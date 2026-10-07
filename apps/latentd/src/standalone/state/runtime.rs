use super::{
    clock::ProtectedCommandClock, request::RequestKind, role::AdmissionTime,
    InstalledTransactionOperation, StateRequest,
};
use crate::config::NodeSettings;
use crate::standalone::startup_observation::{platform, record, Stage};
use latent_artifacts::{DirectoryArtifactRepository, ReleaseUseEligibility};
use latent_capabilities::namespace::RecoverySelection;
use latent_core::{
    native_capacity::{NativeCapacityLimits, NativeCapacityOwner},
    ActivationClock, PlatformError,
};
use latent_effects::{
    authority::EffectAuthorityOwner,
    runtime::{CommandAdmissionSource, DispatcherConfig},
};
use latent_node::{
    command_waiters::{CommandWaiterConfig, CommandWaiterRegistry},
    transaction_runtime::{
        command_completion::{CommandCoordinator, CommandResultCodec},
        query::{QueryAdmission, QueryOwners, QueryScope, QuerySelection},
        CommandTimeSource,
    },
    TransactionActivationAdmission,
};
use latent_policy::capability::PolicyStore;
use latent_state::{
    namespace::{catalog::NamespaceCatalog, NamespaceQuota},
    protected_store::{ProtectedStoreConfig, ProtectedStoreOwner, ProtectedStoreStartup},
};
use latent_wire::{
    management::LocalManagementPolicy,
    phase4::{
        StateManagementBackend, StateManagementBinding, StateManagementRecoveryAdmission,
        StateManagementServices,
    },
};
use std::sync::Arc;

pub(super) struct Inner {
    pub store: Arc<ProtectedStoreOwner>,
    pub policy: Arc<PolicyStore>,
    pub artifacts: Arc<DirectoryArtifactRepository>,
    pub namespaces: Arc<NamespaceCatalog>,
    pub native: NativeCapacityOwner,
    pub source: CommandAdmissionSource,
    pub waiters: CommandWaiterRegistry,
    pub installed: Vec<Arc<InstalledTransactionOperation>>,
    pub intents: Vec<super::effects::InstalledIntent>,
    pub epoch: u64,
    pub profile: String,
    pub configuration_digest: String,
    pub management: Option<StateManagementBackend>,
    pub recovery_selections: Vec<crate::config::state::RecoverySelectorConfig>,
    pub maintenance: Arc<latent_commit::atomic::ResultMaintenanceOwner>,
    pub maintenance_clock: Arc<dyn latent_wire::phase4::StateMaintenanceClock>,
}
#[derive(Clone)]
pub struct StateRuntime(pub(super) Arc<Inner>);
impl StateRuntime {
    /// Actual opened state owner's immutable profile. This observation grants no
    /// namespace, result, staging or dispatch authority.
    #[must_use]
    pub fn inspection_profile(&self) -> (&str, &str, u64) {
        (&self.0.profile, &self.0.configuration_digest, self.0.epoch)
    }

    pub(in crate::standalone) async fn open(
        settings: &NodeSettings,
        artifacts: Arc<DirectoryArtifactRepository>,
        policy: Arc<PolicyStore>,
        clock: Arc<dyn ActivationClock>,
        audit: Option<latent_audit::AuditHandle>,
        control: tokio::runtime::Handle,
        providers: Option<&super::super::providers::ProviderRuntime>,
    ) -> Result<(Arc<Self>, super::super::EffectRuntime), PlatformError> {
        let state = platform(
            Stage::StateConfiguration,
            settings.state.as_ref().ok_or_else(super::denied),
        )?;
        let time = platform(
            Stage::StateClock,
            ProtectedCommandClock::load(settings, Arc::clone(&clock)),
        )?;
        let installed = platform(
            Stage::StateOperations,
            super::load_operations(&artifacts, state.operations.clone()).await,
        )?;
        let (native, waiters) = startup_capacity(&clock)?;
        let authority =
            EffectAuthorityOwner::new(128, 2, time.minimum_checkpoint().1).map_err(|reason| {
                record(Stage::EffectAuthority, reason);
                super::unavailable()
            })?;
        let effect_time: Arc<dyn latent_effects::runtime::EffectTimeSource> = time.clone();
        let installation = platform(
            Stage::EffectInstallation,
            super::effects::install(
                settings,
                &installed,
                providers,
                &policy,
                &authority,
                &effect_time,
            ),
        )?;
        let (store, startup_deadline) = open_validated_store(settings, Arc::clone(&clock)).await?;
        if let Err(reason) = store.bind_native_capacity(&native) {
            record(Stage::NativeCapacity, reason);
            retire_startup_store(
                &store,
                std::time::Instant::now() + settings.shutdown_grace(),
            )
            .await;
            return Err(super::unavailable());
        }
        let effects = super::super::EffectRuntime::start(
            DispatcherConfig::default(),
            Arc::clone(&store),
            authority,
            installation.adapters,
            time.clone(),
            Some(time.minimum_checkpoint()),
            control,
        )
        .await;
        let mut effects = match effects {
            Ok(effects) => effects,
            Err(error) => {
                retire_startup_store(
                    &store,
                    std::time::Instant::now() + settings.shutdown_grace(),
                )
                .await;
                return Err(error);
            }
        };
        // The original empty protected owner must spend its affine creation
        // witness on the real dispatcher epoch before quota metadata is
        // written. Tenant constraints still finish before any StateRuntime or
        // Node admission is published, under the original startup cutoff.
        finish_tenant_setup(
            settings,
            &store,
            &native,
            &installed,
            &mut effects,
            startup_deadline,
        )
        .await?;
        let (profile, digest) = store.inspection_profile();
        let configuration_digest = format!("sha256:{:x}", latent_core::digest::HexDigest(digest));
        let source = effects.command_admission_source();
        let namespaces = Arc::new(NamespaceCatalog::new());
        let inner = Inner {
            store,
            policy,
            artifacts,
            namespaces,
            native,
            source,
            waiters,
            installed,
            intents: installation.intents,
            epoch: state.configuration_epoch,
            profile: profile.into(),
            configuration_digest,
            management: None,
            recovery_selections: state.recovery_selections.clone(),
            maintenance: Arc::new(latent_commit::atomic::ResultMaintenanceOwner::default()),
            maintenance_clock: time,
        };
        finish_open(inner, effects, clock, audit, settings.shutdown_grace()).await
    }
    pub fn installed(
        &self,
        target: &latent_routing::InvocationTarget,
        publication: &ReleaseUseEligibility,
    ) -> Result<Arc<InstalledTransactionOperation>, PlatformError> {
        publication.check_current()?;
        let selected = self
            .0
            .installed
            .iter()
            .find(|op| {
                op.target() == target
                    && op.publication().cache_digest() == publication.cache_digest()
            })
            .ok_or_else(super::denied)?;
        selected.publication().check_current()?;
        Ok(Arc::clone(selected))
    }
    pub fn admission(
        &self,
        installed: Arc<InstalledTransactionOperation>,
        request: StateRequest,
        codec: Arc<dyn CommandResultCodec>,
    ) -> Result<Arc<dyn TransactionActivationAdmission>, PlatformError> {
        self.check_installed(&installed)?;
        let time = AdmissionTime::new(self.0.source.clone(), self.0.native.clone());
        match request.kind {
            RequestKind::Command {
                client_id,
                conditions,
                business_metadata,
                retry,
            } => {
                if installed.mode() != latent_manifest::TransactionOperationMode::StrictCommand {
                    return Err(super::denied());
                }
                let factory = super::command::Factory {
                    runtime: self.clone(),
                    installed,
                    request: super::command::Request {
                        client_id,
                        conditions,
                        metadata: business_metadata,
                        retry,
                    },
                    codec,
                    time: time.clone(),
                };
                Ok(self.coordinator(time).admission(Arc::new(factory)))
            }
            RequestKind::Query { minimum_view } => {
                let selected = QuerySelection::installed(
                    installed.target.clone(),
                    installed.publication.clone(),
                    &installed.companion,
                    &installed.target.service.0,
                    &installed.companion.deployment,
                    QueryScope {
                        incarnation: installed.incarnation,
                        entity: installed.entity.clone(),
                        recovery: RecoverySelection::OriginalCaller,
                        result_policy: installed.result_policy.clone(),
                        minimum_view_token: minimum_view,
                    },
                )?;
                Ok(Arc::new(QueryAdmission::new(
                    QueryOwners {
                        store: Arc::clone(&self.0.store),
                        policy: Arc::clone(&self.0.policy),
                        namespaces: Arc::clone(&self.0.namespaces),
                        time,
                    },
                    selected,
                    self.binding(&installed),
                )?))
            }
        }
    }
    pub fn result_admission(
        &self,
        installed: Arc<InstalledTransactionOperation>,
        original_id: String,
        codec: Arc<dyn CommandResultCodec>,
    ) -> Result<Arc<dyn TransactionActivationAdmission>, PlatformError> {
        self.check_installed(&installed)?;
        super::request::client_key(&original_id)?;
        if installed.mode() != latent_manifest::TransactionOperationMode::StrictCommand {
            return Err(super::denied());
        }
        Ok(Arc::new(super::result::ResultAdmission::new(
            self.clone(),
            installed,
            original_id,
            codec,
        )))
    }
    pub(super) fn coordinator(&self, time: Arc<dyn CommandTimeSource>) -> CommandCoordinator {
        CommandCoordinator::new(
            Arc::clone(&self.0.store),
            self.0.waiters.clone(),
            Some(self.0.source.effect_authority()),
            time,
        )
    }
    fn check_installed(
        &self,
        installed: &Arc<InstalledTransactionOperation>,
    ) -> Result<(), PlatformError> {
        if !self.0.installed.iter().any(|op| Arc::ptr_eq(op, installed)) {
            return Err(super::denied());
        }
        installed.publication.check_current()
    }
    pub(crate) fn management(&self) -> Option<StateManagementBackend> {
        self.0.management.clone()
    }
}
async fn finish_open(
    mut inner: Inner,
    mut effects: super::super::EffectRuntime,
    clock: Arc<dyn ActivationClock>,
    audit: Option<latent_audit::AuditHandle>,
    grace: std::time::Duration,
) -> Result<(Arc<StateRuntime>, super::super::EffectRuntime), PlatformError> {
    match platform(
        Stage::StateManagement,
        management(&inner, effects.management_port(), clock, audit),
    ) {
        Ok(management) => inner.management = management,
        Err(error) => {
            retire_startup_services(&mut effects, &inner.store, grace).await;
            return Err(error);
        }
    }
    Ok((Arc::new(StateRuntime(Arc::new(inner))), effects))
}
async fn open_store(
    settings: &NodeSettings,
    clock: Arc<dyn ActivationClock>,
    validator: super::validation::StartupValidation,
) -> Result<Arc<ProtectedStoreOwner>, PlatformError> {
    let state = settings.state.as_ref().ok_or_else(super::denied)?;
    let mut config =
        ProtectedStoreConfig::bounded_linux(state.protected_root(&settings.data_directory));
    config.create_if_missing = settings
        .state
        .as_ref()
        .ok_or_else(super::denied)?
        .create_if_missing;
    let mut startup = ProtectedStoreOwner::start_validated_view_with_clock(
        config,
        super::validation::STARTUP_VALIDATION_BYTES,
        move |view| validator.validate(view),
        clock,
    )
    .map_err(|reason| {
        record(Stage::ProtectedStoreAdmission, reason);
        super::unavailable()
    })?;
    match (&mut startup).await {
        Ok(owner) => Ok(Arc::new(owner)),
        Err(reason) => {
            record(Stage::ProtectedStoreStartup, reason);
            retire_failed_startup(
                &startup,
                std::time::Instant::now() + settings.shutdown_grace(),
            )
            .await;
            Err(super::unavailable())
        }
    }
}
async fn open_validated_store(
    settings: &NodeSettings,
    clock: Arc<dyn ActivationClock>,
) -> Result<(Arc<ProtectedStoreOwner>, std::time::Instant), PlatformError> {
    let state = settings.state.as_ref().ok_or_else(super::denied)?;
    let deadline = std::time::Instant::now() + settings.shutdown_grace();
    let validator = platform(
        Stage::StateConfiguration,
        super::validation::startup(state, deadline),
    )?;
    let store = open_store(settings, clock, validator).await?;
    Ok((store, deadline))
}
async fn finish_tenant_setup(
    settings: &NodeSettings,
    store: &Arc<ProtectedStoreOwner>,
    native: &NativeCapacityOwner,
    installed: &[Arc<InstalledTransactionOperation>],
    effects: &mut super::super::EffectRuntime,
    deadline: std::time::Instant,
) -> Result<(), PlatformError> {
    let state = settings.state.as_ref().ok_or_else(super::denied)?;
    if let Err(error) = platform(
        Stage::ProtectedStoreStartup,
        super::tenant_setup::install(store, native, &state.tenant_quotas, installed, deadline)
            .await,
    ) {
        retire_startup_services(effects, store, settings.shutdown_grace()).await;
        return Err(error);
    }
    Ok(())
}
async fn retire_startup_services(
    effects: &mut super::super::EffectRuntime,
    store: &ProtectedStoreOwner,
    grace: std::time::Duration,
) {
    effects.close();
    let deadline = std::time::Instant::now() + grace;
    if !effects
        .shutdown(deadline)
        .await
        .is_ok_and(|report| report.clean)
    {
        store.quarantine();
    }
    retire_startup_store(store, deadline).await;
}
fn startup_capacity(
    clock: &Arc<dyn ActivationClock>,
) -> Result<(NativeCapacityOwner, CommandWaiterRegistry), PlatformError> {
    let native = platform(
        Stage::NativeCapacity,
        NativeCapacityOwner::with_clock(NativeCapacityLimits::default(), Arc::clone(clock))
            .map_err(|_| super::capacity()),
    )?;
    let waiters = platform(
        Stage::CommandWaiters,
        CommandWaiterRegistry::new(CommandWaiterConfig::default()).map_err(|_| super::capacity()),
    )?;
    Ok((native, waiters))
}
async fn retire_startup_store(store: &ProtectedStoreOwner, deadline: std::time::Instant) {
    store.close();
    let Ok(drain) = store.drain_async(deadline, tokio::time::sleep_until(deadline.into())) else {
        store.quarantine();
        return;
    };
    if !drain.await.clean || store.reap_retired_threads().is_err() {
        store.quarantine();
    }
}
async fn retire_failed_startup(startup: &ProtectedStoreStartup, deadline: std::time::Instant) {
    startup.close();
    let Ok(drain) = startup.drain_async(deadline, tokio::time::sleep_until(deadline.into())) else {
        startup.quarantine();
        return;
    };
    if !drain.await.clean || startup.reap_retired_threads().is_err() {
        startup.quarantine();
    }
}
fn management(
    inner: &Inner,
    dispatcher: latent_effects::runtime::DispatcherManagementPort,
    clock: Arc<dyn ActivationClock>,
    audit: Option<latent_audit::AuditHandle>,
) -> Result<Option<StateManagementBackend>, PlatformError> {
    let mut bindings: Vec<StateManagementBinding> = Vec::new();
    for op in &inner.installed {
        if bindings.iter().any(|b| {
            b.publication.id == *op.publication.publication() && b.namespace.0 == op.namespace()
        }) {
            continue;
        }
        bindings.push(StateManagementBinding {
            publication: latent_artifacts::PublicationRef {
                id: op.publication.publication().clone(),
                scope: op.publication.scope().clone(),
            },
            component: op.publication.release().clone(),
            service: op.target.service.clone(),
            namespace: latent_core::StateNamespaceId(op.namespace().into()),
            incarnation: op.incarnation,
            state_schema: op.state_schema().into(),
            result_policy: op.result_policy.clone(),
            maximum_quota: NamespaceQuota::default(),
            state: super::authorization::management_binding(inner, op),
        });
    }
    let backend = StateManagementBackend::with_installed_dispatcher(
        StateManagementServices {
            store: Arc::clone(&inner.store),
            namespaces: Arc::clone(&inner.namespaces),
            policy: Arc::clone(&inner.policy),
            artifacts: inner.artifacts.clone(),
            authorization: Arc::new(LocalManagementPolicy),
            admission: Arc::new(StateManagementRecoveryAdmission::new(inner.native.clone())),
            clock,
            audit,
            maintenance: Arc::clone(&inner.maintenance),
            maintenance_clock: Arc::clone(&inner.maintenance_clock),
        },
        bindings,
        dispatcher,
    )?;
    // Trusted installation selects descriptive scope data. Effect management
    // still seals current data-read/action decisions; application commands keep
    // their separately bound OriginalCaller admission.
    Ok(Some(
        backend.with_recovery_bindings(
            inner
                .recovery_selections
                .iter()
                .map(|value| value.binding())
                .collect(),
        )?,
    ))
}

#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod tests;

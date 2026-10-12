//! Installed targets are captured by the original protected recovery worker.
mod http;
mod policy;
mod selection;
#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod tests;
#[cfg(test)]
use latent_policy::supply_chain::{SupplyChainClock, SupplyChainPolicy};

use std::sync::Arc;

use latent_artifacts::{DirectoryArtifactRepository, TRANSACTION_ASSET_RESPONSE_BYTES};
use latent_capabilities::namespace::RecoverySelection;
use latent_commit::atomic::{ReplayPolicy, ResultPolicy};
use latent_control_store::{DeploymentStore, DirectoryDeploymentRepository};
use latent_core::{
    native_capacity::{
        NativeAdmissionClass, NativeBufferClass, NativeBufferPermit, NativeReservation,
        NativeReservationRequest,
    },
    ActivationClock, ContractId, DeploymentId, FunctionId, PlatformError, ServiceId,
    StateNamespaceId,
};
use latent_node::transaction_runtime::{TransactionAdmissionOwners, TransactionInstallation};
use latent_policy::capability::PolicyStore;
use latent_routing::InvocationTarget;
use latent_state::{namespace::catalog::NamespaceCatalog, store_io::StoreIoKind};
use latent_wire::{
    management::LocalManagementPolicy,
    phase4::{
        StateManagementBackend, StateManagementBinding, StateManagementRecoveryAdmission,
        StateManagementServices,
    },
};

use super::StateKernel;
use crate::config::state::{self, OperationSettings, StateSettings};
use crate::standalone::effects::EffectRuntime;

pub(in crate::standalone) struct InstalledStateServices {
    pub artifacts: Arc<DirectoryArtifactRepository>,
    pub deployments: Arc<DirectoryDeploymentRepository>,
    pub clock: Arc<dyn ActivationClock>,
    pub audit: Option<latent_audit::AuditHandle>,
    pub http: InstalledHttpEffects,
}

pub(in crate::standalone) struct InstalledHttpEffects {
    pub(super) clock: Arc<super::AdapterClock>,
    pub(super) adapters: Vec<Arc<latent_http::deferred::HttpEffectAdapter>>,
    registry: Arc<http::DispatchRegistry>,
}
impl InstalledHttpEffects {
    pub(in crate::standalone) fn empty() -> Self {
        Self {
            clock: Arc::new(super::AdapterClock::default()),
            adapters: Vec::new(),
            registry: Arc::new(http::DispatchRegistry::new()),
        }
    }
    pub(in crate::standalone) fn new(
        provider: Option<&crate::standalone::providers::ProviderRuntime>,
        installation: Option<&crate::config::HttpInstallation>,
    ) -> Result<Self, PlatformError> {
        let mut installed = Self::empty();
        if let Some(installation) = installation {
            let provider = provider.ok_or_else(super::unavailable)?;
            installed.adapters = provider
                .typed_deferred_http_adapters(installation, installed.clock.clone())?
                .into_iter()
                .map(|adapter| {
                    // The typed adapter was just constructed from the original provider.
                    let adapter = Arc::try_unwrap(adapter).map_err(|_| super::unavailable())?;
                    Ok(Arc::new(
                        adapter.with_authorization(installed.registry.clone()),
                    ))
                })
                .collect::<Result<Vec<_>, PlatformError>>()?;
        }
        Ok(installed)
    }
}

pub(super) struct InstalledState {
    pub installations: Vec<Arc<TransactionInstallation>>,
    pub management: Option<StateManagementBackend>,
    pub http_rules: bool,
}

struct Resident {
    original: Arc<NativeReservation>,
    metadata: Arc<NativeBufferPermit>,
}

#[expect(
    clippy::too_many_lines,
    reason = "Resident reservations and management custody transfer together across bounded installation groups"
)]
pub(super) async fn load(
    kernel: &StateKernel,
    settings: &StateSettings,
    owners: &Arc<TransactionAdmissionOwners>,
    policy: Arc<PolicyStore>,
    services: InstalledStateServices,
    effects: &EffectRuntime,
) -> Result<InstalledState, PlatformError> {
    let deadline = kernel.original_deadline()?;
    let mut residents = Vec::with_capacity(
        settings
            .operations
            .len()
            .div_ceil(state::INSTALLATION_OPERATIONS_PER_LEASE),
    );
    for chunk in settings
        .operations
        .chunks(state::INSTALLATION_OPERATIONS_PER_LEASE)
    {
        let original = Arc::new(
            kernel
                .native
                .reserve(
                    NativeAdmissionClass::Recovery,
                    NativeReservationRequest {
                        work_bytes: chunk.len() as u64
                            * (state::INSTALLATION_METADATA_BYTES
                                + state::INSTALLATION_SELECTION_BYTES),
                        ..NativeReservationRequest::default()
                    },
                    deadline,
                )
                .map_err(|_| super::unavailable())?,
        );
        let metadata = Arc::new(
            original
                .reserve_buffer(
                    NativeBufferClass::Work,
                    chunk.len() as u64 * state::INSTALLATION_METADATA_BYTES,
                )
                .map_err(|_| super::unavailable())?,
        );
        residents.push(Resident { original, metadata });
    }
    let mut installations = Vec::with_capacity(settings.operations.len());
    let mut bindings: Vec<StateManagementBinding> = Vec::with_capacity(settings.operations.len());
    let mut http_rules = false;
    for (index, operation) in settings.operations.iter().enumerate() {
        let resident = &residents[index / state::INSTALLATION_OPERATIONS_PER_LEASE];
        let (installation, binding) = capture(
            kernel, settings, operation, owners, &services, resident, &policy, effects,
        )
        .await?;
        if let Some(installation) = installation {
            http_rules |= operation.deferred_http.is_some();
            installations.push(Arc::new(installation));
        }
        if let Some(existing) = bindings.iter().find(|existing| {
            existing.publication == binding.publication
                && existing.namespace == binding.namespace
                && existing.incarnation == binding.incarnation
        }) {
            if existing.component != binding.component
                || existing.service != binding.service
                || existing.state_schema != binding.state_schema
                || existing.result_policy != binding.result_policy
                || existing.state.policies != binding.state.policies
                || existing.state.binding != binding.state.binding
            {
                return Err(super::unavailable());
            }
        } else {
            bindings.push(binding);
        }
    }
    let management = if bindings.is_empty() {
        None
    } else {
        Some(
            StateManagementBackend::new(
                StateManagementServices {
                    store: Arc::clone(&kernel.store),
                    namespaces: Arc::clone(&kernel.namespaces),
                    policy,
                    artifacts: services.artifacts,
                    authorization: Arc::new(LocalManagementPolicy),
                    admission: Arc::new(StateManagementRecoveryAdmission::new(
                        kernel.native.clone(),
                    )),
                    clock: services.clock,
                    maintenance: Arc::clone(&kernel.maintenance),
                    maintenance_clock: Arc::new(
                        super::maintenance::ProtectedMaintenanceClock::new(Arc::clone(
                            &kernel.clock,
                        ))?,
                    ),
                    audit: services.audit,
                },
                bindings,
            )?
            .with_dispatcher(effects.management_port())?
            .with_command_recovery(effects.command_admission_source())?
            .with_resident_metadata(
                residents
                    .into_iter()
                    .map(|resident| resident.metadata)
                    .collect(),
            )?,
        )
    };
    Ok(InstalledState {
        installations,
        management,
        http_rules,
    })
}

#[expect(
    clippy::too_many_lines,
    reason = "Original capture admission, fixed worker custody and metadata transfer retire in one visible scope"
)]
#[allow(
    clippy::too_many_arguments,
    reason = "The original kernel, native, policy and effect owners are independently explicit"
)]
async fn capture(
    kernel: &StateKernel,
    settings: &StateSettings,
    operation: &OperationSettings,
    owners: &Arc<TransactionAdmissionOwners>,
    services: &InstalledStateServices,
    resident: &Resident,
    policy: &Arc<PolicyStore>,
    effects: &EffectRuntime,
) -> Result<(Option<TransactionInstallation>, StateManagementBinding), PlatformError> {
    let deadline = kernel.original_deadline()?;
    let original = Arc::new(
        kernel
            .native
            .reserve(
                NativeAdmissionClass::Recovery,
                NativeReservationRequest {
                    request_bytes: state::INSTALLATION_CAPTURE_REQUEST_BYTES,
                    work_bytes: state::INSTALLATION_CAPTURE_WORK_BYTES,
                    response_bytes: TRANSACTION_ASSET_RESPONSE_BYTES,
                },
                deadline,
            )
            .map_err(|_| super::unavailable())?,
    );
    let request = original
        .reserve_buffer(
            NativeBufferClass::Request,
            state::INSTALLATION_CAPTURE_REQUEST_BYTES,
        )
        .map_err(|_| super::unavailable())?;
    let scratch = original
        .reserve_buffer(NativeBufferClass::Work, 2 * 1024 * 1024)
        .map_err(|_| super::unavailable())?;
    let deployment = tokio::time::timeout_at(
        deadline.into(),
        services.deployments.get_versioned(
            &operation.tenant,
            &DeploymentId(operation.deployment.clone()),
        ),
    )
    .await
    .map_err(|_| super::unavailable())??
    .ok_or_else(super::unavailable)?;
    let state_binding = policy::state_binding(settings, operation, &deployment.manifest)?;
    let management_state = policy::state_binding(settings, operation, &deployment.manifest)?;
    let quota = policy::maximum_quota(settings, operation)?;
    let operation = operation.clone();
    let artifacts = Arc::clone(&services.artifacts);
    let deployments = Arc::clone(&services.deployments);
    let namespaces = Arc::clone(&kernel.namespaces);
    let native = kernel.native.clone();
    let resident_original = Arc::clone(&resident.original);
    let metadata_memory = Arc::clone(&resident.metadata);
    let charge = state::INSTALLATION_CAPTURE_REQUEST_BYTES
        + state::INSTALLATION_CAPTURE_WORK_BYTES
        + TRANSACTION_ASSET_RESPONSE_BYTES;
    let worker_original = Arc::clone(&original);
    let owners = Arc::clone(owners);
    let policy = Arc::clone(policy);
    let adapters = services.http.adapters.clone();
    let registry = Arc::clone(&services.http.registry);
    let authority = effects.command_admission_source().effect_authority();
    let job = kernel
        .store
        .with_store_retaining(StoreIoKind::RecoveryRead, charge, original, move |engine| {
            // Invalid selectors do not corrupt or quarantine an otherwise valid store.
            let mut storage_failure = None;
            let result = (|| {
                let asset = artifacts.capture_selected_transaction_asset(
                    &operation.tenant,
                    &operation.component,
                    &operation.publication,
                    &native,
                    Arc::clone(&worker_original),
                )?;
                policy::check_asset(asset.get(), &operation, &deployment.manifest)?;
                let target = InvocationTarget {
                    tenant: operation.tenant.clone(),
                    service: ServiceId(asset.get().metadata().manifest().metadata.name.clone()),
                    contract: ContractId(operation.contract.clone()),
                    function: FunctionId(operation.function.clone()),
                    route: operation.route.clone(),
                };
                let view = engine.snapshot().map_err(|error| {
                    storage_failure = Some(error);
                    super::unavailable()
                })?;
                let namespace = NamespaceCatalog::read_in(
                    &view,
                    &operation.tenant,
                    &StateNamespaceId(asset.get().declaration().namespace.clone()),
                )
                .map_err(|error| {
                    use latent_state::{embedded::StoreError, namespace::NamespaceError};
                    storage_failure = match error {
                        NamespaceError::Corrupt => Some(StoreError::Corrupt),
                        NamespaceError::UnsupportedFormat => Some(StoreError::UnsupportedFormat),
                        NamespaceError::Unavailable => Some(StoreError::Unavailable),
                        _ => None,
                    };
                    super::unavailable()
                })?;
                drop(view);
                let selected = if let Some(namespace) = namespace {
                    if namespace.record().version.incarnation != operation.incarnation {
                        return Err(super::unavailable());
                    }
                    let selected = deployments.capture_transaction_selection(
                        asset.get(),
                        &target,
                        None,
                        operation.entity.as_deref(),
                        namespace,
                        &namespaces,
                        &native,
                        Arc::clone(&worker_original),
                    )?;
                    selected.check_deployment(&deployment.manifest)?;
                    Some(selected.into_resident(&native, resident_original)?)
                } else {
                    None
                };
                let intents = http::install(
                    asset.get(),
                    &operation,
                    &deployment.manifest,
                    &adapters,
                    &policy,
                    &authority,
                    selected.as_ref(),
                    &worker_original,
                    deadline,
                    &registry,
                    Arc::clone(&metadata_memory),
                )?;
                asset.get().with_current(&mut |_| Ok(()))?;
                let (asset, capture_memory) = asset.into_parts();
                let (metadata, declaration, publication, _digest, _original) = asset.into_parts();
                let binding =
                    policy::management_binding(&operation, &declaration, quota, management_state);
                let installation = if let Some(selected) = selected {
                    Some(
                        TransactionInstallation::new(
                            metadata,
                            declaration,
                            &deployment.manifest,
                            publication,
                            Arc::new(state_binding),
                            intents,
                            RecoverySelection::OriginalCaller,
                            operation.result_policy,
                            ResultPolicy {
                                replay: ReplayPolicy::Full,
                                maximum_result_bytes:
                                    latent_core::transaction_contract::VALUE_BYTES,
                                result_millis: 86_400_000,
                                identity_millis: 604_800_000,
                                maximum_attempts: 16,
                            },
                        )?
                        .with_current_selection(
                            Arc::new(selection::ChargedSelection::new(
                                selected,
                                Arc::clone(&metadata_memory),
                            )),
                            &owners,
                        )?,
                    )
                } else {
                    None
                };
                drop(capture_memory);
                Ok((installation, binding))
            })();
            if let Some(error) = storage_failure {
                return Err(error);
            }
            Ok((result, request, scratch, worker_original, metadata_memory))
        })
        .map_err(|_| super::unavailable())?;
    let (result, _request, _scratch, _original, _metadata) =
        tokio::time::timeout_at(deadline.into(), job)
            .await
            .map_err(|_| super::unavailable())?
            .map_err(|_| super::unavailable())?
            .map_err(|_| super::unavailable())?;
    result
}

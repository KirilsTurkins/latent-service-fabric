//! Same-owner startup composition before any transaction transport is exposed.
use std::sync::Arc;
use std::time::Instant;

use latent_core::{
    native_capacity::{NativeCapacityOwner, NativeCapacityShutdown},
    PlatformError,
};
use latent_effects::runtime::DeferredEffectAdapter;
use latent_policy::{capability::PolicyStore, supply_chain::SupplyChainAuthority};
use latent_state::{
    namespace::catalog::NamespaceCatalog,
    protected_store::{ProtectedCheckpointConfig, ProtectedStoreOwner},
    store_io::StoreIoShutdown,
};

use super::super::effects::{EffectRuntime, ProtectedEffectClock, ProtectedEffectStartup};
use super::{bootstrap::StateBootstrap, clock::AdapterClock, preparation};
use crate::config::state::StateSettings;

/// A kernel is still paused when returned. The caller must validate the actual
/// signed installations/current permissions and install all original runtime
/// owners before exposing transport readiness or releasing bootstrap pause.
pub(super) struct StateKernel {
    pub(super) store: Arc<ProtectedStoreOwner>,
    pub(super) namespaces: Arc<NamespaceCatalog>,
    pub(super) clock: Arc<ProtectedEffectClock>,
    pub(super) native: NativeCapacityOwner,
    // LAST: actual root/engine and metadata keepers also retain this original
    // admission through native destruction, even if this startup waiter drops.
    bootstrap: Option<StateBootstrap>,
}

#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
pub(super) mod tests;

pub(super) struct StateShutdownReport {
    pub store: StoreIoShutdown,
    pub native: NativeCapacityShutdown,
    pub namespace_owners: usize,
    pub clean: bool,
}

impl StateKernel {
    pub(super) fn original_deadline(&self) -> Result<Instant, PlatformError> {
        self.bootstrap
            .as_ref()
            .map(|bootstrap| bootstrap.deadline)
            .ok_or_else(super::unavailable)
    }

    pub(super) fn check_ready(&self, effects: &EffectRuntime) -> Result<(), PlatformError> {
        let bootstrap = self.bootstrap.as_ref().ok_or_else(super::unavailable)?;
        bootstrap.check_live()?;
        self.clock.sample()?;
        let store = self.store.snapshot().map_err(|_| super::unavailable())?;
        let source = effects.command_admission_source();
        if !source.uses_store(&self.store)
            || !source.uses_native_capacity(&self.native)
            || !source.uses_effect_authority(&bootstrap.authority)
        {
            return Err(super::unavailable());
        }
        source.command_time().map_err(|_| super::unavailable())?;
        let effects = effects.snapshot()?;
        if store.admission_closed
            || store.quarantined
            || store.physically_retired()
            || effects.admission_closed
            || effects.quarantined
            || !effects.paused
        {
            return Err(super::unavailable());
        }
        Ok(())
    }

    pub(super) fn is_running(&self, effects: &EffectRuntime) -> bool {
        self.clock.sample().is_ok()
            && self.store.snapshot().is_ok_and(|snapshot| {
                !snapshot.admission_closed
                    && !snapshot.quarantined
                    && !snapshot.physically_retired()
            })
            && effects
                .snapshot()
                .is_ok_and(|snapshot| !snapshot.admission_closed && !snapshot.quarantined)
            && effects.command_admission_source().command_time().is_ok()
    }

    /// The early empty authority in `bootstrap` is the same owner already
    /// attached to the original artifact and policy rejection observers. This
    /// method installs no rule from configuration or a retained policy stamp.
    pub(super) async fn start(
        mut bootstrap: StateBootstrap,
        settings: &StateSettings,
        supply_chain: Arc<SupplyChainAuthority>,
        adapters: Vec<Arc<dyn DeferredEffectAdapter>>,
        adapter_clock: &AdapterClock,
        control_runtime: tokio::runtime::Handle,
    ) -> Result<(Self, EffectRuntime), PlatformError> {
        bootstrap.check_live()?;
        if !bootstrap.matches(settings) {
            return Err(super::unavailable());
        }
        let store = bootstrap.open_store(settings).await?;
        let namespaces = match bootstrap.open_namespaces(settings) {
            Ok(namespaces) => namespaces,
            Err(failure) => {
                retire_failed_bootstrap(bootstrap).await;
                return Err(failure);
            }
        };
        let preparation = match preparation::tenant_installation(settings) {
            Ok(preparation) => preparation,
            Err(failure) => {
                drop(namespaces);
                retire_failed_bootstrap(bootstrap).await;
                return Err(failure);
            }
        };
        // The mode leaf uses this actual initializer's sealed Fresh metadata.
        // Verify it before checkpoint consumes the once-only witness and before
        // dispatcher history writes. Neither reopened equality nor config may
        // recreate a missing persisted mode marker.
        let marker =
            store.ensure_state_mode_marker(settings.store_identity.clone(), bootstrap.original());
        let marker = if let Ok(marker) = marker {
            tokio::time::timeout_at(bootstrap.deadline.into(), marker).await
        } else {
            drop(namespaces);
            retire_failed_bootstrap(bootstrap).await;
            return Err(super::unavailable());
        };
        if !matches!(marker, Ok(Ok(Ok(_)))) {
            drop(namespaces);
            retire_failed_bootstrap(bootstrap).await;
            return Err(super::unavailable());
        }
        let protected = EffectRuntime::start_protected(ProtectedEffectStartup {
            dispatcher: settings.dispatcher.clone(),
            store: Arc::clone(&store),
            authority: bootstrap.authority.clone(),
            adapters,
            supply_chain,
            clock: Arc::clone(&bootstrap.clock),
            checkpoint: ProtectedCheckpointConfig {
                root: settings.checkpoint_root.clone(),
            },
            identity: settings.store_identity.clone(),
            preparation,
            original_deadline: bootstrap.deadline,
            control_runtime,
        })
        .await;
        let (mut effects, clock) = match protected {
            Ok(protected) => protected,
            Err(failure) => {
                drop(namespaces);
                retire_failed_bootstrap(bootstrap).await;
                return Err(failure);
            }
        };
        let deadline = bootstrap.deadline;
        let kernel = Self {
            store,
            namespaces,
            clock,
            native: bootstrap.native.clone(),
            bootstrap: Some(bootstrap),
        };
        // Adapters retain only a once-bound projection of this exact admitted
        // clock. No provider is accepted before this binding and cutover.
        let acceptance = adapter_clock
            .bind(Arc::clone(&kernel.clock))
            .and_then(|()| kernel.check_ready(&effects))
            .and_then(|()| {
                kernel
                    .namespaces
                    .uses_native_capacity(&kernel.native)
                    .then_some(())
                    .ok_or_else(super::unavailable)
            });
        if let Err(failure) = acceptance {
            let _retirement = effects.shutdown(deadline).await;
            drop(effects);
            let _retirement = kernel.shutdown(deadline).await;
            return Err(failure);
        }
        Ok((kernel, effects))
    }

    pub(super) fn admission_owners(
        &self,
        policy: Arc<PolicyStore>,
        effects: &EffectRuntime,
    ) -> Result<Arc<latent_node::transaction_runtime::TransactionAdmissionOwners>, PlatformError>
    {
        let bootstrap = self.bootstrap.as_ref().ok_or_else(super::unavailable)?;
        bootstrap.check_live()?;
        let observer = bootstrap.authority.rejection_observer();
        if !policy.rejection_observer_matches(&observer)
            || !self.namespaces.uses_native_capacity(&self.native)
        {
            return Err(super::unavailable());
        }
        self.clock.sample()?;
        latent_node::transaction_runtime::TransactionAdmissionOwners::new(
            Arc::clone(&self.store),
            Arc::clone(&self.namespaces),
            policy,
            effects.command_admission_source(),
        )
        .map(Arc::new)
    }

    /// Used only after the node has closed and positively retired its original
    /// provider/command/transport cleanup owners. A detached drain never proves
    /// physical retirement; all lower keepers retain their original capacity.
    pub(super) async fn shutdown(
        self,
        deadline: Instant,
    ) -> Result<StateShutdownReport, PlatformError> {
        let Self {
            store: owner,
            namespaces,
            clock: _,
            native: capacity,
            bootstrap,
        } = self;
        capacity.close();
        namespaces
            .lifecycle()
            .retire()
            .map_err(|_| super::unavailable())?;
        let namespace_owners = namespaces.lifecycle().retained_owners();
        owner.close();
        let store = owner
            .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
            .map_err(|_| super::unavailable())?
            .await;
        if store.snapshot.physically_retired() {
            owner
                .reap_retired_threads()
                .map_err(|_| super::unavailable())?;
        }
        // Release the startup shell only after the actual store report. A live
        // engine or namespace holder still owns the same lease independently.
        drop(namespaces);
        drop(bootstrap);
        let native = capacity
            .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
            .map_err(|_| super::unavailable())?
            .await;
        Ok(StateShutdownReport {
            clean: store.clean && native.clean && namespace_owners == 0,
            store,
            native,
            namespace_owners,
        })
    }
}

/// Failure cleanup observes the same accepted initializer and original cutoff.
/// A late physical owner remains quarantined and charged; it never yields an
/// abort proof or an extension of the original boot authority.
async fn retire_failed_bootstrap(bootstrap: StateBootstrap) {
    let deadline = bootstrap.deadline;
    let native = bootstrap.native.clone();
    if let Some(namespaces) = &bootstrap.namespaces {
        let _retirement = namespaces.lifecycle().retire();
    }
    if let Some(store) = &bootstrap.opened_store {
        store.close();
        if let Ok(retirement) =
            store.drain_async(deadline, tokio::time::sleep_until(deadline.into()))
        {
            let report = retirement.await;
            if report.snapshot.physically_retired() {
                let _retirement = store.reap_retired_threads();
            }
            if report.snapshot.quarantined {
                native.quarantine();
            }
        }
    }
    drop(bootstrap);
    native.close();
    if let Ok(retirement) = native.drain_async(deadline, tokio::time::sleep_until(deadline.into()))
    {
        let _retirement = retirement.await;
    }
}

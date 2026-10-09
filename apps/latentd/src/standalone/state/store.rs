//! Original protected initialization; callers never receive an unbound engine.
use std::sync::Arc;

use latent_core::{native_capacity::NativeCapacityOwner, PlatformError};
use latent_state::protected_store::{ProtectedStoreOwner, ProtectedStoreStartup};

use super::{bootstrap::StateBootstrap, validation};
use crate::config::state::{StateSettings, STARTUP_VALIDATOR_BYTES};

/// This guard is private to one startup future. Losing that future closes the
/// original global owner and quarantines accepted native initialization, while
/// the lower fixed worker continues to own its actual descriptors and buffers.
struct StartingStore {
    startup: ProtectedStoreStartup,
    native: NativeCapacityOwner,
    delivered: bool,
}

impl Drop for StartingStore {
    fn drop(&mut self) {
        if !self.delivered {
            self.startup.quarantine();
            self.native.quarantine();
        }
    }
}

impl StateBootstrap {
    /// Prepaid initialization runs on the same fixed node storage workers used
    /// by commands and recovery. The exact initial identity transaction is the
    /// only producer of Fresh checkpoint evidence, never matching config bytes.
    pub(super) async fn open_store(
        &mut self,
        settings: &StateSettings,
    ) -> Result<Arc<ProtectedStoreOwner>, PlatformError> {
        self.open_store_inner(settings, None).await
    }

    async fn open_store_inner(
        &mut self,
        settings: &StateSettings,
        before_validation: Option<Box<dyn FnOnce() + Send>>,
    ) -> Result<Arc<ProtectedStoreOwner>, PlatformError> {
        self.check_live()?;
        if self.opened_store.is_some() || !self.matches(settings) {
            return Err(super::unavailable());
        }
        let original = self.original();
        let identity = settings.store_identity.clone();
        let quotas = validation::quotas(settings);
        let initializer = ProtectedStoreOwner::start_bound_retained_validated_view_with_clock(
            settings.store.clone(),
            identity.clone(),
            self.take_memory()?,
            STARTUP_VALIDATOR_BYTES,
            move |view| {
                if let Some(observe) = before_validation {
                    observe();
                }
                validation::validate(view, &identity, &quotas, &original)
            },
            Arc::clone(&self.clock),
        )
        .map_err(|_| super::unavailable())?;
        let mut guard = StartingStore {
            startup: initializer,
            native: self.native.clone(),
            delivered: false,
        };
        let result = tokio::time::timeout_at(self.deadline.into(), &mut guard.startup).await;
        let store = if let Ok(Ok(store)) = result {
            Arc::new(store)
        } else {
            // Observation timeout is never abort or physical retirement.
            // The original absolute cutoff remains unchanged for cleanup;
            // accepted work keeps its original memory if it cannot finish.
            guard.startup.quarantine();
            if let Ok(drain) = guard.startup.drain_async(
                self.deadline,
                tokio::time::sleep_until(self.deadline.into()),
            ) {
                let _report = drain.await;
            }
            return Err(super::unavailable());
        };
        if !store.uses_native_capacity(&self.native) || self.check_live().is_err() {
            store.quarantine();
            self.native.quarantine();
            if let Ok(drain) = store.drain_async(
                self.deadline,
                tokio::time::sleep_until(self.deadline.into()),
            ) {
                let _report = drain.await;
            }
            return Err(super::unavailable());
        }
        // Keep the actual owner in the original boot lifetime until the final
        // standalone runtime has installed current permissions and readiness.
        self.opened_store = Some(Arc::clone(&store));
        guard.delivered = true;
        Ok(store)
    }
}

#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod tests;

//! Observe final fuel and retain original host owners through Store destruction.

use std::ops::{Deref, DerefMut};

use latent_core::activation_runtime::ActivationRuntime;
use latent_executor::{ExecutionCleanup, ExecutionReport};
use wasmtime::Store;

use crate::host::HostState;

/// Invocation-local trusted evidence, independent of guest trap text.
/// No heap allocation, guest-visible flag, replacement ledger or background retry.
/// A post-Store receipt retains only the existing original ledger, not new credit.
#[derive(Default)]
pub(super) struct RuntimeRetirement {
    entered: bool,
    logical_proven: bool,
    store_destroyed: bool,
    refused: bool,
    repeated_store: bool,
    finalization_attempted: bool,
    lift_proven: bool,
    original_runtime: Option<ActivationRuntime>,
    physical_proven: bool,
}

impl RuntimeRetirement {
    fn enter(&mut self) {
        // A second Store cannot inherit another Store's retirement proof.
        self.refused |= self.entered;
        self.repeated_store |= self.entered;
        self.finalization_attempted = false;
        self.lift_proven = false;
        self.original_runtime = None;
        self.physical_proven = false;
        self.entered = true;
        self.logical_proven = false;
        self.store_destroyed = false;
    }

    fn finalized(&mut self, succeeded: bool) {
        self.finalization_attempted = true;
        self.refused |= !succeeded;
        self.logical_proven = succeeded && !self.refused;
    }

    /// Called once, after native-stack and capability cleanup have finished.
    /// Closing the *same* ledger proves no original owner remains; it cannot
    /// repair a missing physical receipt or an earlier observer's quarantine.
    pub(super) fn after_store_dropped(&mut self) {
        if let Some(runtime) = self.original_runtime.take() {
            self.physical_proven = runtime.retire().is_ok();
        }
    }

    pub(super) fn apply(&self, mut report: ExecutionReport) -> ExecutionReport {
        if self.entered
            && (self.repeated_store
                || !self.store_destroyed
                || !(self.logical_proven && !self.refused || self.physical_proven))
            && matches!(report.cleanup, ExecutionCleanup::Reusable)
        {
            report.cleanup = ExecutionCleanup::Quarantine {
                reason: "runtime-retirement-unproven".into(),
            };
        }
        // Preserve the original outcome, accounting, host-result disposition,
        // and any earlier capability/stack quarantine reason verbatim.
        report
    }
}

/// The pinned engine's ordinary Store::drop destroys T before instance backing.
/// into_data instead returns T after that backing's destruction path has run.
/// Logical finalization and physical Store destruction remain separate facts.
struct StoreCustody<'a, T: 'static> {
    store: Option<Store<T>>,
    retirement: &'a mut RuntimeRetirement,
}

impl<'a, T: 'static> StoreCustody<'a, T> {
    fn new(store: Store<T>, retirement: &'a mut RuntimeRetirement) -> Self {
        retirement.enter();
        Self {
            store: Some(store),
            retirement,
        }
    }

    /// Consumes the actual Store before invoking any host-data destructor.
    /// Only the embedding's audited synchronous allocator may supply a ledger
    /// for the separate, post-Store receipt. Generic custody stays conservative.
    fn destroy(&mut self, original_runtime: impl FnOnce(&T) -> Option<ActivationRuntime>) {
        if let Some(store) = self.store.take() {
            // LSF installs no custom linear-memory creator. Its Linux on-demand
            // mappings retire synchronously; a failed munmap panics before
            // into_data returns. Queued pool decommit is NOT this receipt.
            let synchronous = cfg!(target_os = "linux")
                && store.engine().get_pooling_config().is_none()
                && self.retirement.finalization_attempted
                && self.retirement.lift_proven
                && !self.retirement.repeated_store;
            let data = store.into_data();
            let runtime = synchronous.then(|| original_runtime(&data)).flatten();
            drop(data);
            self.retirement.store_destroyed = true;
            self.retirement.original_runtime = runtime;
        }
    }
}

impl<T: 'static> Deref for StoreCustody<'_, T> {
    type Target = Store<T>;

    fn deref(&self) -> &Self::Target {
        self.store.as_ref().expect("live Store custody")
    }
}

impl<T: 'static> DerefMut for StoreCustody<'_, T> {
    fn deref_mut(&mut self) -> &mut Self::Target {
        self.store.as_mut().expect("live Store custody")
    }
}

impl<T: 'static> Drop for StoreCustody<'_, T> {
    fn drop(&mut self) {
        // A generic Store may use pools or custom memory creators. Completion
        // alone does not prove their OS mappings have been retired.
        self.destroy(|_| None);
    }
}

pub(super) struct AccountedStore<'a> {
    store: StoreCustody<'a, HostState>,
}

impl<'a> AccountedStore<'a> {
    pub(super) fn new(store: Store<HostState>, retirement: &'a mut RuntimeRetirement) -> Self {
        Self {
            store: StoreCustody::new(store, retirement),
        }
    }

    pub(super) fn runtime_finalized(&mut self, succeeded: bool, lift_proven: bool) {
        self.store.retirement.finalized(succeeded);
        self.store.retirement.lift_proven = lift_proven;
    }
}

impl Deref for AccountedStore<'_> {
    type Target = Store<HostState>;

    fn deref(&self) -> &Self::Target {
        &self.store
    }
}

impl DerefMut for AccountedStore<'_> {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.store
    }
}

impl Drop for AccountedStore<'_> {
    fn drop(&mut self) {
        // Final observation precedes engine destruction and owner release.
        // Normal completion already advanced the watermark; cancellation and
        // unwind observe the last unsampled work without inventing consumption.
        if let Ok(fuel) = self.store.get_fuel() {
            let peak = self.store.data().limiter.peak_memory_bytes();
            let _ = self.store.data_mut().accounting.observe_runtime(fuel, peak);
        }
        // Native stacks retain their independent physical observer, including
        // custom owned stacks. It runs before the original ledger is checked.
        self.store.destroy(|data| {
            data.runtime
                .as_ref()
                .map(|table| table.retirement_runtime())
        });
    }
}

#[cfg(test)]
mod tests;

//! Observe final fuel and retain original host owners through Store destruction.

use std::ops::{Deref, DerefMut};

use latent_executor::{ExecutionCleanup, ExecutionReport};
use wasmtime::Store;

use crate::host::HostState;

/// Invocation-local trusted evidence, independent of guest trap text.
/// No heap allocation, guest-visible flag, replacement ledger or cleanup retry.
#[derive(Default)]
pub(super) struct RuntimeRetirement {
    entered: bool,
    logical_proven: bool,
    store_destroyed: bool,
    refused: bool,
}

impl RuntimeRetirement {
    fn enter(&mut self) {
        // A second Store cannot inherit another Store's retirement proof.
        self.refused |= self.entered;
        self.entered = true;
        self.logical_proven = false;
        self.store_destroyed = false;
    }

    fn finalized(&mut self, succeeded: bool) {
        self.refused |= !succeeded;
        self.logical_proven = succeeded && !self.refused;
    }

    pub(super) fn apply(&self, mut report: ExecutionReport) -> ExecutionReport {
        if self.entered
            && (!self.logical_proven || !self.store_destroyed || self.refused)
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
        if let Some(store) = self.store.take() {
            // Consume once, without unsafe extraction or reconstructed tokens.
            // This is not a witness of successful OS decommit on every path.
            let data = store.into_data();
            drop(data);
            self.retirement.store_destroyed = true;
        }
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

    pub(super) fn runtime_finalized(&mut self, succeeded: bool) {
        self.store.retirement.finalized(succeeded);
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
    }
}

#[cfg(test)]
mod tests;

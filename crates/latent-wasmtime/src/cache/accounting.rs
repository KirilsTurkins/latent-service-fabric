//! Optional unique-runtime accounting beside the existing resident counters.

mod ledger;
mod model;
mod residency;

use std::sync::{Arc, Mutex, MutexGuard};

pub(crate) use ledger::{PreparedRuntimeCharge, PreparedRuntimeCost, PreparedRuntimeLedger};
pub(super) use residency::PreparedResidency;
pub(crate) use residency::TrackedPreparedValue;

pub use model::{
    PreparedCacheAccountingSnapshot, PreparedRuntimePopulation, PreparedRuntimeSnapshot,
};

/// Independent observation capability which retains no cache, native runtime,
/// factory or worker. Absence means this backend has no unique-lifetime ledger;
/// it does not mean zero resource use.
#[derive(Clone, Debug, Default)]
pub struct PreparedRuntimeObserver {
    state: Option<Arc<Mutex<PreparedRuntimeSnapshot>>>,
}

impl PreparedRuntimeObserver {
    /// Reads unique-runtime costs when that accounting capability is available.
    /// The capability remains usable after the factory and cache are destroyed.
    #[must_use]
    pub fn snapshot(&self) -> Option<PreparedRuntimeSnapshot> {
        self.state.as_ref().map(|state| {
            *state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
        })
    }

    pub(super) fn lock(&self) -> Option<LedgerGuard<'_>> {
        self.state.as_ref().map(|owner| LedgerGuard {
            owner,
            totals: owner
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner),
        })
    }
}

pub(super) struct LedgerGuard<'a> {
    owner: &'a Arc<Mutex<PreparedRuntimeSnapshot>>,
    totals: MutexGuard<'a, PreparedRuntimeSnapshot>,
}

impl<T> super::PreparedCache<T> {
    pub(crate) fn accounting_snapshot(&self) -> PreparedCacheAccountingSnapshot {
        let state = self.lock();
        let ledger = self.runtime_observer.lock();
        PreparedCacheAccountingSnapshot {
            resident: state.snapshot(self.limits),
            runtimes: ledger.map(|ledger| *ledger.totals),
        }
    }

    pub(crate) fn prepared_runtime_observer(&self) -> PreparedRuntimeObserver {
        self.runtime_observer.clone()
    }

    pub(crate) fn new_tracked(
        limits: super::CacheLimits,
    ) -> Result<Self, latent_core::PlatformError> {
        let mut cache = Self::new(limits)?;
        cache.runtime_observer.state =
            Some(Arc::new(Mutex::new(PreparedRuntimeSnapshot::default())));
        Ok(cache)
    }

    pub(crate) fn runtime_ledger(&self) -> Option<PreparedRuntimeLedger> {
        self.runtime_observer
            .state
            .as_ref()
            .map(|state| PreparedRuntimeLedger {
                state: Arc::clone(state),
            })
    }
}

#[cfg(test)]
mod tests;

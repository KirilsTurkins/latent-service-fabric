//! Optional unique-runtime accounting beside the existing resident counters.

mod model;

use std::sync::{Arc, Mutex};

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
}

impl<T> super::PreparedCache<T> {
    pub(crate) fn accounting_snapshot(&self) -> PreparedCacheAccountingSnapshot {
        PreparedCacheAccountingSnapshot {
            resident: self.snapshot(),
            runtimes: self.runtime_observer.snapshot(),
        }
    }

    pub(crate) fn prepared_runtime_observer(&self) -> PreparedRuntimeObserver {
        self.runtime_observer.clone()
    }
}

#[cfg(test)]
mod tests;

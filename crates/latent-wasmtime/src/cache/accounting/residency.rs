use std::sync::atomic::Ordering;
use std::sync::{Arc, Weak};

use latent_core::PlatformError;

use super::ledger::{add, subtract, ChargeState, EVICTED, RESIDENT, UNPUBLISHED};
use super::{LedgerGuard, PreparedRuntimeCharge, PreparedRuntimeCost, PreparedRuntimeObserver};

/// This crate-private trait is needed only by the attachment method. The
/// concrete implementation must return the same runtime's own final field.
/// It is never called under a cache, ledger or compiler registry lock.
pub(crate) trait TrackedPreparedValue {
    fn runtime_charge(&self) -> &PreparedRuntimeCharge;
}

pub(in crate::cache) struct PreparedResidency<T> {
    runtime: Weak<T>,
    state: Arc<ChargeState>,
}

impl<T> PreparedResidency<T> {
    pub(in crate::cache) fn claim(
        runtime: &Arc<T>,
        charge: &PreparedRuntimeCharge,
        observer: &PreparedRuntimeObserver,
    ) -> Result<Self, PlatformError> {
        let Some(ledger) = observer.lock() else {
            return Err(super::super::capacity_error());
        };
        if !Arc::ptr_eq(ledger.owner, &charge.state.ledger)
            || charge.state.phase.load(Ordering::Relaxed) != UNPUBLISHED
            || charge.state.claimed.load(Ordering::Relaxed)
        {
            return Err(super::super::capacity_error());
        }
        charge.state.claimed.store(true, Ordering::Relaxed);
        Ok(Self {
            runtime: Arc::downgrade(runtime),
            state: Arc::clone(&charge.state),
        })
    }

    pub(in crate::cache) fn validate(
        &self,
        runtime: &Arc<T>,
        cost: PreparedRuntimeCost,
        ledger: &LedgerGuard<'_>,
    ) -> Result<(), PlatformError> {
        if !self.runtime.ptr_eq(&Arc::downgrade(runtime))
            || !Arc::ptr_eq(ledger.owner, &self.state.ledger)
            || self.state.cost != cost.population()?
            || self.state.phase.load(Ordering::Relaxed) != UNPUBLISHED
            || !self.state.claimed.load(Ordering::Relaxed)
        {
            return Err(super::super::capacity_error());
        }
        Ok(())
    }

    pub(in crate::cache) fn admit(&self, ledger: &mut LedgerGuard<'_>) {
        subtract(&mut ledger.totals.unpublished, self.state.cost);
        // This population remains a subset of the checked total live charge.
        ledger.totals.resident =
            add(ledger.totals.resident, self.state.cost).expect("subset of live runtime costs");
        self.state.phase.store(RESIDENT, Ordering::Relaxed);
    }

    pub(in crate::cache) fn evict(&self, ledger: &mut LedgerGuard<'_>) {
        debug_assert!(Arc::ptr_eq(ledger.owner, &self.state.ledger));
        if self.state.phase.load(Ordering::Relaxed) == RESIDENT {
            subtract(&mut ledger.totals.resident, self.state.cost);
            ledger.totals.evicted_live = add(ledger.totals.evicted_live, self.state.cost)
                .expect("subset of live runtime costs");
            self.state.phase.store(EVICTED, Ordering::Relaxed);
        }
    }
}

impl<T> Drop for PreparedResidency<T> {
    fn drop(&mut self) {
        let mut totals = self
            .state
            .ledger
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if self.state.phase.load(Ordering::Relaxed) == RESIDENT {
            subtract(&mut totals.resident, self.state.cost);
            totals.evicted_live =
                add(totals.evicted_live, self.state.cost).expect("subset of live runtime costs");
            self.state.phase.store(EVICTED, Ordering::Relaxed);
        }
        self.state.claimed.store(false, Ordering::Relaxed);
    }
}

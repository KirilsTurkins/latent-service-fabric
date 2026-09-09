use std::sync::atomic::{AtomicBool, AtomicU8, Ordering};
use std::sync::{Arc, Mutex};

use latent_core::PlatformError;

use super::{PreparedRuntimePopulation, PreparedRuntimeSnapshot};

pub(super) const UNPUBLISHED: u8 = 0;
pub(super) const RESIDENT: u8 = 1;
pub(super) const EVICTED: u8 = 2;
pub(super) const DEAD: u8 = 3;

#[derive(Clone, Copy)]
pub(crate) struct PreparedRuntimeCost {
    pub source_bytes: usize,
    pub metadata_bytes: usize,
    pub compiled_image_bytes: usize,
}

impl PreparedRuntimeCost {
    pub(super) fn population(self) -> Result<PreparedRuntimePopulation, PlatformError> {
        Ok(PreparedRuntimePopulation {
            runtimes: 1,
            source_bytes: u64::try_from(self.source_bytes)
                .map_err(|_| super::super::capacity_error())?,
            metadata_bytes: u64::try_from(self.metadata_bytes)
                .map_err(|_| super::super::capacity_error())?,
            compiled_image_bytes: u64::try_from(self.compiled_image_bytes)
                .map_err(|_| super::super::capacity_error())?,
        })
    }
}

/// Fixed counters only: no cache, runtime, source, engine or helper ownership.
#[derive(Clone)]
pub(crate) struct PreparedRuntimeLedger {
    pub(super) state: Arc<Mutex<PreparedRuntimeSnapshot>>,
}

impl PreparedRuntimeLedger {
    pub(crate) fn register(
        &self,
        cost: PreparedRuntimeCost,
    ) -> Result<PreparedRuntimeCharge, PlatformError> {
        let cost = cost.population()?;
        let charge = Arc::new(ChargeState {
            ledger: Arc::clone(&self.state),
            cost,
            phase: AtomicU8::new(DEAD),
            claimed: AtomicBool::new(false),
        });
        let mut totals = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let live = add(totals.live, cost).ok_or_else(super::super::capacity_error)?;
        let unpublished = add(totals.unpublished, cost).ok_or_else(super::super::capacity_error)?;
        totals.live = live;
        totals.unpublished = unpublished;
        charge.phase.store(UNPUBLISHED, Ordering::Relaxed);
        drop(totals);
        Ok(PreparedRuntimeCharge { state: charge })
    }
}

/// Unique guard declared after every native field in the prepared runtime.
/// Bookkeeping token references cannot delay or trigger this final refund.
pub(crate) struct PreparedRuntimeCharge {
    pub(super) state: Arc<ChargeState>,
}

pub(super) struct ChargeState {
    pub(super) ledger: Arc<Mutex<PreparedRuntimeSnapshot>>,
    pub(super) cost: PreparedRuntimePopulation,
    // Both atomics are private and accessed while holding their ledger mutex.
    pub(super) phase: AtomicU8,
    pub(super) claimed: AtomicBool,
}

impl Drop for PreparedRuntimeCharge {
    fn drop(&mut self) {
        let mut totals = self
            .state
            .ledger
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let population = match self.state.phase.load(Ordering::Relaxed) {
            UNPUBLISHED => &mut totals.unpublished,
            RESIDENT => &mut totals.resident,
            EVICTED => &mut totals.evicted_live,
            _ => unreachable!("a unique runtime charge retires once"),
        };
        subtract(population, self.state.cost);
        subtract(&mut totals.live, self.state.cost);
        self.state.phase.store(DEAD, Ordering::Relaxed);
    }
}

pub(super) fn add(
    left: PreparedRuntimePopulation,
    right: PreparedRuntimePopulation,
) -> Option<PreparedRuntimePopulation> {
    Some(PreparedRuntimePopulation {
        runtimes: left.runtimes.checked_add(right.runtimes)?,
        source_bytes: left.source_bytes.checked_add(right.source_bytes)?,
        metadata_bytes: left.metadata_bytes.checked_add(right.metadata_bytes)?,
        compiled_image_bytes: left
            .compiled_image_bytes
            .checked_add(right.compiled_image_bytes)?,
    })
}

pub(super) fn subtract(left: &mut PreparedRuntimePopulation, right: PreparedRuntimePopulation) {
    left.runtimes -= right.runtimes;
    left.source_bytes -= right.source_bytes;
    left.metadata_bytes -= right.metadata_bytes;
    left.compiled_image_bytes -= right.compiled_image_bytes;
}

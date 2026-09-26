use super::{CapabilitySession, RandomError};
use crate::broker::session::SessionCore;
use std::sync::{atomic::Ordering, Arc};

/// Pending work reserves aggregate capacity; started entropy work spends it.
pub(super) struct Reservation {
    core: Arc<SessionCore>,
    bytes: usize,
    committed: bool,
}
impl Reservation {
    pub(super) fn new(
        session: &CapabilitySession,
        bytes: usize,
        maximum: usize,
    ) -> Result<Self, RandomError> {
        session.core.check()?;
        session
            .core
            .random_bytes
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |used| {
                used.checked_add(bytes).filter(|total| *total <= maximum)
            })
            .map_err(|_| RandomError::BudgetExhausted)?;
        Ok(Self {
            core: session.core.clone(),
            bytes,
            committed: false,
        })
    }
    pub(super) fn commit(&mut self) {
        self.committed = true;
    }
}
impl Drop for Reservation {
    fn drop(&mut self) {
        if !self.committed {
            self.core
                .random_bytes
                .fetch_sub(self.bytes, Ordering::AcqRel);
        }
    }
}

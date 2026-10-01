//! One shared, caller-driven maintenance owner. Execution borrows the original
//! physical store worker; this module creates no thread, timer or authority.

mod clock;
mod expired;
mod step;

pub(super) use clock::PROGRESS_KEY;
pub use clock::{MaintenanceClock, MaintenanceProgress};
pub(super) use expired::ExpiredResult;

use super::AtomicError;
use std::sync::atomic::{AtomicBool, Ordering};

/// Construct once for the node. Submit steps through the existing authorized
/// recovery store owner; neither this flag nor its clock supplies permission.
#[derive(Default)]
pub struct ResultMaintenanceOwner {
    active: AtomicBool,
}
impl ResultMaintenanceOwner {
    /// Includes page, result codec, CAS copies and bounded dependency metadata.
    /// Dropping a public waiter must not release the physical reservation.
    pub const RETAINED_BYTES: u64 = 8 * 1024 * 1024;

    fn enter(&self) -> Result<StepGuard<'_>, AtomicError> {
        self.active
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| AtomicError::InProgress)?;
        Ok(StepGuard(&self.active))
    }
}
struct StepGuard<'a>(&'a AtomicBool);
impl Drop for StepGuard<'_> {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Release);
    }
}

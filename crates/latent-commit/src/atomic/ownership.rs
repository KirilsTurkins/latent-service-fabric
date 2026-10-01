//! Physical executor/commit/cleanup guards. A deadline or dropped caller never
//! retires one. Unretired guards quarantine the attempt and cannot mint abort proof.

use super::{AdmittedCommand, AtomicError, CommandRecord};
use std::sync::{
    atomic::{AtomicBool, AtomicU8, AtomicUsize, Ordering},
    Arc,
};
pub(super) const OPEN: u8 = 0;
pub(super) const ACCEPTED: u8 = 1;
pub(super) const TERMINAL: u8 = 2;
pub(super) const UNKNOWN: u8 = 3;
pub(super) struct AttemptState {
    pub record: CommandRecord,
    pub expected: Vec<u8>,
    pub owners: AtomicUsize,
    pub phase: AtomicU8,
    pub quarantined: AtomicBool,
}
impl AttemptState {
    pub fn new(record: CommandRecord, expected: Vec<u8>) -> Arc<Self> {
        Arc::new(Self {
            record,
            expected,
            owners: AtomicUsize::new(1),
            phase: AtomicU8::new(OPEN),
            quarantined: AtomicBool::new(false),
        })
    }
}
pub struct AttemptRetirement {
    pub(super) state: Arc<AttemptState>,
}
pub struct RetiredAttempt {
    pub(super) record: CommandRecord,
    pub(super) expected: Vec<u8>,
}
pub struct PhysicalAttemptWork {
    state: Arc<AttemptState>,
    retired: bool,
}
impl AdmittedCommand {
    #[must_use]
    pub fn retirement(&self) -> AttemptRetirement {
        AttemptRetirement {
            state: Arc::clone(&self.physical),
        }
    }
    /// Move this affine guard into the actual executor/cleanup/store work item.
    /// Taking it or observing it is not proof of resource reservation elsewhere.
    pub fn physical_work(&self) -> Result<PhysicalAttemptWork, AtomicError> {
        self.physical
            .owners
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |owners| {
                if (1..8).contains(&owners) {
                    Some(owners + 1)
                } else {
                    None
                }
            })
            .map_err(|_| AtomicError::Limit)?;
        Ok(PhysicalAttemptWork {
            state: Arc::clone(&self.physical),
            retired: false,
        })
    }
}
impl AttemptRetirement {
    pub fn proven_noncommit(&self) -> Result<RetiredAttempt, AtomicError> {
        if self.state.owners.load(Ordering::Acquire) != 0
            || self.state.quarantined.load(Ordering::Acquire)
            || self.state.phase.load(Ordering::Acquire) != OPEN
        {
            return Err(AtomicError::RecoveryRequired);
        }
        Ok(RetiredAttempt {
            record: self.state.record.clone(),
            expected: self.state.expected.clone(),
        })
    }
}
impl PhysicalAttemptWork {
    /// Invoke only after the physical executor, IO or cleanup operation has
    /// completed. A cancelled waiter cannot call it on the worker's guard.
    pub fn retire(mut self) {
        self.retired = true;
        self.state.owners.fetch_sub(1, Ordering::AcqRel);
    }
}
impl Drop for PhysicalAttemptWork {
    fn drop(&mut self) {
        if !self.retired {
            self.state.quarantined.store(true, Ordering::Release);
        }
    }
}
impl Drop for AdmittedCommand {
    fn drop(&mut self) {
        self.physical.owners.fetch_sub(1, Ordering::AcqRel);
    }
}

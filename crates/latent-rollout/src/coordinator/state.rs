use crate::{
    busy, capacity, closed, lease::PageBudget, CoordinatorLimits, CoordinatorSnapshot, Result,
};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};

pub(crate) struct Shared {
    pub limits: CoordinatorLimits,
    pub pages: Arc<PageBudget>,
    pub closed: AtomicBool,
    pub failed: AtomicBool,
    pub started: AtomicBool,
    pub live: AtomicBool,
    pub completed: AtomicBool,
    pub shutdown: tokio::sync::Notify,
    pub(super) stats: Mutex<Stats>,
}
#[derive(Default)]
pub(super) struct Stats {
    queued: usize,
    active: usize,
    bytes: usize,
    accepted: u64,
    completed: u64,
}
pub(crate) struct RequestCharge {
    shared: Arc<Shared>,
    bytes: usize,
    active: bool,
}
impl RequestCharge {
    pub fn activate(&mut self) {
        let mut stats = self
            .shared
            .stats
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        stats.queued -= 1;
        stats.active += 1;
        self.active = true;
    }
}
impl Drop for RequestCharge {
    fn drop(&mut self) {
        let mut stats = self
            .shared
            .stats
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if self.active {
            stats.active -= 1;
        } else {
            stats.queued -= 1;
        }
        stats.bytes -= self.bytes;
        stats.completed = stats.completed.saturating_add(1);
    }
}
impl Shared {
    pub(super) fn reserve(self: &Arc<Self>, bytes: usize) -> Result<RequestCharge> {
        let mut stats = self.stats.try_lock().map_err(|_| busy())?;
        if self.closed.load(Ordering::Acquire) {
            return Err(closed());
        }
        if bytes > self.limits.maximum_request_bytes
            || stats.queued >= self.limits.maximum_queued_commands
            || bytes > self.limits.maximum_queued_bytes - stats.bytes
        {
            return Err(capacity("rollout-command-capacity"));
        }
        stats.queued += 1;
        stats.bytes += bytes;
        stats.accepted = stats.accepted.saturating_add(1);
        Ok(RequestCharge {
            shared: Arc::clone(self),
            bytes,
            active: false,
        })
    }
    pub fn snapshot(&self) -> CoordinatorSnapshot {
        let stats = self
            .stats
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let (owners, bytes) = self.pages.snapshot();
        CoordinatorSnapshot {
            queued_commands: stats.queued,
            active_commands: stats.active,
            retained_request_bytes: stats.bytes,
            response_owners: owners,
            response_bytes: bytes,
            accepted_commands: stats.accepted,
            completed_commands: stats.completed,
            worker_live: self.live.load(Ordering::Acquire),
            worker_started: self.started.load(Ordering::Acquire),
            worker_completed: self.completed.load(Ordering::Acquire),
            closed: self.closed.load(Ordering::Acquire),
            failed: self.failed.load(Ordering::Acquire),
        }
    }
}

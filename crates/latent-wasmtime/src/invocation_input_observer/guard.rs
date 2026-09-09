use std::sync::Arc;

use super::{Inner, InvocationInputDropReason, InvocationInputPhase};

/// Values-only stage access; this never owns an activation resource.
#[derive(Clone)]
pub(crate) struct InputTrace {
    pub(super) inner: Arc<Inner>,
    pub(super) token: u8,
}

impl InputTrace {
    pub(crate) fn stage(&self, phase: InvocationInputPhase) {
        self.inner
            .lock()
            .stage(self.token, phase, self.inner.origin);
    }

    pub(crate) fn raw_owner(&self, length: usize, capacity: usize) -> Option<RawGuard> {
        let Some((length, capacity)) = u64::try_from(length).ok().zip(u64::try_from(capacity).ok())
        else {
            self.inner.lock().overflowed = true;
            return None;
        };
        if !self
            .inner
            .lock()
            .raw_created(self.token, length, capacity, self.inner.origin)
        {
            return None;
        }
        Some(RawGuard {
            trace: self.clone(),
            reason: InvocationInputDropReason::OwnerScopeExit,
        })
    }
}

pub(crate) struct RawGuard {
    trace: InputTrace,
    reason: InvocationInputDropReason,
}

impl RawGuard {
    pub(crate) fn set_reason(&mut self, reason: InvocationInputDropReason) {
        self.reason = reason;
    }
}

impl Drop for RawGuard {
    fn drop(&mut self) {
        self.trace
            .inner
            .lock()
            .raw_dropped(self.trace.token, self.reason, self.trace.inner.origin);
    }
}

/// Its containing future must be destroyed before this guard, including unwind.
pub(crate) struct InvocationObservation {
    trace: InputTrace,
    completed: bool,
}

impl InvocationObservation {
    pub(super) fn new(trace: InputTrace) -> Self {
        Self {
            trace,
            completed: false,
        }
    }

    pub(crate) fn trace(&self) -> InputTrace {
        self.trace.clone()
    }

    pub(crate) fn completed(&mut self) {
        self.completed = true;
    }
}

impl Drop for InvocationObservation {
    fn drop(&mut self) {
        self.trace.inner.lock().retire(
            self.trace.token,
            self.completed && !std::thread::panicking(),
            self.trace.inner.origin,
        );
    }
}

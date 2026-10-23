//! Invocation-local timer readiness. No background worker or callback is
//! created. A maintained language scheduler consumes each readiness result.
use super::shared::Shared;
use super::{error, ActivationRuntime, OwnerKind, RuntimeOwner, RuntimeToken};
use crate::{PlatformError, PlatformErrorCode};
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

#[derive(Debug, Clone)]
pub struct RuntimeTimer {
    inner: Shared<Inner>,
}
#[derive(Debug)]
struct Inner {
    runtime: ActivationRuntime,
    schedule: Mutex<Schedule>,
    owner: RuntimeOwner,
}
#[derive(Debug)]
struct Schedule {
    next: Option<Instant>,
    period_nanos: Option<u64>,
    waiting: bool,
    closed: bool,
}

/// An affine, non-overlapping next-readiness registration. Dropping a waiter
/// clears only its registration; the physical timer still owns its reservation.
#[derive(Debug)]
pub struct TimerWait {
    inner: Shared<Inner>,
    requested: Instant,
    _owner: RuntimeOwner,
}
impl RuntimeTimer {
    pub fn new(
        runtime: &ActivationRuntime,
        first: Instant,
        period: Option<Duration>,
        continuation: Option<RuntimeToken>,
    ) -> Result<Self, PlatformError> {
        let period_nanos = period
            .map(|period| u64::try_from(period.as_nanos()))
            .transpose()
            .map_err(|_| error(PlatformErrorCode::InvalidArgument, "runtime-timer-period"))?;
        if period_nanos == Some(0) {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "runtime-timer-period",
            ));
        }
        let allocation = Shared::<Inner>::reserve(&runtime.inner.budget)?;
        let owner = runtime.register(OwnerKind::Timer, continuation)?;
        let inner = allocation.allocate(Inner {
            runtime: runtime.clone(),
            schedule: Mutex::new(Schedule {
                next: Some(first),
                period_nanos,
                waiting: false,
                closed: false,
            }),
            owner,
        });
        Ok(Self { inner })
    }
    #[must_use]
    pub fn token(&self) -> RuntimeToken {
        self.inner.owner.token()
    }
    pub fn begin_wait(&self) -> Result<TimerWait, PlatformError> {
        self.inner.runtime.check_live()?;
        let mut schedule = self
            .inner
            .schedule
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let requested = schedule
            .next
            .filter(|_| !schedule.closed)
            .ok_or_else(|| error(PlatformErrorCode::InvalidArgument, "runtime-timer-closed"))?;
        if schedule.waiting {
            return Err(error(
                PlatformErrorCode::ResourceExhausted,
                "runtime-timer-wait-inflight",
            ));
        }
        let owner = self
            .inner
            .runtime
            .register(OwnerKind::Wait, Some(self.token()))?;
        schedule.waiting = true;
        Ok(TimerWait {
            inner: self.inner.clone(),
            requested,
            _owner: owner,
        })
    }
    pub fn close(&self) {
        let mut schedule = self
            .inner
            .schedule
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        schedule.closed = true;
        schedule.next = None;
    }
}
impl TimerWait {
    #[must_use]
    pub const fn requested(&self) -> Instant {
        self.requested
    }
    #[must_use]
    pub fn is_closed(&self) -> bool {
        self.inner
            .schedule
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .closed
    }
    /// Fixed-rate recurrence emits at most one readiness result per wait and
    /// coalesces all missed ticks in O(1). There is no unbounded catch-up queue.
    pub fn complete(&mut self, now: Instant) -> Result<u64, PlatformError> {
        self.inner.runtime.check_live()?;
        let mut schedule = self
            .inner
            .schedule
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if schedule.closed || now < self.requested || schedule.next != Some(self.requested) {
            return Err(error(PlatformErrorCode::Cancelled, "runtime-timer-closed"));
        }
        let skipped = if let Some(period) = schedule.period_nanos {
            let elapsed = now.duration_since(self.requested).as_nanos();
            let skipped = u64::try_from(elapsed / u128::from(period)).unwrap_or(u64::MAX);
            let remaining = period
                - u64::try_from(elapsed % u128::from(period)).expect("remainder bounded by period");
            schedule.next = Some(
                now.checked_add(Duration::from_nanos(remaining))
                    .ok_or_else(|| {
                        error(PlatformErrorCode::InvalidArgument, "runtime-timer-range")
                    })?,
            );
            skipped
        } else {
            schedule.next = None;
            0
        };
        Ok(skipped)
    }
}
impl Drop for TimerWait {
    fn drop(&mut self) {
        self.inner
            .schedule
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .waiting = false;
    }
}

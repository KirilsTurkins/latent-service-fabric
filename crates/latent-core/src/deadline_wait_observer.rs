//! Opt-in accounting for the manager's owned deadline sleep futures.
//!
//! These counters describe this one helper, not operating-system timers,
//! transport deadlines or backend interruption clocks. Ordinary clocks expose
//! no observer and incur no observer allocation or lock on an invocation.

use std::sync::{Arc, Mutex, MutexGuard};

/// A coherent fixed-size observation. Overflow makes exact coverage unavailable.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DeadlineWaitSnapshot {
    pub supported: bool,
    pub armed: u64,
    pub completed: u64,
    pub dropped: u64,
    pub live: u64,
    pub maximum_live: u64,
    /// Clock checks after a completed sleep, excluding the initial expiry check.
    pub rechecks: u64,
    pub overflowed: bool,
}

/// Explicitly retained by an observing clock; clones share one bounded counter set.
#[derive(Debug, Clone)]
pub struct DeadlineWaitObserver {
    inner: Arc<Mutex<DeadlineWaitSnapshot>>,
}

impl Default for DeadlineWaitObserver {
    fn default() -> Self {
        Self::new()
    }
}

impl DeadlineWaitObserver {
    #[must_use]
    pub fn new() -> Self {
        Self {
            inner: Arc::new(Mutex::new(DeadlineWaitSnapshot {
                supported: true,
                armed: 0,
                completed: 0,
                dropped: 0,
                live: 0,
                maximum_live: 0,
                rechecks: 0,
                overflowed: false,
            })),
        }
    }

    #[must_use]
    pub fn snapshot(&self) -> DeadlineWaitSnapshot {
        *lock(&self.inner)
    }

    /// Arm immediately before polling one owned sleep. Dropping its guard
    /// without completion accounts cancellation, stage return and unwinding.
    #[must_use]
    pub fn arm(&self) -> DeadlineWaitGuard {
        let active = {
            let mut state = lock(&self.inner);
            state.armed = increment(state.armed, &mut state.overflowed);
            if let Some(live) = state.live.checked_add(1) {
                state.live = live;
                state.maximum_live = state.maximum_live.max(live);
                true
            } else {
                state.overflowed = true;
                false
            }
        };
        DeadlineWaitGuard {
            inner: Arc::clone(&self.inner),
            active,
        }
    }

    pub fn recheck(&self) {
        let mut state = lock(&self.inner);
        state.rechecks = increment(state.rechecks, &mut state.overflowed);
    }
}

/// Affine counter ownership; it retains no sleep, clock or activation owner.
#[derive(Debug)]
pub struct DeadlineWaitGuard {
    inner: Arc<Mutex<DeadlineWaitSnapshot>>,
    active: bool,
}

impl DeadlineWaitGuard {
    pub fn complete(mut self) {
        self.finish(true);
    }

    fn finish(&mut self, completed: bool) {
        if !self.active {
            return;
        }
        self.active = false;
        let mut state = lock(&self.inner);
        state.live -= 1;
        if completed {
            state.completed = increment(state.completed, &mut state.overflowed);
        } else {
            state.dropped = increment(state.dropped, &mut state.overflowed);
        }
    }
}

impl Drop for DeadlineWaitGuard {
    fn drop(&mut self) {
        self.finish(false);
    }
}

fn increment(value: u64, overflowed: &mut bool) -> u64 {
    value.checked_add(1).unwrap_or_else(|| {
        *overflowed = true;
        u64::MAX
    })
}

fn lock(inner: &Mutex<DeadlineWaitSnapshot>) -> MutexGuard<'_, DeadlineWaitSnapshot> {
    inner
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn affine_waits_account_completion_drop_and_rechecks() {
        let observer = DeadlineWaitObserver::new();
        let first = observer.arm();
        let second = observer.arm();
        assert_eq!(observer.snapshot().live, 2);
        first.complete();
        observer.recheck();
        drop(second);
        let snapshot = observer.snapshot();
        assert!(snapshot.supported);
        assert_eq!(
            (snapshot.armed, snapshot.completed, snapshot.dropped),
            (2, 1, 1)
        );
        assert_eq!(
            (snapshot.live, snapshot.maximum_live, snapshot.rechecks),
            (0, 2, 1)
        );
        assert!(!snapshot.overflowed);
    }

    #[test]
    fn unwinding_releases_the_guard_without_retaining_its_creator() {
        let observer = DeadlineWaitObserver::new();
        let observed = observer.clone();
        let result = std::panic::catch_unwind(move || {
            let _wait = observer.arm();
            panic!("injected deadline owner failure");
        });
        assert!(result.is_err());
        assert_eq!(observed.snapshot().live, 0);
        assert_eq!(observed.snapshot().dropped, 1);
        assert_eq!(Arc::strong_count(&observed.inner), 1);
    }

    #[test]
    fn counter_exhaustion_is_explicit_and_never_wraps() {
        let observer = DeadlineWaitObserver::new();
        {
            let mut state = lock(&observer.inner);
            state.armed = u64::MAX;
            state.rechecks = u64::MAX;
        }
        observer.arm().complete();
        observer.recheck();
        let snapshot = observer.snapshot();
        assert!(snapshot.overflowed);
        assert_eq!(snapshot.armed, u64::MAX);
        assert_eq!(snapshot.rechecks, u64::MAX);
        assert_eq!(snapshot.live, 0);
        assert_eq!(snapshot.completed, 1);
    }
}

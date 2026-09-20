//! Injected monotonic time, independent wall observations, and bounded manual timers.
//!
//! This does not change Tokio time, OS time, or child-process clocks. Advancing
//! wakes only this clock's `sleep_until` futures. Production consumers continue
//! to use their existing `ActivationClock` seam and their own waiting mechanism.

use std::collections::BTreeMap;
use std::future::Future;
use std::pin::Pin;
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll, Waker};
use std::time::{Duration, Instant};

use latent_core::{ActivationClock, ClockSample};

#[derive(Debug)]
struct State {
    now: Instant,
    wall: u64,
    next: u64,
    capacity: usize,
    waits: BTreeMap<u64, (Instant, Waker)>,
}

/// A clone shares one coherent time domain. Monotonic time can only advance.
#[derive(Debug, Clone)]
pub struct TestClock(Arc<Mutex<State>>);

impl TestClock {
    #[must_use]
    pub fn new(wall_unix_millis: u64, monotonic: Instant, maximum_waiters: usize) -> Self {
        assert!(maximum_waiters > 0, "manual timer capacity must be nonzero");
        Self(Arc::new(Mutex::new(State {
            now: monotonic,
            wall: wall_unix_millis,
            next: 0,
            capacity: maximum_waiters,
            waits: BTreeMap::new(),
        })))
    }

    /// Wall-clock changes never move an existing monotonic deadline or wake a timer.
    pub fn set_wall_unix_millis(&self, wall: u64) {
        self.0.lock().unwrap().wall = wall;
    }

    /// Advance monotonically and wake due registrations outside the clock lock.
    pub fn advance(&self, amount: Duration) {
        let wakes = {
            let mut state = self.0.lock().unwrap();
            state.now = state.now.checked_add(amount).expect("test clock overflow");
            let now = state.now;
            let due: Vec<_> = state
                .waits
                .iter()
                .filter_map(|(id, (deadline, _))| (*deadline <= now).then_some(*id))
                .collect();
            due.into_iter()
                .map(|id| state.waits.remove(&id).unwrap().1)
                .collect::<Vec<_>>()
        };
        for waker in wakes {
            waker.wake();
        }
    }

    #[must_use]
    pub fn pending_waiters(&self) -> usize {
        self.0.lock().unwrap().waits.len()
    }

    /// Registration happens on poll, not construction. Drop unregisters a pending timer.
    #[must_use]
    pub fn sleep_until(&self, deadline: Instant) -> ManualSleep {
        ManualSleep {
            clock: self.clone(),
            deadline,
            registration: None,
        }
    }
}

impl ActivationClock for TestClock {
    fn sample(&self) -> ClockSample {
        let state = self.0.lock().unwrap();
        ClockSample::new(state.wall, state.now)
    }

    fn monotonic_now(&self) -> Instant {
        self.0.lock().unwrap().now
    }
}

#[derive(Debug)]
pub struct ManualSleep {
    clock: TestClock,
    deadline: Instant,
    registration: Option<u64>,
}

impl Future for ManualSleep {
    type Output = ();

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<()> {
        let this = self.get_mut();
        let mut state = this.clock.0.lock().unwrap();
        if state.now >= this.deadline {
            if let Some(id) = this.registration.take() {
                state.waits.remove(&id);
            }
            return Poll::Ready(());
        }
        if let Some(id) = this.registration {
            state
                .waits
                .get_mut(&id)
                .expect("live manual timer")
                .1
                .clone_from(cx.waker());
        } else {
            // Fail without poisoning the clock, so other timer owners can still retire.
            if state.waits.len() == state.capacity {
                drop(state);
                panic!("manual timer capacity exhausted");
            }
            let id = state.next;
            state.next = state
                .next
                .checked_add(1)
                .expect("manual timer identity exhausted");
            state.waits.insert(id, (this.deadline, cx.waker().clone()));
            this.registration = Some(id);
        }
        Poll::Pending
    }
}

impl Drop for ManualSleep {
    fn drop(&mut self) {
        if let Some(id) = self.registration {
            self.clock.0.lock().unwrap().waits.remove(&id);
        }
    }
}

#[cfg(test)]
mod tests;

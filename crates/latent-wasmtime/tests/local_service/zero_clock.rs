//! Bounded diagnostic clock for one signed Go timer edge.
//! The mock wait registry is test infrastructure, not physical timer evidence.

use latent_core::{test_support::TestClock, ActivationClock, ClockSample, SystemActivationClock};
use std::{
    future::Future,
    io::Write,
    sync::atomic::{AtomicBool, AtomicU64, Ordering},
    time::{Duration, Instant},
};
use tokio::sync::Notify;

/// One shared monotonic domain for the real node, broker and Wasmtime host.
/// The registry is finite and exists only in this isolated test fixture.
pub struct ZeroClock {
    clock: TestClock,
    origin: Instant,
    seen: AtomicBool,
    pending: AtomicBool,
    target_live: AtomicBool,
    notify: Notify,
}

impl ZeroClock {
    pub fn new() -> Self {
        let origin = Instant::now();
        Self {
            clock: TestClock::new(SystemActivationClock.sample().unix_millis(), origin, 8),
            origin,
            seen: AtomicBool::new(false),
            pending: AtomicBool::new(false),
            target_live: AtomicBool::new(false),
            notify: Notify::new(),
        }
    }

    pub fn origin(&self) -> Instant {
        self.origin
    }
    pub fn pending_waiters(&self) -> usize {
        self.clock.pending_waiters()
    }
    pub fn target_live(&self) -> bool {
        self.target_live.load(Ordering::Acquire)
    }
    pub fn advance(&self, by: Duration) {
        self.clock.advance(by);
    }

    pub async fn target_pending(&self) {
        loop {
            let notified = self.notify.notified();
            if self.pending.load(Ordering::Acquire) {
                return;
            }
            notified.await;
        }
    }

    pub async fn wait(&self, deadline: Instant, active: &AtomicU64, entered: &Notify) {
        struct Active<'a>(&'a AtomicU64);
        impl Drop for Active<'_> {
            fn drop(&mut self) {
                self.0.fetch_sub(1, Ordering::AcqRel);
            }
        }
        struct Target<'a> {
            clock: &'a ZeroClock,
            armed: bool,
        }
        impl Drop for Target<'_> {
            fn drop(&mut self) {
                if self.armed {
                    self.clock.target_live.store(false, Ordering::Release);
                }
            }
        }
        active.fetch_add(1, Ordering::AcqRel);
        let _active = Active(active);
        let mut target = Target {
            clock: self,
            armed: false,
        };
        entered.notify_one();
        let mut sleep = std::pin::pin!(self.clock.sleep_until(deadline));
        let mut reported = false;
        std::future::poll_fn(|cx| {
            let result = sleep.as_mut().poll(cx);
            if result.is_pending() && !reported && deadline == self.origin + Duration::from_nanos(5)
            {
                reported = true;
                assert!(
                    !self.seen.swap(true, Ordering::AcqRel),
                    "duplicate five-nanosecond wait"
                );
                target.armed = true;
                self.target_live.store(true, Ordering::Release);
                writeln!(
                    std::io::stderr().lock(),
                    "LSF-GO-ZERO-CLOCK-V1|wait-pending|0|5"
                )
                .expect("write zero-clock witness");
                self.pending.store(true, Ordering::Release);
                self.notify.notify_one();
            }
            result
        })
        .await;
    }
}

impl ActivationClock for ZeroClock {
    fn sample(&self) -> ClockSample {
        self.clock.sample()
    }
    fn monotonic_now(&self) -> Instant {
        self.clock.monotonic_now()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::task::Poll;

    async fn require_pending<F: Future + Unpin>(future: &mut F) {
        std::future::poll_fn(|cx| match std::pin::Pin::new(&mut *future).poll(cx) {
            Poll::Pending => Poll::Ready(()),
            Poll::Ready(_) => panic!("wait was not pending"),
        })
        .await;
    }

    #[tokio::test]
    async fn five_nanosecond_wait_only_fires_after_shared_clock_reaches_deadline() {
        let clock = ZeroClock::new();
        let active = AtomicU64::new(0);
        let entered = Notify::new();
        let mut wait =
            Box::pin(clock.wait(clock.origin() + Duration::from_nanos(5), &active, &entered));
        require_pending(&mut wait).await;
        clock.target_pending().await;
        assert_eq!(active.load(Ordering::Acquire), 1);
        assert_eq!(clock.pending_waiters(), 1);
        assert!(clock.target_live());
        clock.advance(Duration::from_nanos(4));
        require_pending(&mut wait).await;
        clock.advance(Duration::from_nanos(1));
        wait.await;
        assert_eq!(
            clock.monotonic_now(),
            clock.origin() + Duration::from_nanos(5)
        );
        assert_eq!(active.load(Ordering::Acquire), 0);
        assert_eq!(clock.pending_waiters(), 0);
        assert!(!clock.target_live());
    }

    #[tokio::test]
    async fn dropping_pending_wait_removes_registration_and_active_owner() {
        let clock = ZeroClock::new();
        let active = AtomicU64::new(0);
        let entered = Notify::new();
        let mut wait =
            Box::pin(clock.wait(clock.origin() + Duration::from_nanos(5), &active, &entered));
        require_pending(&mut wait).await;
        assert_eq!(clock.pending_waiters(), 1);
        drop(wait);
        assert_eq!(clock.pending_waiters(), 0);
        assert_eq!(active.load(Ordering::Acquire), 0);
        assert!(!clock.target_live());
    }
}

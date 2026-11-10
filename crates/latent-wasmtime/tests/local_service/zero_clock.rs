//! Bounded diagnostic clock for one signed Go timer edge.
//! The mock wait registry is test infrastructure, not physical timer evidence.

use latent_core::{test_support::TestClock, ActivationClock, ClockSample, SystemActivationClock};
use std::{
    future::Future,
    io::Write,
    sync::atomic::{AtomicBool, AtomicU64, AtomicU8, Ordering},
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
    ticker_mode: bool,
    ticker_stage: AtomicU8,
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
            ticker_mode: false,
            ticker_stage: AtomicU8::new(0),
            notify: Notify::new(),
        }
    }

    /// Reuse the same bounded clock and wait registry for one ticker scenario.
    pub fn for_ticker() -> Self {
        let mut clock = Self::new();
        clock.ticker_mode = true;
        clock
    }

    pub async fn ticker_pending(&self, stage: u8) {
        assert!(self.ticker_mode && (1..=3).contains(&stage));
        loop {
            let notified = self.notify.notified();
            let observed = self.ticker_stage.load(Ordering::Acquire);
            assert!(observed <= stage, "ticker wait stage advanced unexpectedly");
            if observed == stage {
                return;
            }
            notified.await;
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
            if result.is_pending() && !reported && self.ticker_mode {
                if let Some(delta) = deadline.checked_duration_since(self.origin) {
                    if delta <= Duration::from_nanos(100) {
                        let stage = usize::from(self.ticker_stage.load(Ordering::Acquire));
                        let deadlines = [5, 10, 30];
                        let before = [0, 5, 29];
                        assert!(stage < deadlines.len(), "extra short ticker wait");
                        assert_eq!(
                            delta,
                            Duration::from_nanos(deadlines[stage]),
                            "wrong ticker deadline"
                        );
                        assert_eq!(
                            self.clock.monotonic_now(),
                            self.origin + Duration::from_nanos(before[stage]),
                            "ticker wait entered at wrong clock edge"
                        );
                        assert!(
                            !self.target_live.swap(true, Ordering::AcqRel),
                            "overlapping ticker waits"
                        );
                        reported = true;
                        target.armed = true;
                        writeln!(
                            std::io::stderr().lock(),
                            "LSF-GO-TICKER-CLOCK-V1|wait-pending|{}|{}",
                            before[stage],
                            deadlines[stage]
                        )
                        .expect("write ticker wait witness");
                        self.ticker_stage
                            .store((stage + 1) as u8, Ordering::Release);
                        self.notify.notify_one();
                    }
                }
            }
            if result.is_pending()
                && !reported
                && !self.ticker_mode
                && deadline == self.origin + Duration::from_nanos(5)
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
    async fn ticker_waits_remain_pending_at_each_controlled_clock_edge() {
        let clock = ZeroClock::for_ticker();
        let active = AtomicU64::new(0);
        let entered = Notify::new();
        for (stage, deadline, advance) in [(1, 5, 5), (2, 10, 24), (3, 30, 1)] {
            let mut wait = Box::pin(clock.wait(
                clock.origin() + Duration::from_nanos(deadline),
                &active,
                &entered,
            ));
            require_pending(&mut wait).await;
            clock.ticker_pending(stage).await;
            assert!(clock.target_live());
            assert_eq!(active.load(Ordering::Acquire), 1);
            assert_eq!(clock.pending_waiters(), 1);
            clock.advance(Duration::from_nanos(advance));
            wait.await;
            assert!(!clock.target_live());
            assert_eq!(active.load(Ordering::Acquire), 0);
            assert_eq!(clock.pending_waiters(), 0);
        }
    }

    #[tokio::test]
    #[should_panic(expected = "wrong ticker deadline")]
    async fn ticker_rejects_a_foreign_short_wait() {
        let clock = ZeroClock::for_ticker();
        let active = AtomicU64::new(0);
        let entered = Notify::new();
        let mut wrong =
            Box::pin(clock.wait(clock.origin() + Duration::from_nanos(6), &active, &entered));
        require_pending(&mut wrong).await;
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

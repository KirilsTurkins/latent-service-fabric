use super::*;
use crate::coordination::{with_watchdog, PollProbe, WATCHDOG};
use crate::DeterministicIds;

#[test]
fn wall_jumps_cannot_restart_a_monotonic_deadline_and_advance_wakes_exactly() {
    let clock = TestClock::new(10_000, Instant::now(), 2);
    let deadline = clock.monotonic_now() + Duration::from_millis(50);
    let mut sleep = Box::pin(clock.sleep_until(deadline));
    let probe = PollProbe::default();
    probe.pending(sleep.as_mut());
    assert_eq!(clock.pending_waiters(), 1);
    for wall in [0, u64::MAX, 10_000] {
        clock.set_wall_unix_millis(wall);
        probe.pending(sleep.as_mut());
        assert_eq!(probe.wakes(), 0);
    }
    clock.advance(Duration::from_millis(49));
    probe.pending(sleep.as_mut());
    assert_eq!(probe.wakes(), 0);
    clock.advance(Duration::from_millis(1));
    assert_eq!(probe.wakes(), 1);
    probe.ready(sleep.as_mut());
    assert_eq!(clock.monotonic_now(), deadline);
    assert_eq!(clock.pending_waiters(), 0);
    assert!(!clock.uses_system_monotonic());
}

#[test]
fn cancelled_timer_registration_does_not_wake_or_consume_reused_capacity() {
    let clock = TestClock::new(0, Instant::now(), 1);
    let deadline = clock.monotonic_now() + Duration::from_secs(1);
    let stale = PollProbe::default();
    let mut first = Box::pin(clock.sleep_until(deadline));
    stale.pending(first.as_mut());
    drop(first);
    assert_eq!(clock.pending_waiters(), 0);
    let current = PollProbe::default();
    let mut second = Box::pin(clock.sleep_until(deadline));
    current.pending(second.as_mut());
    clock.advance(Duration::from_secs(1));
    assert_eq!(stale.wakes(), 0);
    assert_eq!(current.wakes(), 1);
    current.ready(second.as_mut());
}

#[test]
fn missing_timer_poll_and_capacity_exhaustion_are_not_readiness() {
    let clock = TestClock::new(0, Instant::now(), 1);
    let deadline = clock.monotonic_now() + Duration::from_secs(1);
    let mut first = Box::pin(clock.sleep_until(deadline));
    assert_eq!(clock.pending_waiters(), 0);
    PollProbe::default().pending(first.as_mut());
    let extra = std::panic::catch_unwind(|| {
        let mut extra = Box::pin(clock.sleep_until(deadline));
        PollProbe::default().pending(extra.as_mut());
    });
    assert!(extra.is_err());
    assert_eq!(clock.pending_waiters(), 1);
    drop(first);
    assert_eq!(clock.pending_waiters(), 0);
}

async fn fixed_script() {
    with_watchdog(WATCHDOG, async {
        let clock = TestClock::new(433, Instant::now(), 1);
        let mut ids = DeterministicIds::new("seed-433");
        for index in 0..16 {
            assert_eq!(ids.next_id(), format!("seed-433-{index:016x}"));
            let deadline = clock.monotonic_now() + Duration::from_nanos(1);
            let mut sleep = Box::pin(clock.sleep_until(deadline));
            PollProbe::default().pending(sleep.as_mut());
            let task = tokio::spawn(sleep);
            clock.advance(Duration::from_nanos(1));
            task.await.unwrap();
            assert_eq!(clock.monotonic_now(), deadline);
            assert_eq!(clock.pending_waiters(), 0);
        }
    })
    .await;
}

#[tokio::test(flavor = "current_thread")]
async fn fixed_seed_current_thread() {
    fixed_script().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn fixed_seed_multi_thread() {
    fixed_script().await;
}

#[tokio::test(start_paused = true)]
async fn tokio_virtual_time_is_not_injected_or_operating_system_time() {
    with_watchdog(WATCHDOG, async {
        let clock = TestClock::new(0, Instant::now(), 1);
        let injected_before = clock.monotonic_now();
        let os_before = Instant::now();
        let tokio_before = tokio::time::Instant::now();
        tokio::time::advance(Duration::from_secs(3600)).await;
        assert_eq!(clock.monotonic_now(), injected_before);
        assert_eq!(
            tokio::time::Instant::now() - tokio_before,
            Duration::from_secs(3600)
        );
        assert!(os_before.elapsed() < WATCHDOG);
    })
    .await;
}

#[tokio::test]
async fn system_clock_and_real_timer_integration() {
    with_watchdog(WATCHDOG, async {
        let clock = latent_core::SystemActivationClock;
        assert!(clock.uses_system_monotonic());
        let before = clock.monotonic_now();
        tokio::time::sleep(Duration::from_millis(1)).await;
        assert!(clock.monotonic_now() > before);
    })
    .await;
}

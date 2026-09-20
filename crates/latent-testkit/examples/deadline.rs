//! cargo run -p latent-testkit --no-default-features --example deadline --locked
use std::time::{Duration, Instant};

use latent_core::ActivationClock;
use latent_testkit::{coordination::PollProbe, TestClock};

fn main() {
    let clock = TestClock::new(10_000, Instant::now(), 1);
    let deadline = clock.monotonic_now() + Duration::from_millis(50);
    let mut waiting = Box::pin(clock.sleep_until(deadline));
    let probe = PollProbe::default();
    probe.pending(waiting.as_mut());
    assert_eq!(clock.pending_waiters(), 1);
    clock.set_wall_unix_millis(0); // A wall jump cannot restart this deadline.
    clock.advance(Duration::from_millis(49));
    probe.pending(waiting.as_mut());
    clock.advance(Duration::from_millis(1));
    assert_eq!(probe.wakes(), 1);
    probe.ready(waiting.as_mut());
    assert_eq!(clock.pending_waiters(), 0);
}

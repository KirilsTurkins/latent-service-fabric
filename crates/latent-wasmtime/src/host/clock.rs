//! Clock imports retain only activation-local monotonic observation state.

use std::time::Instant;

use latent_core::ActivationClock;

use super::HostState;
use crate::bindings::latent::clock::{monotonic, wall};

impl monotonic::Host for HostState {
    async fn now_nanos(&mut self) -> u64 {
        let started = Instant::now();
        let value = monotonic_nanos(
            self.clock.as_ref(),
            self.clock_origin,
            &mut self.last_monotonic_nanos,
        );
        self.record_host_call(started);
        value
    }
}

impl wall::Host for HostState {
    async fn now_unix_millis(&mut self) -> u64 {
        let started = Instant::now();
        // Wall-clock adjustments are observable; elapsed time and deadlines
        // remain based on the separate monotonic process clock.
        let value = self.clock.sample().unix_millis();
        self.record_host_call(started);
        value
    }
}

fn monotonic_nanos(clock: &dyn ActivationClock, origin: Instant, last: &mut u64) -> u64 {
    let elapsed = clock.monotonic_now().saturating_duration_since(origin);
    let nanos = u64::try_from(elapsed.as_nanos()).unwrap_or(u64::MAX);
    *last = (*last).max(nanos);
    *last
}

#[cfg(test)]
mod tests {
    use super::*;
    use latent_core::ClockSample;
    use std::sync::Mutex;
    use std::time::Duration;

    struct ManualClock(Mutex<ClockSample>);

    impl ActivationClock for ManualClock {
        fn sample(&self) -> ClockSample {
            *self.0.lock().unwrap()
        }
        fn monotonic_now(&self) -> Instant {
            self.sample().monotonic()
        }
    }

    #[test]
    fn monotonic_observations_clamp_regressions_and_reset_only_for_a_new_activation() {
        let origin = Instant::now();
        let clock = ManualClock(Mutex::new(ClockSample::new(1000, origin)));
        let mut previous = 0;
        assert_eq!(monotonic_nanos(&clock, origin, &mut previous), 0);
        *clock.0.lock().unwrap() = ClockSample::new(1001, origin + Duration::from_nanos(40));
        assert_eq!(monotonic_nanos(&clock, origin, &mut previous), 40);
        *clock.0.lock().unwrap() = ClockSample::new(900, origin + Duration::from_nanos(20));
        assert_eq!(monotonic_nanos(&clock, origin, &mut previous), 40);
        assert_eq!(monotonic_nanos(&clock, origin, &mut 0), 20);
        *clock.0.lock().unwrap() = ClockSample::new(901, origin + Duration::from_nanos(60));
        assert_eq!(monotonic_nanos(&clock, origin, &mut previous), 60);
    }

    #[test]
    fn wall_adjustments_do_not_change_elapsed_monotonic_time() {
        let origin = Instant::now();
        let clock = ManualClock(Mutex::new(ClockSample::new(10_000, origin)));
        let mut previous = 0;
        assert_eq!(clock.sample().unix_millis(), 10_000);
        *clock.0.lock().unwrap() = ClockSample::new(1, origin + Duration::from_nanos(100));
        assert_eq!(clock.sample().unix_millis(), 1);
        assert_eq!(monotonic_nanos(&clock, origin, &mut previous), 100);
        *clock.0.lock().unwrap() = ClockSample::new(u64::MAX, origin + Duration::from_nanos(101));
        assert_eq!(clock.sample().unix_millis(), u64::MAX);
        assert_eq!(monotonic_nanos(&clock, origin, &mut previous), 101);
    }
}

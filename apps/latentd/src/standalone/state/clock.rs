//! Protected operator checkpoint plus one original observed process clock.
use latent_core::{ActivationClock, ClockSample, PlatformError};
use latent_effects::{authority::EffectTime, runtime::EffectTimeSource};
use latent_node::transaction_runtime::CommandTimeSource;
use serde::Deserialize;
use std::sync::{Arc, Mutex};

const DRIFT_MILLIS: u64 = 1000;
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Checkpoint {
    format_version: u32,
    node_id: String,
    owner_epoch: u64,
    clock_floor_unix_millis: u64,
}

pub(super) struct ProtectedCommandClock {
    clock: Arc<dyn ActivationClock>,
    anchor: ClockSample,
    checkpoint: Checkpoint,
    last: Mutex<(ClockSample, bool)>,
}
impl ProtectedCommandClock {
    pub fn load(
        settings: &crate::config::NodeSettings,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<Arc<Self>, PlatformError> {
        let configuration = settings.state.as_ref().ok_or_else(super::denied)?;
        let bytes = latent_protected_files::read(
            &configuration.clock_checkpoint,
            4096,
            latent_protected_files::ProtectedFilePolicy::Secret,
            "stateClockCheckpointProtection",
        )?;
        let checkpoint: Checkpoint = serde_json::from_slice(&bytes).map_err(|_| super::denied())?;
        if checkpoint.format_version != 1 || checkpoint.node_id != settings.node.id.0 {
            return Err(super::denied());
        }
        Self::admitted(checkpoint, clock)
    }
    fn admitted(
        checkpoint: Checkpoint,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<Arc<Self>, PlatformError> {
        let anchor = clock.sample();
        if checkpoint.format_version != 1
            || checkpoint.owner_epoch == 0
            || anchor.unix_millis() < checkpoint.clock_floor_unix_millis
        {
            return Err(super::denied());
        }
        Ok(Arc::new(Self {
            clock,
            anchor,
            checkpoint,
            last: Mutex::new((anchor, false)),
        }))
    }
    pub fn minimum_checkpoint(&self) -> (u64, u64) {
        (
            self.checkpoint.owner_epoch,
            self.checkpoint.clock_floor_unix_millis,
        )
    }
}
impl EffectTimeSource for ProtectedCommandClock {
    fn observe(&self) -> EffectTime {
        let sample = self.clock.sample();
        let mut last = match self.last.lock() {
            Ok(last) => last,
            Err(error) => {
                let mut last = error.into_inner();
                last.1 = true;
                last
            }
        };
        let elapsed = sample
            .monotonic()
            .checked_duration_since(self.anchor.monotonic())
            .and_then(|elapsed| u64::try_from(elapsed.as_millis()).ok());
        let expected = elapsed.and_then(|elapsed| self.anchor.unix_millis().checked_add(elapsed));
        if sample.monotonic() < last.0.monotonic()
            || sample.unix_millis() < last.0.unix_millis()
            || expected
                .is_none_or(|expected| sample.unix_millis().abs_diff(expected) > DRIFT_MILLIS)
        {
            last.1 = true;
        }
        if !last.1 {
            last.0 = sample;
        }
        EffectTime {
            unix_millis: last.0.unix_millis(),
            continuity_proven: !last.1,
        }
    }
}

impl CommandTimeSource for ProtectedCommandClock {
    fn sample(&self) -> latent_commit::atomic::CommandTime {
        let time = self.observe();
        latent_commit::atomic::CommandTime {
            unix_millis: time.unix_millis,
            continuity_proven: time.continuity_proven,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{Duration, Instant};

    struct TestClock(Mutex<ClockSample>);
    impl ActivationClock for TestClock {
        fn sample(&self) -> ClockSample {
            *self.0.lock().unwrap()
        }
        fn monotonic_now(&self) -> Instant {
            self.sample().monotonic()
        }
    }
    impl TestClock {
        fn set(&self, unix: u64, monotonic: Instant) {
            *self.0.lock().unwrap() = ClockSample::new(unix, monotonic);
        }
    }
    fn admitted(
        unix: u64,
        floor: u64,
    ) -> (
        Arc<TestClock>,
        Result<Arc<ProtectedCommandClock>, PlatformError>,
        Instant,
    ) {
        let now = Instant::now();
        let clock = Arc::new(TestClock(Mutex::new(ClockSample::new(unix, now))));
        let owner = ProtectedCommandClock::admitted(
            Checkpoint {
                format_version: 1,
                node_id: "node".into(),
                owner_epoch: 7,
                clock_floor_unix_millis: floor,
            },
            clock.clone(),
        );
        (clock, owner, now)
    }
    #[test]
    fn cumulative_small_wall_jumps_refuse_without_refreshing_original_anchor() {
        let (clock, owner, now) = admitted(10_000, 9_000);
        let owner = owner.unwrap();
        clock.set(10_800, now + Duration::from_millis(100));
        assert!(owner.observe().continuity_proven);
        clock.set(11_600, now + Duration::from_millis(200));
        let stopped = owner.observe();
        assert!(!stopped.continuity_proven);
        assert_eq!(stopped.unix_millis, 10_800);
        clock.set(10_900, now + Duration::from_millis(900));
        let current = owner.observe();
        assert_eq!(current.unix_millis, stopped.unix_millis);
        assert!(!current.continuity_proven);
    }
    #[test]
    fn observed_regression_overflow_and_checkpoint_floor_refuse() {
        assert!(admitted(9, 10).1.is_err());
        let (clock, owner, now) = admitted(10_000, 10_000);
        let owner = owner.unwrap();
        assert_eq!(owner.minimum_checkpoint(), (7, 10_000));
        clock.set(10_100, now + Duration::from_millis(100));
        assert!(owner.observe().continuity_proven);
        clock.set(10_099, now + Duration::from_millis(101));
        assert!(!owner.observe().continuity_proven);
        let (clock, owner, now) = admitted(u64::MAX, u64::MAX);
        let owner = owner.unwrap();
        clock.set(u64::MAX, now + Duration::from_millis(1));
        assert!(!owner.observe().continuity_proven);
    }
    #[test]
    fn poisoned_clock_observation_cannot_certify_continuity() {
        let (_, owner, _) = admitted(10_000, 9_000);
        let owner = owner.unwrap();
        let poisoned = Arc::clone(&owner);
        assert!(std::thread::spawn(move || {
            let _guard = poisoned.last.lock().unwrap();
            panic!("poison clock fixture");
        })
        .join()
        .is_err());
        assert!(!owner.observe().continuity_proven);
    }
}

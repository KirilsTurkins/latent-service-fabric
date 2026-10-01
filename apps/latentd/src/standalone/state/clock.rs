//! Protected operator checkpoint plus one original observed process clock.
use latent_core::{ActivationClock, ClockSample, PlatformError};
use latent_effects::{authority::EffectTime, runtime::EffectTimeSource};
use latent_node::transaction_runtime::CommandTimeSource;
use latent_wire::phase4::StateMaintenanceClock;
use serde::Deserialize;
use std::{
    sync::{Arc, Mutex, OnceLock},
    time::Instant,
};

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
    maintenance: MaintenanceOrigin,
}

#[derive(Clone, Copy)]
struct MaintenanceOrigin {
    boot: [u8; 32],
    monotonic: Instant,
}
impl MaintenanceOrigin {
    fn process() -> Result<Self, PlatformError> {
        static ORIGIN: OnceLock<Result<MaintenanceOrigin, ()>> = OnceLock::new();
        ORIGIN
            .get_or_init(|| {
                let mut boot = [0; 32];
                rustls::crypto::ring::default_provider()
                    .secure_random
                    .fill(&mut boot)
                    .map_err(|_| ())?;
                if boot == [0; 32] {
                    return Err(());
                }
                Ok(Self {
                    boot,
                    monotonic: Instant::now(),
                })
            })
            .as_ref()
            .copied()
            .map_err(|()| super::unavailable())
    }
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
        Self::with_origin(checkpoint, clock, MaintenanceOrigin::process()?)
    }
    fn with_origin(
        checkpoint: Checkpoint,
        clock: Arc<dyn ActivationClock>,
        maintenance: MaintenanceOrigin,
    ) -> Result<Arc<Self>, PlatformError> {
        let anchor = clock.sample();
        if checkpoint.format_version != 1
            || checkpoint.owner_epoch == 0
            || anchor.unix_millis() < checkpoint.clock_floor_unix_millis
            || maintenance.boot == [0; 32]
            || anchor.monotonic() < maintenance.monotonic
        {
            return Err(super::denied());
        }
        Ok(Arc::new(Self {
            clock,
            anchor,
            checkpoint,
            last: Mutex::new((anchor, false)),
            maintenance,
        }))
    }
    pub fn minimum_checkpoint(&self) -> (u64, u64) {
        (
            self.checkpoint.owner_epoch,
            self.checkpoint.clock_floor_unix_millis,
        )
    }

    /// Read once. All consumers use this accepted wall/monotonic pair; a second
    /// raw sample could cross a discontinuity after the first was approved.
    fn protected_sample(&self) -> (ClockSample, bool) {
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
            || sample
                .monotonic()
                .checked_duration_since(self.maintenance.monotonic)
                .and_then(|elapsed| u64::try_from(elapsed.as_millis()).ok())
                .is_none()
            || expected
                .is_none_or(|expected| sample.unix_millis().abs_diff(expected) > DRIFT_MILLIS)
        {
            last.1 = true;
        }
        if !last.1 {
            last.0 = sample;
        }
        (last.0, !last.1)
    }
}
impl EffectTimeSource for ProtectedCommandClock {
    fn observe(&self) -> EffectTime {
        let (sample, continuity_proven) = self.protected_sample();
        EffectTime {
            unix_millis: sample.unix_millis(),
            continuity_proven,
        }
    }
}

impl StateMaintenanceClock for ProtectedCommandClock {
    fn sample(&self) -> Result<latent_commit::atomic::MaintenanceClock, PlatformError> {
        let (sample, continuity_proven) = self.protected_sample();
        if !continuity_proven {
            return Err(super::unavailable());
        }
        let monotonic_millis = sample
            .monotonic()
            .checked_duration_since(self.maintenance.monotonic)
            .and_then(|elapsed| u64::try_from(elapsed.as_millis()).ok())
            .ok_or_else(super::unavailable)?;
        Ok(latent_commit::atomic::MaintenanceClock {
            time: latent_commit::atomic::CommandTime {
                unix_millis: sample.unix_millis(),
                continuity_proven,
            },
            boot: self.maintenance.boot,
            monotonic_millis,
        })
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
        let owner = ProtectedCommandClock::with_origin(
            Checkpoint {
                format_version: 1,
                node_id: "node".into(),
                owner_epoch: 7,
                clock_floor_unix_millis: floor,
            },
            clock.clone(),
            MaintenanceOrigin {
                boot: [7; 32],
                monotonic: now,
            },
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

    #[test]
    fn maintenance_observation_uses_one_coherent_protected_sample() {
        use std::sync::atomic::{AtomicU64, Ordering};
        struct CountingClock {
            anchor: Instant,
            calls: AtomicU64,
        }
        impl ActivationClock for CountingClock {
            fn sample(&self) -> ClockSample {
                let tick = self.calls.fetch_add(1, Ordering::Relaxed) * 11;
                ClockSample::new(10_000 + tick, self.anchor + Duration::from_millis(tick))
            }
            fn monotonic_now(&self) -> Instant {
                panic!("maintenance must use the accepted coherent sample")
            }
        }
        let now = Instant::now();
        let clock = Arc::new(CountingClock {
            anchor: now,
            calls: AtomicU64::new(0),
        });
        let owner = ProtectedCommandClock::with_origin(
            Checkpoint {
                format_version: 1,
                node_id: "node".into(),
                owner_epoch: 1,
                clock_floor_unix_millis: 10_000,
            },
            clock.clone(),
            MaintenanceOrigin {
                boot: [1; 32],
                monotonic: now,
            },
        )
        .unwrap();
        let sample = StateMaintenanceClock::sample(owner.as_ref()).unwrap();
        assert_eq!(clock.calls.load(Ordering::Relaxed), 2);
        assert_eq!(sample.time.unix_millis, 10_011);
        assert_eq!(sample.monotonic_millis, 11);
        assert!(sample.time.continuity_proven);
    }

    #[test]
    fn process_maintenance_boot_and_monotonic_origin_survive_clock_owner_reload() {
        let first = MaintenanceOrigin::process().unwrap();
        let second = MaintenanceOrigin::process().unwrap();
        assert_ne!(first.boot, [0; 32]);
        assert_eq!(first.boot, second.boot);
        assert_eq!(first.monotonic, second.monotonic);
        let clock = Arc::new(TestClock(Mutex::new(ClockSample::new(
            10_000,
            first.monotonic,
        ))));
        let checkpoint = || Checkpoint {
            format_version: 1,
            node_id: "node".into(),
            owner_epoch: 1,
            clock_floor_unix_millis: 10_000,
        };
        let one = ProtectedCommandClock::admitted(checkpoint(), clock.clone()).unwrap();
        clock.set(10_050, first.monotonic + Duration::from_millis(50));
        let two = ProtectedCommandClock::admitted(checkpoint(), clock).unwrap();
        let one = StateMaintenanceClock::sample(one.as_ref()).unwrap();
        let two = StateMaintenanceClock::sample(two.as_ref()).unwrap();
        assert_eq!(one.boot, two.boot);
        assert_eq!(one.monotonic_millis, 50);
        assert_eq!(one.monotonic_millis, two.monotonic_millis);
    }

    #[test]
    fn maintenance_cannot_recover_a_sticky_protected_clock_discontinuity() {
        let (clock, owner, now) = admitted(10_000, 9_000);
        let owner = owner.unwrap();
        clock.set(10_800, now + Duration::from_millis(100));
        assert!(StateMaintenanceClock::sample(owner.as_ref()).is_ok());
        clock.set(11_600, now + Duration::from_millis(200));
        assert!(StateMaintenanceClock::sample(owner.as_ref()).is_err());
        clock.set(10_900, now + Duration::from_millis(900));
        assert!(StateMaintenanceClock::sample(owner.as_ref()).is_err());
        assert!(!CommandTimeSource::sample(owner.as_ref()).continuity_proven);
    }

    #[test]
    fn new_boot_holds_engine_retention_until_explicit_authorized_reanchor() {
        use latent_commit::atomic::{AtomicError, ResultMaintenanceOwner};
        use latent_state::embedded::{EmbeddedStore, StoreLimits};
        let store = EmbeddedStore::open_file(tempfile::tempfile().unwrap(), StoreLimits::default())
            .unwrap();
        let (clock, old, now) = admitted(10_000, 9_000);
        let old = old.unwrap();
        let maintenance = ResultMaintenanceOwner::default();
        let old_sample = StateMaintenanceClock::sample(old.as_ref()).unwrap();
        let original = maintenance
            .anchor(&store, None, old_sample, |_| Ok(()))
            .unwrap();
        clock.set(11_000, now + Duration::from_secs(1));
        let restarted = ProtectedCommandClock::with_origin(
            Checkpoint {
                format_version: 1,
                node_id: "node".into(),
                owner_epoch: 8,
                clock_floor_unix_millis: 11_000,
            },
            clock,
            MaintenanceOrigin {
                boot: [8; 32],
                monotonic: now + Duration::from_millis(500),
            },
        )
        .unwrap();
        let current = StateMaintenanceClock::sample(restarted.as_ref()).unwrap();
        assert_ne!(current.boot, old_sample.boot);
        assert_eq!(
            maintenance.step(&store, current, |_| Ok(())),
            Err(AtomicError::RecoveryRequired)
        );
        assert_eq!(
            maintenance.anchor(&store, Some(original.generation), current, |_| {
                Err(AtomicError::PermissionDenied)
            }),
            Err(AtomicError::PermissionDenied)
        );
        let accepted = maintenance
            .anchor(&store, Some(original.generation), current, |_| Ok(()))
            .unwrap();
        assert_eq!(accepted.boot, current.boot);
        assert_eq!(accepted.generation, original.generation + 1);
        assert_eq!(accepted.retired, 0);
        assert_eq!(
            maintenance
                .step(&store, current, |_| Ok(()))
                .unwrap()
                .retired,
            0
        );
    }
}

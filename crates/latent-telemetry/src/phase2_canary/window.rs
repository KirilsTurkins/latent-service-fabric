use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, Weak};
use std::time::{Duration, Instant};

use latent_core::{ActivationClock, PlatformError, PlatformErrorCode, SystemActivationClock};

use super::capture::CanaryCapture;
use super::model::{
    bounded_spec, CanaryWindowSpec, Phase2CanaryOutcomeWindowConfig, Phase2CanaryWindowSnapshot,
};
use super::snapshot::{CanaryRevisionSnapshot, CanaryWindowSnapshot};
use super::{error, model::MAX_REVISIONS};

pub(super) struct Hub {
    pub config: Phase2CanaryOutcomeWindowConfig,
    pub clock: Arc<dyn ActivationClock>,
    pub registry: Mutex<Registry>,
    pub live: AtomicUsize,
    pub samples: AtomicUsize,
    pub snapshots: AtomicUsize,
    pub loss_epoch: AtomicU64,
    pub exhausted: AtomicBool,
    /// Entered capture attempts, including a failed registry acquisition whose
    /// loss publication has not finished. Live guards bound this to actual calls.
    pub attempts: AtomicUsize,
}

pub(super) struct Registry {
    pub slots: Vec<Slot>,
    next_epoch: u64,
}

pub(super) struct Slot {
    pub window: Weak<Window>,
    pub retained: Arc<AtomicBool>,
}

pub(super) struct WindowReservation {
    hub: Arc<Hub>,
    retained: Arc<AtomicBool>,
    pub starts: AtomicUsize,
}

pub(super) struct Window {
    pub hub: Arc<Hub>,
    pub spec: CanaryWindowSpec,
    pub epoch: u64,
    pub loss_epoch: u64,
    pub deadline: Instant,
    pub started: Instant,
    pub closed: AtomicBool,
    pub early_closed: AtomicBool,
    pub retired: AtomicBool,
    pub lost: AtomicBool,
    pub live: AtomicUsize,
    pub stats: Mutex<Stats>,
    // Last: metadata/stats are released before their slot/sample allowance.
    pub reservation: WindowReservation,
}

#[derive(Clone, Copy, Default)]
pub(super) struct Stats {
    pub selected: u64,
    pub admitted: u64,
    pub terminal: u64,
    pub unattributed: u64,
    pub abandoned: u64,
    pub revisions: [CanaryRevisionSnapshot; MAX_REVISIONS],
}

/// One bounded host owner; no background workers or per-window tasks.
#[derive(Clone)]
pub struct BoundedPhase2CanaryOutcomeWindow(pub(super) Arc<Hub>);

/// Trusted control owner of one immutable cohort. Dropping it closes capture.
pub struct CanaryWindow(pub(super) Arc<Window>);

impl BoundedPhase2CanaryOutcomeWindow {
    pub fn new(config: Phase2CanaryOutcomeWindowConfig) -> Result<Self, PlatformError> {
        Self::with_clock(config, Arc::new(SystemActivationClock))
    }

    /// The supplied clock must be trusted and its monotonic read nonblocking.
    pub fn with_clock(
        config: Phase2CanaryOutcomeWindowConfig,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<Self, PlatformError> {
        config.validate()?;
        Ok(Self(Arc::new(Hub {
            config,
            clock,
            registry: Mutex::new(Registry {
                slots: (0..config.maximum_series)
                    .map(|_| Slot {
                        window: Weak::new(),
                        retained: Arc::new(AtomicBool::new(false)),
                    })
                    .collect(),
                next_epoch: 1,
            }),
            live: AtomicUsize::new(0),
            samples: AtomicUsize::new(0),
            snapshots: AtomicUsize::new(0),
            loss_epoch: AtomicU64::new(0),
            exhausted: AtomicBool::new(false),
            attempts: AtomicUsize::new(0),
        })))
    }

    /// Control only. At most one open window may observe a tenant/service pair.
    pub fn register(&self, spec: &CanaryWindowSpec) -> Result<CanaryWindow, PlatformError> {
        let mut registry = self.0.registry.try_lock().map_err(|_| busy())?;
        // Establish the loss baseline before the interval's start. A producer
        // failing this held lock during registration cannot disappear into a
        // newer baseline sampled after its failed in-window capture.
        let loss_epoch = self.0.loss_epoch.load(Ordering::Acquire);
        let available = registry
            .slots
            .iter()
            .position(|slot| !slot.retained.load(Ordering::Acquire))
            .ok_or_else(capacity)?;
        let now = self.0.clock.monotonic_now();
        for slot in &registry.slots {
            if let Some(window) = slot.window.upgrade() {
                if !window.closed.load(Ordering::Acquire)
                    && now < window.deadline
                    && window.spec.identity.tenant == spec.identity.tenant
                    && window.spec.identity.service == spec.identity.service
                {
                    return Err(error(
                        PlatformErrorCode::AlreadyExists,
                        "phase2-canary-window-overlap",
                    ));
                }
            }
        }
        let spec = bounded_spec(spec, self.0.config.maximum_identity_bytes)?;
        let deadline = now.checked_add(spec.duration).ok_or_else(capacity)?;
        let epoch = registry.next_epoch;
        registry.next_epoch = epoch.checked_add(1).ok_or_else(capacity)?;
        let window = Arc::new(Window {
            hub: Arc::clone(&self.0),
            spec,
            epoch,
            loss_epoch,
            deadline,
            started: now,
            closed: AtomicBool::new(false),
            early_closed: AtomicBool::new(false),
            retired: AtomicBool::new(false),
            lost: AtomicBool::new(false),
            live: AtomicUsize::new(0),
            stats: Mutex::new(Stats::default()),
            reservation: WindowReservation {
                hub: Arc::clone(&self.0),
                retained: Arc::clone(&registry.slots[available].retained),
                starts: AtomicUsize::new(0),
            },
        });
        registry.slots[available]
            .retained
            .store(true, Ordering::Release);
        registry.slots[available].window = Arc::downgrade(&window);
        Ok(CanaryWindow(window))
    }

    #[must_use]
    pub fn capture_handle(&self) -> CanaryCapture {
        CanaryCapture(Arc::clone(&self.0))
    }

    #[must_use]
    pub fn same_owner(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.0, &other.0)
    }

    #[must_use]
    pub fn config(&self) -> Phase2CanaryOutcomeWindowConfig {
        self.0.config
    }

    pub fn snapshot(&self) -> Result<Phase2CanaryWindowSnapshot, PlatformError> {
        let registry = self.0.registry.try_lock().map_err(|_| busy())?;
        Ok(Phase2CanaryWindowSnapshot {
            tracked_series: registry
                .slots
                .iter()
                .filter(|slot| slot.retained.load(Ordering::Acquire))
                .count(),
            total_samples: self.0.samples.load(Ordering::Acquire),
            live_samples: self.0.live.load(Ordering::Acquire),
            snapshot_owners: self.0.snapshots.load(Ordering::Acquire),
            unattributed_loss_epoch: self.0.loss_epoch.load(Ordering::Acquire),
            loss_epoch_exhausted: self.0.exhausted.load(Ordering::Acquire),
        })
    }
}

impl CanaryWindow {
    /// Stop memberships without waiting for live samples. Terminal owners remain charged.
    pub fn close(&self) -> Result<(), PlatformError> {
        let _registry = self.0.hub.registry.try_lock().map_err(|_| busy())?;
        if self.0.hub.clock.monotonic_now() < self.0.deadline {
            self.0.early_closed.store(true, Ordering::Release);
        }
        self.0.closed.store(true, Ordering::Release);
        Ok(())
    }

    pub fn snapshot(&self, required_samples: usize) -> Result<CanaryWindowSnapshot, PlatformError> {
        CanaryWindowSnapshot::capture(&self.0, required_samples)
    }

    #[must_use]
    pub fn elapsed(&self) -> Duration {
        self.0
            .hub
            .clock
            .monotonic_now()
            .saturating_duration_since(self.0.started)
            .min(self.0.spec.duration)
    }

    /// Owner Drop also closes capture; retained samples/snapshots keep the slot charged.
    pub fn retire(self) {
        drop(self);
    }
}

impl Drop for CanaryWindow {
    fn drop(&mut self) {
        self.0.retired.store(true, Ordering::Release);
        self.0.closed.store(true, Ordering::Release);
    }
}

impl Drop for WindowReservation {
    fn drop(&mut self) {
        self.hub
            .samples
            .fetch_sub(*self.starts.get_mut(), Ordering::AcqRel);
        self.retained.store(false, Ordering::Release);
    }
}

impl Hub {
    pub fn lose_unattributed(&self) {
        let old = self.loss_epoch.load(Ordering::Acquire);
        // One attempt only: contention/saturation is an explicit permanent unknown.
        if old.checked_add(1).is_none_or(|next| {
            self.loss_epoch
                .compare_exchange(old, next, Ordering::AcqRel, Ordering::Acquire)
                .is_err()
        }) {
            self.exhausted.store(true, Ordering::Release);
        }
    }
}

pub(super) fn busy() -> PlatformError {
    error(PlatformErrorCode::Unavailable, "phase2-canary-busy")
}
pub(super) fn capacity() -> PlatformError {
    error(
        PlatformErrorCode::ResourceExhausted,
        "phase2-canary-capacity",
    )
}

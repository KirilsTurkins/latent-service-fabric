use std::sync::atomic::Ordering;
use std::sync::Arc;

use latent_core::{PlatformError, PlatformErrorCode};

use super::model::{CanaryCoverage, CanaryRevisionBinding, CanaryWindowIdentity};
use super::window::{busy, capacity, Hub, Stats, Window};
use super::{error, Phase2CanaryOutcomeCounters};

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct CanaryRevisionSnapshot {
    pub selected: u64,
    pub admitted: u64,
    pub admitted_terminal: u64,
    pub outcomes: Phase2CanaryOutcomeCounters,
    /// Inclusive fixed microsecond bounds are `CANARY_LATENCY_UPPER_MICROS`.
    pub latency_buckets: [u64; 9],
}

/// Bounded owned readout, not a promotion/authorization capability. Retains its
/// window slot and one snapshot allowance; cannot be cloned or deserialized.
pub struct CanaryWindowSnapshot {
    window: Arc<Window>,
    stats: Stats,
    starts: usize,
    live: usize,
    closed: bool,
    required: usize,
    _allowance: SnapshotAllowance,
}

struct SnapshotAllowance(Arc<Hub>);

impl CanaryWindowSnapshot {
    pub(super) fn capture(window: &Arc<Window>, required: usize) -> Result<Self, PlatformError> {
        if required == 0 || required > window.hub.config.maximum_samples_per_series {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-phase2-canary-required-samples",
            ));
        }
        let _registry = window.hub.registry.try_lock().map_err(|_| busy())?;
        let stats = window.stats.try_lock().map_err(|_| busy())?;
        if window.hub.snapshots.load(Ordering::Acquire) >= window.hub.config.maximum_snapshot_owners
        {
            return Err(capacity());
        }
        let closed = window.closed.load(Ordering::Acquire)
            || window.hub.clock.monotonic_now() >= window.deadline;
        window.hub.snapshots.fetch_add(1, Ordering::AcqRel);
        Ok(Self {
            window: Arc::clone(window),
            stats: *stats,
            starts: window.reservation.starts.load(Ordering::Acquire),
            live: window.live.load(Ordering::Acquire),
            closed,
            required,
            _allowance: SnapshotAllowance(Arc::clone(&window.hub)),
        })
    }

    #[must_use]
    pub fn identity(&self) -> &CanaryWindowIdentity {
        &self.window.spec.identity
    }
    #[must_use]
    pub fn revisions(&self) -> &[CanaryRevisionBinding] {
        &self.window.spec.revisions
    }
    #[must_use]
    pub fn revision_outcomes(&self) -> &[CanaryRevisionSnapshot] {
        &self.stats.revisions[..self.window.spec.revisions.len()]
    }
    #[must_use]
    pub fn epoch(&self) -> u64 {
        self.window.epoch
    }
    #[must_use]
    pub fn starts(&self) -> usize {
        self.starts
    }
    #[must_use]
    pub fn live(&self) -> usize {
        self.live
    }
    #[must_use]
    pub fn selected(&self) -> u64 {
        self.stats.selected
    }
    #[must_use]
    pub fn admitted(&self) -> u64 {
        self.stats.admitted
    }
    #[must_use]
    pub fn terminal(&self) -> u64 {
        self.stats.terminal
    }
    #[must_use]
    pub fn unattributed(&self) -> u64 {
        self.stats.unattributed
    }
    #[must_use]
    pub fn abandoned(&self) -> u64 {
        self.stats.abandoned
    }

    /// Unknown capture loss is conservative across windows. A later loss may
    /// downgrade a retained snapshot; copyable counters are never validated proof.
    #[must_use]
    pub fn coverage(&self) -> CanaryCoverage {
        if self.window.lost.load(Ordering::Acquire)
            || self.window.retired.load(Ordering::Acquire)
            || self.window.hub.exhausted.load(Ordering::Acquire)
            || self.window.hub.loss_epoch.load(Ordering::Acquire) != self.window.loss_epoch
        {
            return CanaryCoverage::Incomplete;
        }
        if !self.closed {
            return CanaryCoverage::Open;
        }
        if self.live != 0 {
            return CanaryCoverage::Draining;
        }
        if self.stats.terminal != self.starts as u64 || self.stats.selected != self.stats.terminal {
            return CanaryCoverage::Incomplete;
        }
        if self.starts == 0 {
            CanaryCoverage::NoSamples
        } else if self.starts < self.required {
            CanaryCoverage::Insufficient
        } else {
            CanaryCoverage::CompleteData
        }
    }
}

impl Drop for SnapshotAllowance {
    fn drop(&mut self) {
        self.0.snapshots.fetch_sub(1, Ordering::AcqRel);
    }
}

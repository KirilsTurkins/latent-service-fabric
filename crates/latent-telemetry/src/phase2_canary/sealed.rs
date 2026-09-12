//! An affine, immutable observation cut. The diagnostic snapshot intentionally
//! retains conservative later-loss downgrades; this proof freezes only after the
//! full interval and every pre-cut producer has actually retired.
use std::sync::{atomic::Ordering, Arc};
use std::time::Duration;

use latent_core::{ArtifactBlobDigest, PlatformError, PlatformErrorCode, RevisionId};

use super::snapshot::SnapshotAllowance;
use super::window::{busy, capacity, Stats, Window};
use super::{
    error, policy, BoundedPhase2CanaryOutcomeWindow, CanaryAssessment, CanaryCoverage,
    CanaryRevisionBinding, CanaryRevisionSnapshot, CanaryThresholds, CanaryWindow,
    CanaryWindowIdentity,
};

/// No public constructor, Clone or deserialization. Retains the actual window
/// slot and a read allowance through the consumer's catalog commit boundary.
pub struct SealedCanaryWindow {
    window: Arc<Window>,
    stats: Stats,
    starts: usize,
    // Last: copied data and retained metadata precede allowance release.
    _allowance: SnapshotAllowance,
}

impl std::fmt::Debug for SealedCanaryWindow {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SealedCanaryWindow")
            .field("identity", self.identity())
            .field("epoch", &self.epoch())
            .finish_non_exhaustive()
    }
}

impl CanaryWindow {
    /// One bounded attempt, with no waiting or new worker. Incomplete/early-closed
    /// windows never qualify, even if a caller later waits past their deadline.
    pub fn try_seal(&self) -> Result<SealedCanaryWindow, PlatformError> {
        let window = &self.0;
        let hub = &window.hub;
        let _registry = hub.registry.try_lock().map_err(|_| busy())?;
        if window.early_closed.load(Ordering::Acquire) || window.retired.load(Ordering::Acquire) {
            return Err(incomplete());
        }
        if hub.clock.monotonic_now() < window.deadline {
            return Err(error(PlatformErrorCode::Unavailable, "canary-window-open"));
        }
        window.closed.store(true, Ordering::Release);
        // The full interval ended before this cut. A new producer entering after
        // the zero read is outside the closed interval. A failed earlier producer
        // cannot retire its guard until its loss epoch has been published.
        if hub.attempts.load(Ordering::SeqCst) != 0 || window.live.load(Ordering::Acquire) != 0 {
            return Err(error(
                PlatformErrorCode::Unavailable,
                "canary-window-draining",
            ));
        }
        let stats = window.stats.try_lock().map_err(|_| busy())?;
        let captured_count = window.reservation.starts.load(Ordering::Acquire);
        if window.lost.load(Ordering::Acquire)
            || hub.exhausted.load(Ordering::Acquire)
            || hub.loss_epoch.load(Ordering::Acquire) != window.loss_epoch
            || stats.terminal != captured_count as u64
            || stats.selected != stats.terminal
            || stats.unattributed != 0
            || stats.abandoned != 0
        {
            return Err(incomplete());
        }
        if hub.snapshots.load(Ordering::Acquire) >= hub.config.maximum_snapshot_owners {
            return Err(capacity());
        }
        hub.snapshots.fetch_add(1, Ordering::AcqRel);
        Ok(SealedCanaryWindow {
            window: Arc::clone(window),
            stats: *stats,
            starts: captured_count,
            _allowance: SnapshotAllowance(Arc::clone(hub)),
        })
    }
}

impl BoundedPhase2CanaryOutcomeWindow {
    #[must_use]
    pub fn owns_sealed(&self, proof: &SealedCanaryWindow) -> bool {
        Arc::ptr_eq(&self.0, &proof.window.hub)
    }
}

impl SealedCanaryWindow {
    #[must_use]
    pub fn identity(&self) -> &CanaryWindowIdentity {
        &self.window.spec.identity
    }
    #[must_use]
    pub fn control_digest(&self) -> Option<&ArtifactBlobDigest> {
        self.window.spec.control_digest.as_ref()
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
    pub fn duration(&self) -> Duration {
        self.window.spec.duration
    }
    #[must_use]
    pub fn starts(&self) -> usize {
        self.starts
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

    pub fn assess_candidate(
        &self,
        candidate: &RevisionId,
        thresholds: CanaryThresholds,
    ) -> Result<CanaryAssessment, PlatformError> {
        policy::assess(
            self.revisions(),
            self.revision_outcomes(),
            candidate,
            thresholds,
            if self.starts == 0 {
                CanaryCoverage::NoSamples
            } else {
                CanaryCoverage::CompleteData
            },
            false,
        )
    }
}

fn incomplete() -> PlatformError {
    error(PlatformErrorCode::Unavailable, "canary-window-incomplete")
}

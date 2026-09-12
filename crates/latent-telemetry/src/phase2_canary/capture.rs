use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

use latent_core::{
    ActivationTerminalState, ReleaseDigest, RevisionId, RouteGeneration, ServiceId, TenantId,
};

use super::model::CANARY_LATENCY_UPPER_MICROS;
use super::window::{Hub, Window};
use super::Phase2CanaryOutcomeClass;
use crate::{ActivationObservationToken, ActivationOutcomeClass, ActivationTerminalObservation};

#[derive(Clone)]
pub struct CanaryCapture(pub(super) Arc<Hub>);

/// A trusted producer's attempt, with no allocated error or caller-supplied text.
pub enum CanaryCaptureAttempt {
    Captured(CanarySample),
    NotObserved,
    Lost,
}

impl CanaryCaptureAttempt {
    #[must_use]
    pub fn into_sample(self) -> Option<CanarySample> {
        match self {
            Self::Captured(sample) => Some(sample),
            Self::NotObserved | Self::Lost => None,
        }
    }
}

/// Borrowed fields from the exact revision selected by the activation owner.
pub struct SelectedOutcomeRevision<'a> {
    pub tenant: &'a TenantId,
    pub service: &'a ServiceId,
    pub revision: &'a RevisionId,
    pub component: &'a ReleaseDigest,
    pub generation: RouteGeneration,
}

/// Affine host-only sample. No Clone/Deserialize or terminal-event injection RPC.
pub struct CanarySample {
    window: Arc<Window>,
    token: ActivationObservationToken,
    selected: Option<usize>,
    admitted: bool,
    finished: bool,
}

impl CanaryCapture {
    /// Call once per accepted activation. Uses only bounded try-acquisition and
    /// existing preallocated slots; loss never changes the activation result.
    #[must_use]
    pub fn try_begin(
        &self,
        token: ActivationObservationToken,
        tenant: &TenantId,
        service: &ServiceId,
    ) -> CanaryCaptureAttempt {
        // The guard enters before try_lock and retires after any loss is visible.
        // A control seal cannot miss a failed capture paused before loss publication.
        let _attempt = CaptureFrontier::enter(&self.0);
        let Ok(registry) = self.0.registry.try_lock() else {
            self.0.lose_unattributed();
            return CanaryCaptureAttempt::Lost;
        };
        let now = self.0.clock.monotonic_now();
        for slot in &registry.slots {
            let Some(window) = slot.window.upgrade() else {
                continue;
            };
            if window.spec.identity.tenant != *tenant
                || window.spec.identity.service != *service
                || window.closed.load(Ordering::Acquire)
                || now >= window.deadline
            {
                continue;
            }
            if window.reservation.starts.load(Ordering::Acquire)
                >= self.0.config.maximum_samples_per_series
                || self.0.samples.load(Ordering::Acquire) >= self.0.config.maximum_total_samples
                || self.0.live.load(Ordering::Acquire) >= self.0.config.maximum_live_samples
            {
                window.lost.store(true, Ordering::Release);
                return CanaryCaptureAttempt::Lost;
            }
            // Increments serialize under registry; terminal/Drop may only decrease live.
            window.reservation.starts.fetch_add(1, Ordering::AcqRel);
            window.live.fetch_add(1, Ordering::AcqRel);
            self.0.samples.fetch_add(1, Ordering::AcqRel);
            self.0.live.fetch_add(1, Ordering::AcqRel);
            return CanaryCaptureAttempt::Captured(CanarySample {
                window,
                token,
                selected: None,
                admitted: false,
                finished: false,
            });
        }
        CanaryCaptureAttempt::NotObserved
    }
}

impl CanarySample {
    #[must_use]
    pub fn token(&self) -> ActivationObservationToken {
        self.token
    }

    /// Repeated refreshes must retain the original selection. A mismatch is loss.
    #[expect(
        clippy::needless_pass_by_value,
        reason = "existing observation hooks pass this temporary borrowed selection view inline"
    )]
    pub fn bind_selected(&mut self, selected: SelectedOutcomeRevision<'_>) {
        let identity = &self.window.spec.identity;
        let index = self.window.spec.revisions.iter().position(|binding| {
            binding.revision == *selected.revision && binding.component == *selected.component
        });
        if identity.tenant != *selected.tenant
            || identity.service != *selected.service
            || identity.generation != selected.generation
            || index.is_none()
            || self.selected.is_some_and(|old| Some(old) != index)
        {
            self.window.lost.store(true, Ordering::Release);
            return;
        }
        if self.selected.is_some() {
            return;
        }
        self.selected = index;
        let Ok(mut stats) = self.window.stats.try_lock() else {
            self.window.lost.store(true, Ordering::Release);
            return;
        };
        stats.selected += 1;
        if let Some(index) = index {
            stats.revisions[index].selected += 1;
        }
    }

    pub fn admitted(&mut self) {
        if self.admitted {
            return;
        }
        self.admitted = true;
        let Ok(mut stats) = self.window.stats.try_lock() else {
            self.window.lost.store(true, Ordering::Release);
            return;
        };
        stats.admitted += 1;
        if let Some(index) = self.selected {
            stats.revisions[index].admitted += 1;
        } else {
            self.window.lost.store(true, Ordering::Release);
        }
    }

    pub fn finish(mut self, terminal: &ActivationTerminalObservation, elapsed: Duration) {
        self.finished = true;
        let Ok(mut stats) = self.window.stats.try_lock() else {
            self.window.lost.store(true, Ordering::Release);
            return;
        };
        stats.terminal += 1;
        let Some(index) = self.selected else {
            stats.unattributed += 1;
            self.window.lost.store(true, Ordering::Release);
            return;
        };
        let revision = &mut stats.revisions[index];
        let outcome = classify(terminal);
        if revision.outcomes.record(outcome).is_err() {
            self.window.lost.store(true, Ordering::Release);
        }
        if self.admitted {
            revision.admitted_terminal += 1;
        }
        let bucket = CANARY_LATENCY_UPPER_MICROS
            .iter()
            .position(|edge| elapsed <= Duration::from_micros(*edge))
            .unwrap_or(8);
        revision.latency_buckets[bucket] += 1;
    }
}

pub(super) struct CaptureFrontier<'a>(&'a Hub);

impl<'a> CaptureFrontier<'a> {
    pub(super) fn enter(hub: &'a Hub) -> Self {
        // This is a live-owner count, not an ever-increasing event sequence.
        // Every increment has its own nonzero-sized stack guard until retirement.
        hub.attempts.fetch_add(1, Ordering::SeqCst);
        Self(hub)
    }
}

impl Drop for CaptureFrontier<'_> {
    fn drop(&mut self) {
        self.0.attempts.fetch_sub(1, Ordering::SeqCst);
    }
}

impl Drop for CanarySample {
    fn drop(&mut self) {
        if !self.finished {
            self.window.lost.store(true, Ordering::Release);
            if let Ok(mut stats) = self.window.stats.try_lock() {
                stats.abandoned += 1;
            }
        }
        // Publish terminal/loss first. Seeing live==0 cannot precede that bookkeeping.
        self.window.live.fetch_sub(1, Ordering::AcqRel);
        self.window.hub.live.fetch_sub(1, Ordering::AcqRel);
    }
}

fn classify(terminal: &ActivationTerminalObservation) -> Phase2CanaryOutcomeClass {
    match terminal.class {
        ActivationOutcomeClass::GuestSuccess => Phase2CanaryOutcomeClass::Success,
        ActivationOutcomeClass::GuestDomainError => Phase2CanaryOutcomeClass::DomainError,
        ActivationOutcomeClass::PlatformFailure => match terminal.terminal_state {
            ActivationTerminalState::DeadlineExceeded => Phase2CanaryOutcomeClass::DeadlineExceeded,
            ActivationTerminalState::Cancelled => Phase2CanaryOutcomeClass::Cancelled,
            _ => Phase2CanaryOutcomeClass::PlatformError,
        },
    }
}

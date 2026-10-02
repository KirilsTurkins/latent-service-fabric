use crate::supply_chain::{unavailable, State};
use latent_core::PlatformError;
use std::sync::atomic::{AtomicU64, Ordering};

/// Only the original state owner publishes a new accepted floor. Sequentially
/// consistent fields make a single bounded read reject an overlapping publish;
/// no reader spins or waits for the admission/currentness mutex.
pub(in crate::supply_chain) struct Metadata {
    revision: AtomicU64,
    epoch: AtomicU64,
    covered_until: AtomicU64,
    valid_from: AtomicU64,
    valid_until: AtomicU64,
    observed_at: AtomicU64,
}

pub(super) struct Snapshot {
    pub revision: u64,
    pub epoch: u64,
    pub covered_until: u64,
    pub valid_from: u64,
    pub valid_until: u64,
}

impl Metadata {
    pub(in crate::supply_chain) fn new(state: &State) -> Self {
        Self {
            revision: AtomicU64::new(2),
            epoch: AtomicU64::new(state.floor.epoch),
            covered_until: AtomicU64::new(state.floor.restart_not_before),
            valid_from: AtomicU64::new(state.policy.identity.valid_from),
            valid_until: AtomicU64::new(state.policy.identity.valid_until),
            observed_at: AtomicU64::new(state.observed_at),
        }
    }

    pub(in crate::supply_chain) fn observed_at(&self) -> u64 {
        self.observed_at.load(Ordering::SeqCst)
    }

    pub(in crate::supply_chain) fn record(&self, now: u64) {
        self.observed_at.fetch_max(now, Ordering::SeqCst);
    }

    pub(super) fn record_current(&self, now: u64) -> Result<(), PlatformError> {
        if self.observed_at.fetch_max(now, Ordering::SeqCst) > now {
            // A concurrent successful observation may complete first. That is
            // contention, not evidence that the trusted clock moved backwards.
            return Err(unavailable("admission-authority-busy"));
        }
        Ok(())
    }

    pub(in crate::supply_chain) fn publish(&self, state: &State) -> Result<(), PlatformError> {
        let previous = self.revision.load(Ordering::SeqCst);
        let next = previous
            .checked_add(2)
            .filter(|_| previous & 1 == 0)
            .ok_or_else(|| unavailable("admission-clock-metadata-exhausted"))?;
        self.revision.store(previous + 1, Ordering::SeqCst);
        self.epoch.store(state.floor.epoch, Ordering::SeqCst);
        self.covered_until
            .store(state.floor.restart_not_before, Ordering::SeqCst);
        self.valid_from
            .store(state.policy.identity.valid_from, Ordering::SeqCst);
        self.valid_until
            .store(state.policy.identity.valid_until, Ordering::SeqCst);
        self.revision.store(next, Ordering::SeqCst);
        Ok(())
    }

    pub(super) fn snapshot(&self) -> Result<Snapshot, PlatformError> {
        let revision = self.revision.load(Ordering::SeqCst);
        if revision & 1 != 0 {
            return Err(unavailable("admission-authority-busy"));
        }
        let snapshot = Snapshot {
            revision,
            epoch: self.epoch.load(Ordering::SeqCst),
            covered_until: self.covered_until.load(Ordering::SeqCst),
            valid_from: self.valid_from.load(Ordering::SeqCst),
            valid_until: self.valid_until.load(Ordering::SeqCst),
        };
        self.check_revision(revision)?;
        Ok(snapshot)
    }

    pub(super) fn check_revision(&self, revision: u64) -> Result<(), PlatformError> {
        if self.revision.load(Ordering::SeqCst) != revision {
            return Err(unavailable("admission-authority-busy"));
        }
        Ok(())
    }
}

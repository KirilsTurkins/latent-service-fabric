mod check;
mod proof;
#[cfg(test)]
mod tests;

pub use proof::VerifiedBuildProvenance;

use crate::{
    provenance::evidence::inspect_evidence, BuilderTrust, BuilderTrustStateId,
    PackageSigningSubject, ProvenanceEvidenceRef, ProvenanceLimits, SignatureFailure,
    SignatureResult,
};
use std::{
    fmt,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, Mutex, MutexGuard, TryLockError,
    },
};

/// One bounded builder trust owner. It performs synchronous bounded crypto,
/// without an internal queue, network access or positive verification cache.
///
/// Times must come from a trusted host clock. Its high-water mark survives every
/// failed operation within this instance; durable owners must persist that mark
/// and trust generations before adopting state across process restarts.
pub struct BuilderVerifier {
    limits: ProvenanceLimits,
    state: Mutex<Arc<BuilderTrust>>,
    clock: AtomicU64,
}

impl BuilderVerifier {
    pub fn new(trust: BuilderTrust, limits: ProvenanceLimits, now: u64) -> SignatureResult<Self> {
        limits.validate()?;
        trust.fits(limits)?;
        trust.fresh(now)?;
        Ok(Self {
            limits,
            state: Mutex::new(Arc::new(trust)),
            clock: AtomicU64::new(now),
        })
    }

    pub fn state_id(&self) -> SignatureResult<BuilderTrustStateId> {
        Ok(self.lock()?.state_id().clone())
    }

    /// Highest trusted time observed, including rejected/expired operations.
    #[must_use]
    pub fn clock_floor(&self) -> u64 {
        self.clock.load(Ordering::Acquire)
    }

    /// Verifies exact bytes against one captured current trust state. A concurrent
    /// replacement or clock advance causes failure before the proof is returned.
    /// Publication must still compare the proof's state at its own commit point.
    pub fn verify_package(
        &self,
        expected: &PackageSigningSubject,
        evidence: ProvenanceEvidenceRef<'_>,
        now: u64,
    ) -> SignatureResult<VerifiedBuildProvenance> {
        self.observe(now)?;
        let trust = Arc::clone(&*self.lock()?);
        trust.fresh(now)?;
        let inspected = inspect_evidence(expected, evidence, self.limits)?;
        let proof = check::authenticate(&trust, inspected, self.limits, now)?;
        self.check_captured(&proof, now)?;
        Ok(proof)
    }

    /// Rechecks trust/time only. A consumer must separately match package and
    /// evidence identities and atomically guard its final admission/publication.
    pub fn check_current(&self, proof: &VerifiedBuildProvenance, now: u64) -> SignatureResult<()> {
        self.observe(now)?;
        self.check_captured(proof, now)
    }

    /// Atomically installs explicit fresh operator-approved snapshots. Failed
    /// refreshes never extend prior validity; identical updates do not renew TTLs.
    pub fn replace_trust(
        &self,
        expected: &BuilderTrustStateId,
        next: BuilderTrust,
        now: u64,
    ) -> SignatureResult<BuilderTrustStateId> {
        self.observe(now)?;
        next.fits(self.limits)?;
        next.fresh(now)?;
        let mut current = self.lock()?;
        if current.state_id() != expected {
            return Err(SignatureFailure::TrustConflict.into());
        }
        next.replaces(&current)?;
        if self.clock_floor() > now {
            return Err(SignatureFailure::ClockRegression.into());
        }
        let id = next.state_id().clone();
        if &id != current.state_id() {
            *current = Arc::new(next);
        }
        Ok(id)
    }

    fn observe(&self, now: u64) -> SignatureResult<()> {
        if self.clock.fetch_max(now, Ordering::AcqRel) > now {
            return Err(SignatureFailure::ClockRegression.into());
        }
        Ok(())
    }

    fn check_captured(&self, proof: &VerifiedBuildProvenance, now: u64) -> SignatureResult<()> {
        let current = self.lock()?;
        if current.state_id() != proof.state_id() {
            return Err(SignatureFailure::StaleProof.into());
        }
        current.fresh(now)?;
        if now < proof.verified_at() || now >= proof.valid_until() {
            return Err(SignatureFailure::StaleProof.into());
        }
        if self.clock_floor() > now {
            return Err(SignatureFailure::ClockRegression.into());
        }
        Ok(())
    }

    fn lock(&self) -> SignatureResult<MutexGuard<'_, Arc<BuilderTrust>>> {
        self.state.try_lock().map_err(|error| match error {
            TryLockError::WouldBlock => SignatureFailure::ResourceLimit.into(),
            TryLockError::Poisoned(_) => SignatureFailure::Internal.into(),
        })
    }
}

impl fmt::Debug for BuilderVerifier {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("BuilderVerifier")
            .field("limits", &self.limits)
            .field("clock_floor", &self.clock_floor())
            .finish_non_exhaustive()
    }
}

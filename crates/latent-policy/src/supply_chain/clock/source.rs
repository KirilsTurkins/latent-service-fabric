use super::CoveredClock;
use crate::supply_chain::{denied, unavailable, Inner, SupplyChainAuthority};
use latent_core::PlatformError;
use std::sync::atomic::Ordering;
use std::sync::{Arc, Weak};

/// Read-only projection of the original supply-chain owner. It retains no
/// policy document, grant, verifier, ledger lock or separate clock authority.
/// A successful sample describes a covered clock; it grants no execution,
/// result read, commit, provider retry or lease-renewal authority.
#[derive(Clone)]
pub struct CoveredClockSource {
    owner: Weak<Inner>,
}

impl CoveredClockSource {
    pub(in crate::supply_chain) fn new(owner: &Arc<Inner>) -> Self {
        Self {
            owner: Arc::downgrade(owner),
        }
    }

    /// Tests the actual original owner identity, not equivalent configuration.
    pub fn is_from_authority(&self, authority: &SupplyChainAuthority) -> bool {
        self.owner.ptr_eq(&Arc::downgrade(&authority.inner))
    }

    /// Samples the exact original trusted clock once, without filesystem I/O,
    /// lease renewal, callbacks into a policy/lifecycle owner, or reacquiring
    /// the admission mutex. Concurrent metadata publication fails this bounded
    /// observation only; it supplies no cached positive coverage.
    pub fn sample(&self) -> Result<CoveredClock, PlatformError> {
        let owner = self
            .owner
            .upgrade()
            .ok_or_else(|| unavailable("admission-owner-retired"))?;
        check_owner(&owner)?;
        let accepted = owner.clock_metadata.snapshot()?;
        let previous = owner.clock_metadata.observed_at();
        let now_seconds = owner.clock.now()?;
        // Do not mistake a stale pre-renewal ceiling for an uncovered lease.
        // A replaced snapshot is transient, even if its old ceiling expired.
        owner.clock_metadata.check_revision(accepted.revision)?;
        check_owner(&owner)?;
        let checked = if now_seconds < previous {
            Err(unavailable("admission-clock-regression"))
        } else if now_seconds >= accepted.covered_until {
            Err(unavailable("admission-clock-lease-uncovered"))
        } else if now_seconds < accepted.valid_from || now_seconds >= accepted.valid_until {
            Err(denied("admission-policy-expired"))
        } else {
            owner.clock_metadata.record_current(now_seconds)
        };
        owner.clock_metadata.check_revision(accepted.revision)?;
        check_owner(&owner)?;
        checked?;
        Ok(CoveredClock {
            now_seconds,
            authority_epoch: accepted.epoch,
            covered_until_seconds: accepted.covered_until,
        })
    }
}

fn check_owner(owner: &Inner) -> Result<(), PlatformError> {
    if owner.retired.load(Ordering::Acquire) {
        return Err(unavailable("admission-owner-retired"));
    }
    if owner.halted.load(Ordering::Acquire) {
        return Err(unavailable("admission-durability-uncertain"));
    }
    if owner.state.is_poisoned()
        || owner.reader_poisoned.load(Ordering::Acquire)
        || owner.commit_fence.is_poisoned()
    {
        return Err(unavailable("admission-authority-poisoned"));
    }
    Ok(())
}

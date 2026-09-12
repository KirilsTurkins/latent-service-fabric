//! Node-owned package admission and durable policy/time floors.
//!
//! Uploaded bytes and historical receipts never construct executable authority.
//! All verifiers are private to the same nonblocking currentness fence.

mod clock;
mod config;
mod grant;
mod json;
mod ledger;
mod receipt;
#[cfg(test)]
mod tests;
mod verify;

pub use clock::{SupplyChainClock, SystemSupplyChainClock};
pub use config::SupplyChainPolicy;

use latent_artifacts::{
    AdmissionAuthority, AdmissionBinding, PackageAdmissionUpload, VerifiedAdmission,
};
use latent_core::{PlatformError, PlatformErrorCode, TenantId};
use latent_signing::{BuilderVerifier, PublisherVerifier};
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};

use ledger::{DurableFloor, Ledger};

/// One shared host owner. Verification has exactly one slot and no waiting queue
/// or independently retained positive cache. Catalog grants are charged by their
/// catalog owner and rechecked against this live state on every reuse.
pub struct SupplyChainAuthority {
    inner: Arc<Inner>,
}

struct Inner {
    clock: Arc<dyn SupplyChainClock>,
    state: Mutex<State>,
    retired: AtomicBool,
}
struct State {
    policy: SupplyChainPolicy,
    publisher: PublisherVerifier,
    builder: BuilderVerifier,
    ledger: Ledger,
    floor: DurableFloor,
    observed_at: u64,
    lease_seconds: u64,
    halted: bool,
}

impl SupplyChainAuthority {
    /// Opens the single durable authority owner. Restarts before the previous
    /// future clock ceiling fail closed; the configured lease is 1..=5 seconds.
    pub fn open(
        root: &Path,
        policy: SupplyChainPolicy,
        clock: Arc<dyn SupplyChainClock>,
        lease_seconds: u64,
    ) -> Result<Self, PlatformError> {
        if !(1..=5).contains(&lease_seconds) {
            return Err(invalid("admission-clock-lease-limit"));
        }
        let now = clock.now()?;
        let ledger = Ledger::open(root)?;
        let previous = ledger.read()?;
        if let Some(previous) = &previous {
            previous.check_policy(&policy.identity)?;
            if now < previous.restart_not_before {
                return Err(unavailable("admission-restart-clock-floor"));
            }
        }
        let epoch = previous
            .as_ref()
            .map_or(Some(1), |floor| floor.epoch.checked_add(1))
            .ok_or_else(|| unavailable("admission-epoch-exhausted"))?;
        let (publisher, builder) = policy.verifiers(now)?;
        let ceiling = now
            .checked_add(lease_seconds)
            .ok_or_else(|| invalid("admission-clock-overflow"))?;
        let floor = DurableFloor::new(&policy.identity, epoch, ceiling);
        ledger.persist(&floor)?;
        let after = clock.now()?;
        if after < now || after >= ceiling {
            return Err(unavailable("admission-clock-lease-uncovered"));
        }
        Ok(Self {
            inner: Arc::new(Inner {
                clock,
                retired: AtomicBool::new(false),
                state: Mutex::new(State {
                    policy,
                    publisher,
                    builder,
                    ledger,
                    floor,
                    observed_at: after,
                    lease_seconds,
                    halted: false,
                }),
            }),
        })
    }

    /// Permanently retires this node incarnation. Retained caches/factories and
    /// in-flight control work cannot turn it back into an accepting owner.
    /// This control operation waits for the existing fence before releasing
    /// durable ownership. Never call it from inside a fenced commit callback.
    pub fn retire(&self) {
        self.inner.retired.store(true, Ordering::Release);
        // Old positive grants may retain Inner, but not the OS ownership lock.
        // Finish any previously fenced filesystem write before a new owner can
        // open the same root; retired grants remain permanently inert.
        let mut state = self
            .inner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.ledger.retire();
    }

    /// Called by the existing bounded control owner, never an invocation. A
    /// busy fence skips this attempt; no tasks, waiters or timers are allocated.
    pub fn renew_clock_lease(&self) -> Result<(), PlatformError> {
        let mut state = self.inner.lock()?;
        self.renew(&mut state)
    }
    fn renew(&self, state: &mut State) -> Result<(), PlatformError> {
        if self.inner.retired.load(Ordering::Acquire) {
            return Err(unavailable("admission-owner-retired"));
        }
        if state.halted {
            return Err(unavailable("admission-durability-uncertain"));
        }
        let now = self.inner.clock.now()?;
        if now < state.observed_at {
            return Err(unavailable("admission-clock-regression"));
        }
        // Keep at least two seconds of margin with the default lease, avoiding
        // filesystem work on every control tick. Short leases renew each second.
        let margin = state.lease_seconds.min(2);
        if now
            .checked_add(margin)
            .is_some_and(|until| until < state.floor.restart_not_before)
        {
            state.observed_at = now;
            return Ok(());
        }
        let ceiling = now
            .checked_add(state.lease_seconds)
            .ok_or_else(|| invalid("admission-clock-overflow"))?;
        let mut next = state.floor.clone();
        next.restart_not_before = ceiling;
        state.persist(next)?;
        // The new durable ceiling covers this observation even if the next
        // clock read fails or regresses. Never forget time already observed.
        state.observed_at = now;
        let after = self.inner.clock.now()?;
        if after < now || after >= ceiling {
            return Err(unavailable("admission-clock-lease-uncovered"));
        }
        state.observed_at = after;
        Ok(())
    }

    /// Replaces one complete approved snapshot bundle. All component generation
    /// floors are checked and persisted before either verifier becomes visible.
    pub fn replace_policy(&self, next: SupplyChainPolicy) -> Result<(), PlatformError> {
        let mut state = self.inner.lock()?;
        let now = self.inner.sample_clock(&mut state)?;
        state.floor.check_policy(&next.identity)?;
        next.verifiers(now)?;
        if state.policy.identity == next.identity {
            return Ok(());
        }
        let epoch = state
            .floor
            .epoch
            .checked_add(1)
            .ok_or_else(|| unavailable("admission-epoch-exhausted"))?;
        let floor = DurableFloor::new(&next.identity, epoch, state.floor.restart_not_before);
        state.persist(floor)?;
        // The durable floor is already advanced. Any subsequent problem closes
        // the old authority too; it cannot resume behind that new floor.
        state.halted = true;
        let after = self.inner.clock.now()?;
        if after < now || after >= state.floor.restart_not_before {
            return Err(unavailable("admission-clock-lease-uncovered"));
        }
        let (publisher, builder) = next.verifiers(after)?;
        state.policy = next;
        state.publisher = publisher;
        state.builder = builder;
        state.observed_at = after;
        state.halted = false;
        Ok(())
    }
}

impl Drop for SupplyChainAuthority {
    fn drop(&mut self) {
        self.retire();
    }
}

impl AdmissionAuthority for SupplyChainAuthority {
    fn verify(
        &self,
        tenant: &TenantId,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        verify::verify(&self.inner, tenant, upload, None)
    }
    fn recover(
        &self,
        binding: &AdmissionBinding,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        // Recovery is an explicit synchronous control operation. It may cover
        // the clock lease while scanning; preparation/invocation never renew it.
        let mut state = self
            .inner
            .state
            .lock()
            .map_err(|_| unavailable("admission-authority-poisoned"))?;
        // Structural recovery shares the single verification slot and precedes
        // any current clock/policy denial that may retain historical metadata.
        let upload = receipt::Receipt::validate_retained(binding, upload)?;
        self.renew(&mut state)?;
        verify::with_state(
            &self.inner,
            &binding.tenant,
            upload,
            Some(binding),
            &mut state,
        )
    }
}

impl Inner {
    fn lock(&self) -> Result<MutexGuard<'_, State>, PlatformError> {
        if self.retired.load(Ordering::Acquire) {
            return Err(unavailable("admission-owner-retired"));
        }
        self.state
            .try_lock()
            .map_err(|_| unavailable("admission-authority-busy"))
    }
    fn sample(&self, state: &mut State) -> Result<u64, PlatformError> {
        let now = self.sample_clock(state)?;
        state.policy.fresh(now)?;
        Ok(now)
    }
    fn sample_clock(&self, state: &mut State) -> Result<u64, PlatformError> {
        if self.retired.load(Ordering::Acquire) {
            return Err(unavailable("admission-owner-retired"));
        }
        if state.halted {
            return Err(unavailable("admission-durability-uncertain"));
        }
        let now = self.clock.now()?;
        if now < state.observed_at {
            return Err(unavailable("admission-clock-regression"));
        }
        if now >= state.floor.restart_not_before {
            return Err(unavailable("admission-clock-lease-uncovered"));
        }
        state.observed_at = now;
        Ok(now)
    }
}
impl State {
    fn persist(&mut self, next: DurableFloor) -> Result<(), PlatformError> {
        if let Err(error) = self.ledger.persist(&next) {
            self.halted = true;
            return Err(error);
        }
        self.floor = next;
        Ok(())
    }
}

fn error(code: PlatformErrorCode, message: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: code == PlatformErrorCode::Unavailable,
        details: Vec::new(),
    }
}
fn invalid(message: &'static str) -> PlatformError {
    error(PlatformErrorCode::InvalidArgument, message)
}
fn unavailable(message: &'static str) -> PlatformError {
    error(PlatformErrorCode::Unavailable, message)
}
fn denied(message: &'static str) -> PlatformError {
    error(PlatformErrorCode::PermissionDenied, message)
}

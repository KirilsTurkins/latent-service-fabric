//! Node-owned package admission and durable policy/time floors.
//!
//! Uploaded bytes and historical receipts never construct executable authority.
//! All verifiers are private to the same nonblocking currentness fence.

mod clock;
mod config;
mod grant;
pub(crate) mod json;
mod ledger;
mod receipt;
#[cfg(test)]
mod tests;
mod verification;
mod verify;
mod web;
pub use verification::{
    verify_package_once, verify_web_package_once, PackageVerificationReport,
    PackageVerificationRequest, WebPackageVerificationReport,
};

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
    runtime: Option<Arc<latent_manifest::RuntimeCompatibilityProfile>>,
    state: Mutex<State>,
    // Durable control operations acquire ledger before state. Grant checkpoints
    // acquire only state and never wait for the filesystem owner.
    ledger: Mutex<Ledger>,
    halted: AtomicBool,
    retired: AtomicBool,
    verifying: AtomicBool,
}

struct VerificationPermit<'owner>(&'owner AtomicBool);

impl Drop for VerificationPermit<'_> {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Release);
    }
}
struct State {
    policy: SupplyChainPolicy,
    verifiers: Option<(PublisherVerifier, BuilderVerifier)>,
    floor: DurableFloor,
    observed_at: u64,
    lease_seconds: u64,
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
        Self::open_inner(root, policy, clock, lease_seconds, None)
    }

    /// Opens with the same immutable, detected host profile used for deployment
    /// and preparation. A receipt never substitutes for current host suitability.
    pub fn open_with_runtime(
        root: &Path,
        policy: SupplyChainPolicy,
        clock: Arc<dyn SupplyChainClock>,
        lease_seconds: u64,
        runtime: Arc<latent_manifest::RuntimeCompatibilityProfile>,
    ) -> Result<Self, PlatformError> {
        Self::open_inner(root, policy, clock, lease_seconds, Some(runtime))
    }

    fn open_inner(
        root: &Path,
        policy: SupplyChainPolicy,
        clock: Arc<dyn SupplyChainClock>,
        lease_seconds: u64,
        runtime: Option<Arc<latent_manifest::RuntimeCompatibilityProfile>>,
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
        // Structurally valid but currently expired/offline policy may restore
        // negative catalog history and management. It creates no verifier/grant.
        let verifiers = match policy.verifiers(now) {
            Ok(verifiers) => Some(verifiers),
            Err(failure) if failure.code == PlatformErrorCode::PermissionDenied => None,
            Err(failure) => return Err(failure),
        };
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
                runtime,
                retired: AtomicBool::new(false),
                verifying: AtomicBool::new(false),
                ledger: Mutex::new(ledger),
                halted: AtomicBool::new(false),
                state: Mutex::new(State {
                    policy,
                    verifiers,
                    floor,
                    observed_at: after,
                    lease_seconds,
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
        let mut ledger = self
            .inner
            .ledger
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let _state = self
            .inner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        ledger.retire();
    }

    /// Called by the existing bounded control owner, never an invocation. A
    /// busy owner or currentness fence skips entry. After persistence, only the
    /// control owner waits to publish the new floor under the currentness fence.
    pub fn renew_clock_lease(&self) -> Result<(), PlatformError> {
        let ledger = self.inner.ledger.try_lock().map_err(|error| match error {
            std::sync::TryLockError::WouldBlock => unavailable("admission-control-busy"),
            std::sync::TryLockError::Poisoned(_) => unavailable("admission-authority-poisoned"),
        })?;
        self.renew_unfenced(&ledger, false)
    }
    fn renewal(
        &self,
        state: &mut State,
        full_window: bool,
    ) -> Result<Option<DurableFloor>, PlatformError> {
        if self.inner.retired.load(Ordering::Acquire) {
            return Err(unavailable("admission-owner-retired"));
        }
        if self.inner.halted.load(Ordering::Acquire) {
            return Err(unavailable("admission-durability-uncertain"));
        }
        let now = self.inner.clock.now()?;
        if now < state.observed_at {
            return Err(unavailable("admission-clock-regression"));
        }
        // Keep at least two seconds of margin with the default lease, avoiding
        // filesystem work on every control tick. Short leases renew each second.
        let margin = state.lease_seconds.min(2);
        if !full_window
            && now
                .checked_add(margin)
                .is_some_and(|until| until < state.floor.restart_not_before)
        {
            state.observed_at = now;
            return Ok(None);
        }
        let ceiling = now
            .checked_add(state.lease_seconds)
            .ok_or_else(|| invalid("admission-clock-overflow"))?;
        let mut next = state.floor.clone();
        next.restart_not_before = ceiling;
        // Keep this observation even if persistence or a later sample fails.
        state.observed_at = now;
        Ok(Some(next))
    }
    fn finish_renewal(&self, state: &mut State, next: DurableFloor) -> Result<(), PlatformError> {
        let ceiling = next.restart_not_before;
        state.floor = next;
        if self.inner.retired.load(Ordering::Acquire) {
            return Err(unavailable("admission-owner-retired"));
        }
        let after = self.inner.clock.now()?;
        if after < state.observed_at || after >= ceiling {
            return Err(unavailable("admission-clock-lease-uncovered"));
        }
        state.observed_at = after;
        Ok(())
    }
    fn renew(&self, state: &mut State, ledger: &Ledger) -> Result<(), PlatformError> {
        if let Some(next) = self.renewal(state, false)? {
            self.inner.persist(ledger, &next)?;
            self.finish_renewal(state, next)?;
        }
        Ok(())
    }
    fn renew_unfenced(&self, ledger: &Ledger, full_window: bool) -> Result<(), PlatformError> {
        let next = self.renewal(&mut *self.inner.lock()?, full_window)?;
        let Some(next) = next else {
            return Ok(());
        };
        // The single ledger owner excludes replacement, recovery and retirement.
        // Existing grants keep their old durable ceiling while this append does
        // filesystem I/O. No future ceiling is visible before persistence ends.
        self.inner.persist(ledger, &next)?;
        let mut state = self
            .inner
            .state
            .lock()
            .map_err(|_| unavailable("admission-authority-poisoned"))?;
        self.finish_renewal(&mut state, next)
    }

    /// Replaces one complete approved snapshot bundle. All component generation
    /// floors are checked and persisted before either verifier becomes visible.
    pub fn replace_policy(&self, next: SupplyChainPolicy) -> Result<(), PlatformError> {
        let ledger = self
            .inner
            .ledger
            .try_lock()
            .map_err(|_| unavailable("admission-control-busy"))?;
        let mut state = self.inner.lock()?;
        let now = self.inner.sample_clock(&mut state)?;
        state.floor.check_policy(&next.identity)?;
        next.verifiers(now)?;
        if state.policy.identity == next.identity && state.verifiers.is_some() {
            return Ok(());
        }
        let epoch = state
            .floor
            .epoch
            .checked_add(1)
            .ok_or_else(|| unavailable("admission-epoch-exhausted"))?;
        let floor = DurableFloor::new(&next.identity, epoch, state.floor.restart_not_before);
        self.inner.persist(&ledger, &floor)?;
        state.floor = floor;
        // The durable floor is already advanced. Any subsequent problem closes
        // the old authority too; it cannot resume behind that new floor.
        self.inner.halted.store(true, Ordering::Release);
        let after = self.inner.clock.now()?;
        if after < now || after >= state.floor.restart_not_before {
            return Err(unavailable("admission-clock-lease-uncovered"));
        }
        let verifiers = next.verifiers(after)?;
        state.policy = next;
        state.verifiers = Some(verifiers);
        state.observed_at = after;
        self.inner.halted.store(false, Ordering::Release);
        Ok(())
    }
}

impl Drop for SupplyChainAuthority {
    fn drop(&mut self) {
        self.retire();
    }
}

impl AdmissionAuthority for SupplyChainAuthority {
    fn renew_control_lease(&self) -> Result<(), PlatformError> {
        // Detect a nested currentness fence before waiting for a ledger owner
        // which may itself be finishing against that fence.
        drop(self.inner.lock()?);
        let ledger = self
            .inner
            .ledger
            .lock()
            .map_err(|_| unavailable("admission-authority-poisoned"))?;
        // A mutation can occupy the control worker longer than the sampler's
        // two-second margin. Start its work with a complete configured window,
        // not merely a currently covered (but almost expired) sampler lease.
        // The maximum window, persistence-before-use and all grant fences stay
        // unchanged; this never retries the caller's mutation.
        self.renew_unfenced(&ledger, true)
    }

    fn verify_web(
        &self,
        tenant: &TenantId,
        upload: PackageAdmissionUpload,
    ) -> Result<latent_artifacts::web::VerifiedWebAdmission, PlatformError> {
        let _verification = self.inner.verification()?;
        {
            let mut state = self.inner.lock()?;
            self.inner.sample(&mut state)?;
            web::check_tenant(tenant, &state)?;
        }
        let prepared = web::prepare(upload)?;
        let ledger = self
            .inner
            .ledger
            .lock()
            .map_err(|_| unavailable("admission-authority-poisoned"))?;
        let mut state = self.inner.lock()?;
        self.renew(&mut state, &ledger)?;
        web::with_state(&self.inner, tenant, prepared, None, &mut state)
    }

    fn recover_web(
        &self,
        binding: &latent_artifacts::web::WebAdmissionBinding,
        upload: PackageAdmissionUpload,
    ) -> Result<latent_artifacts::web::VerifiedWebAdmission, PlatformError> {
        let _verification = self.inner.verification()?;
        let upload = web::validate_retained(binding, upload)?;
        let prepared = web::prepare(upload)?;
        let ledger = self
            .inner
            .ledger
            .lock()
            .map_err(|_| unavailable("admission-authority-poisoned"))?;
        let mut state = self
            .inner
            .state
            .lock()
            .map_err(|_| unavailable("admission-authority-poisoned"))?;
        self.renew(&mut state, &ledger)?;
        web::with_state(
            &self.inner,
            &binding.tenant,
            prepared,
            Some(binding),
            &mut state,
        )
    }

    fn verify(
        &self,
        tenant: &TenantId,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        verify::verify(self, tenant, upload)
    }
    fn recover(
        &self,
        binding: &AdmissionBinding,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        let _verification = self.inner.verification()?;
        // Recovery is an explicit synchronous control operation. It may cover
        // the clock lease while scanning; preparation/invocation never renew it.
        // Structural history is checked under the single verification owner,
        // outside the currentness fence, before any policy/clock denial that may
        // retain non-authorizing historical metadata (as for web recovery).
        let upload = receipt::Receipt::validate_retained(binding, upload)?;
        let prepared = verify::prepare(upload)?;
        let ledger = self
            .inner
            .ledger
            .lock()
            .map_err(|_| unavailable("admission-authority-poisoned"))?;
        let mut state = self
            .inner
            .state
            .lock()
            .map_err(|_| unavailable("admission-authority-poisoned"))?;
        self.renew(&mut state, &ledger)?;
        verify::with_state(
            &self.inner,
            &binding.tenant,
            prepared,
            Some(binding),
            &mut state,
        )
    }
}

impl Inner {
    fn verification(&self) -> Result<VerificationPermit<'_>, PlatformError> {
        if self.retired.load(Ordering::Acquire) {
            return Err(unavailable("admission-owner-retired"));
        }
        self.verifying
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| unavailable("admission-verification-busy"))?;
        Ok(VerificationPermit(&self.verifying))
    }

    fn lock(&self) -> Result<MutexGuard<'_, State>, PlatformError> {
        if self.retired.load(Ordering::Acquire) {
            return Err(unavailable("admission-owner-retired"));
        }
        match self.state.try_lock() {
            Ok(state) => Ok(state),
            Err(std::sync::TryLockError::WouldBlock) => {
                Err(unavailable("admission-authority-busy"))
            }
            Err(std::sync::TryLockError::Poisoned(_)) => {
                Err(unavailable("admission-authority-poisoned"))
            }
        }
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
        if self.halted.load(Ordering::Acquire) {
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
    fn persist(&self, ledger: &Ledger, next: &DurableFloor) -> Result<(), PlatformError> {
        if let Err(error) = ledger.persist(next) {
            // Readers can still own the currentness fence. Publish uncertainty
            // immediately so their next checkpoint cannot reuse an old grant.
            self.halted.store(true, Ordering::Release);
            return Err(error);
        }
        Ok(())
    }
}
impl State {
    fn verifiers(&self) -> Result<&(PublisherVerifier, BuilderVerifier), PlatformError> {
        self.verifiers
            .as_ref()
            .ok_or_else(|| denied("admission-trust-unavailable"))
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
    let mut failure = error(PlatformErrorCode::Unavailable, message);
    if latent_core::error::ADMISSION_CURRENTNESS_REASONS.contains(&message) {
        failure.details.push(latent_core::ErrorDetail {
            kind: "admission.currentness".into(),
            fields: [("reason".into(), message.into())].into(),
        });
    }
    failure
}
fn denied(message: &'static str) -> PlatformError {
    error(PlatformErrorCode::PermissionDenied, message)
}

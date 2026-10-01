use super::{
    check_time, current_ceiling, Arc, AuthorityError, DispatchCeiling, DispatchContext,
    DispatchProfile, DurableEffectAuthority, Duration, EffectScope, EffectTime, Instant, Owner,
};
use std::sync::atomic::{AtomicBool, Ordering};

/// Sealed, owned delegation to one reviewed adapter acceptance. Contains only
/// bounded current metadata; the fixed worker retains the affine physical
/// `DispatchContext` until the accepted provider operation actually retires.
pub struct DispatchGrant {
    pub(super) owner: Arc<Owner>,
    pub(super) live: Arc<AtomicBool>,
    pub(super) scope: EffectScope,
    pub(super) profile: DispatchProfile,
    pub(super) effect: String,
    pub(super) payload_digest: String,
    pub(super) payload_bytes: u64,
    pub(super) committed_at_millis: u64,
    pub(super) expires_at_millis: u64,
    pub(super) attempt: u32,
    pub(super) ceiling: DispatchCeiling,
    pub(super) credential_epoch: u64,
    pub(super) reference: String,
    pub(super) deadline: Instant,
    pub(super) lookup: Option<Arc<dyn super::ProviderLookupAuthorization>>,
    // Drop after every grant description. Actual provider cleanup retains this
    // same original owner through DeferredRequest; this creates no admission.
    pub(super) _retained_owner: Option<Arc<dyn std::any::Any + Send + Sync>>,
}

impl DispatchGrant {
    /// Recheck the same sealed effect owner immediately before protocol I/O,
    /// after any awaited DNS/TLS/qualification work. This metadata-only fence
    /// neither admits a new attempt nor refreshes the original physical lease,
    /// ceiling or deadline. Call outside `accept_with`'s held acceptance fence.
    /// The provider request must also check its original installed epoch.
    pub fn check_current(&self, time: EffectTime) -> Result<(), AuthorityError> {
        if self.lookup.is_some() {
            return super::lookup::check_current(self, time);
        }
        let mut state = self
            .owner
            .state
            .lock()
            .map_err(|_| AuthorityError::Unavailable)?;
        if !self.live.load(Ordering::Acquire) {
            return Err(AuthorityError::Stale);
        }
        check_time(&mut state, time)?;
        let rule = state
            .rules
            .get(&self.scope)
            .filter(|rule| rule.enabled)
            .ok_or(AuthorityError::PolicyBlocked)?;
        if rule.profile != self.profile {
            return Err(AuthorityError::UnsupportedFormat);
        }
        if rule.credential_epoch != self.credential_epoch
            || rule.protected_credential_reference != self.reference
        {
            return Err(AuthorityError::PolicyBlocked);
        }
        if self.ceiling.intersection(rule.ceiling) != self.ceiling {
            return Err(AuthorityError::Capacity);
        }
        let expiry = self
            .committed_at_millis
            .checked_add(self.ceiling.maximum_age_millis)
            .ok_or(AuthorityError::Invalid)?
            .min(self.expires_at_millis);
        if time.unix_millis < self.committed_at_millis {
            return Err(AuthorityError::ClockDiscontinuity);
        }
        if time.unix_millis >= expiry || Instant::now() >= self.deadline {
            return Err(AuthorityError::Expired);
        }
        Ok(())
    }

    #[must_use]
    pub fn purpose(&self) -> super::DispatchPurpose {
        if self.lookup.is_some() {
            super::DispatchPurpose::ReconcileOnly
        } else {
            super::DispatchPurpose::Execute
        }
    }

    /// Every mutating provider adapter checks this before accepting or
    /// allocating a request. Fresh operator lookup cannot become send authority.
    pub fn require_execution(&self) -> Result<(), AuthorityError> {
        if self.purpose() == super::DispatchPurpose::Execute {
            Ok(())
        } else {
            Err(AuthorityError::PolicyBlocked)
        }
    }

    #[must_use]
    pub fn scope(&self) -> &EffectScope {
        &self.scope
    }

    #[must_use]
    pub fn profile(&self) -> &DispatchProfile {
        &self.profile
    }

    #[must_use]
    pub fn effect(&self) -> &str {
        &self.effect
    }

    #[must_use]
    pub fn payload_digest(&self) -> &str {
        &self.payload_digest
    }

    #[must_use]
    pub const fn payload_bytes(&self) -> u64 {
        self.payload_bytes
    }

    #[must_use]
    pub const fn committed_at_millis(&self) -> u64 {
        self.committed_at_millis
    }

    #[must_use]
    pub const fn expires_at_millis(&self) -> u64 {
        self.expires_at_millis
    }

    #[must_use]
    pub const fn attempt(&self) -> u32 {
        self.attempt
    }

    #[must_use]
    pub const fn ceiling(&self) -> DispatchCeiling {
        self.ceiling
    }

    #[must_use]
    pub const fn credential_epoch(&self) -> u64 {
        self.credential_epoch
    }

    #[must_use]
    pub fn protected_credential_reference(&self) -> &str {
        &self.reference
    }

    #[must_use]
    pub const fn deadline(&self) -> Instant {
        self.deadline
    }
}

impl DispatchContext {
    /// Linearize reviewed adapter admission with current rule publication.
    /// `accept` is a short synchronous admission callback: no storage, network
    /// or blocking credential lookup under this fence. It returns an owned
    /// provider operation that the fixed worker subsequently drives to physical
    /// retirement. Revalidation never allocates another physical permit or
    /// extends the original deadline; uncertain work is never automatically
    /// authorized for a second attempt here.
    pub fn accept_with<T>(
        &mut self,
        authority: &DurableEffectAuthority,
        attempt: u32,
        time: EffectTime,
        accept: impl FnOnce(DispatchGrant) -> T,
    ) -> Result<T, AuthorityError> {
        if self.lookup.is_some() {
            return super::lookup::accept_with(self, authority, attempt, time, accept);
        }
        if authority.scope != self.scope
            || authority.profile != self.profile
            || authority.link.effect != self.effect
            || attempt != self.attempt
        {
            return Err(AuthorityError::Invalid);
        }
        let owner = Arc::clone(&self.owner);
        let mut state = owner
            .state
            .lock()
            .map_err(|_| AuthorityError::Unavailable)?;
        check_time(&mut state, time)?;
        let (ceiling, expiry) = current_ceiling(&state, authority, time)?;
        let ceiling = self.ceiling.intersection(ceiling);
        if attempt > ceiling.maximum_attempts {
            return Err(AuthorityError::Capacity);
        }
        let now = Instant::now();
        if now >= self.deadline {
            return Err(AuthorityError::Expired);
        }
        let timeout = Duration::from_millis(
            ceiling
                .attempt_timeout_millis
                .min(expiry - time.unix_millis),
        );
        let deadline = now
            .checked_add(timeout)
            .ok_or(AuthorityError::Invalid)?
            .min(self.deadline);
        let rule = state
            .rules
            .get(&self.scope)
            .ok_or(AuthorityError::PolicyBlocked)?;
        self.ceiling = ceiling;
        self.deadline = deadline;
        self.credential_epoch = rule.credential_epoch;
        self.reference
            .clone_from(&rule.protected_credential_reference);
        self.grant_issued = true;
        let result = accept(DispatchGrant {
            owner: Arc::clone(&self.owner),
            live: Arc::clone(&self.live),
            scope: self.scope.clone(),
            profile: self.profile.clone(),
            effect: self.effect.clone(),
            payload_digest: authority.payload_digest.clone(),
            payload_bytes: authority.payload_bytes,
            committed_at_millis: authority.committed_at_millis,
            expires_at_millis: authority.expires_at_millis,
            attempt,
            ceiling,
            credential_epoch: self.credential_epoch,
            reference: self.reference.clone(),
            deadline,
            lookup: None,
            _retained_owner: self.retained_owner.as_ref().map(Arc::clone),
        });
        drop(state);
        Ok(result)
    }
}

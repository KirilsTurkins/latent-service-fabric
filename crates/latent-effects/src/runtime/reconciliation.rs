//! Trusted provider status lookup. These bounded descriptions cannot authorize
//! another send; the installed adapter still requires an original sealed grant.

use crate::authority::{AuthorityError, DurableEffectAuthority};
use crate::dispatch::AttemptIdentity;
use crate::payload::PayloadRecord;

/// Own the actual immutable payload rather than copying it into an operator
/// lookup. The host reads the attempt and version from the same durable view.
pub struct ProviderReconciliationRequest {
    authority: DurableEffectAuthority,
    payload: PayloadRecord,
    attempt: AttemptIdentity,
    record_version: [u8; 32],
}

impl ProviderReconciliationRequest {
    pub fn new(
        authority: DurableEffectAuthority,
        payload: PayloadRecord,
        attempt: AttemptIdentity,
        record_version: [u8; 32],
    ) -> Result<Self, AuthorityError> {
        payload.verify(&authority)?;
        validate_attempt(&attempt)?;
        if attempt.effect() != authority.link().effect
            || attempt.attempt() > authority.ceiling().maximum_attempts
            || record_version == [0; 32]
        {
            return Err(AuthorityError::Invalid);
        }
        Ok(Self {
            authority,
            payload,
            attempt,
            record_version,
        })
    }

    #[must_use]
    pub fn authority(&self) -> &DurableEffectAuthority {
        &self.authority
    }
    #[must_use]
    pub fn payload(&self) -> &PayloadRecord {
        &self.payload
    }
    #[must_use]
    pub fn attempt(&self) -> &AttemptIdentity {
        &self.attempt
    }
    #[must_use]
    pub const fn record_version(&self) -> [u8; 32] {
        self.record_version
    }

    /// Transfer actual payload buffers into the existing protected provider
    /// owner. No cloned application body or replacement request permit is needed.
    #[must_use]
    pub fn into_parts(self) -> (PayloadRecord, AttemptIdentity, [u8; 32]) {
        (self.payload, self.attempt, self.record_version)
    }
}

/// A positive provider fact tied to exactly one original row and attempt. Its
/// constructor is a trusted adapter port, never an operator request field.
/// Persistence additionally checks current management authority and exact CAS.
pub struct ProviderConfirmation {
    attempt: AttemptIdentity,
    record_version: [u8; 32],
    provider_receipt: String,
    observed_at_millis: u64,
}

impl ProviderConfirmation {
    pub fn new(
        attempt: AttemptIdentity,
        record_version: [u8; 32],
        provider_receipt: String,
        observed_at_millis: u64,
    ) -> Result<Self, AuthorityError> {
        validate_attempt(&attempt)?;
        if record_version == [0; 32]
            || provider_receipt.is_empty()
            || provider_receipt.len() > 256
            || provider_receipt.capacity() > 1024
            || provider_receipt.chars().any(char::is_control)
            || observed_at_millis == 0
        {
            return Err(AuthorityError::Invalid);
        }
        Ok(Self {
            attempt,
            record_version,
            provider_receipt,
            observed_at_millis,
        })
    }

    #[must_use]
    pub fn attempt(&self) -> &AttemptIdentity {
        &self.attempt
    }
    #[must_use]
    pub const fn record_version(&self) -> [u8; 32] {
        self.record_version
    }
    #[must_use]
    pub fn provider_receipt(&self) -> &str {
        &self.provider_receipt
    }
    #[must_use]
    pub const fn observed_at_millis(&self) -> u64 {
        self.observed_at_millis
    }

    pub fn validate_for(
        &self,
        attempt: &AttemptIdentity,
        record_version: [u8; 32],
    ) -> Result<(), AuthorityError> {
        if &self.attempt != attempt || self.record_version != record_version {
            return Err(AuthorityError::Stale);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProviderReconciliationReason {
    NotFound,
    Conflict,
    Expired,
    Unavailable,
    Unsupported,
    Ambiguous,
    InvalidResponse,
}

/// Missing/expired/conflicting status remains uncertain. It supplies no absence
/// proof, automatic retry, replacement command, or permission to issue a POST.
pub enum ProviderReconciliationOutcome {
    Confirmed(ProviderConfirmation),
    Uncertain(ProviderReconciliationReason),
}

fn validate_attempt(attempt: &AttemptIdentity) -> Result<(), AuthorityError> {
    crate::effect_identity::parse(attempt.effect())?;
    if attempt.owner_epoch() == 0
        || attempt.claim_generation() == 0
        || !(1..=128).contains(&attempt.attempt())
    {
        return Err(AuthorityError::Invalid);
    }
    Ok(())
}

#[cfg(test)]
mod tests;

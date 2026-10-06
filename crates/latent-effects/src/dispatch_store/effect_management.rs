//! Finite original-operation plans and receipts in the same atomic engine.
//! Plans reserve disposition capacity; they are descriptions, never grants.

mod catalog;
mod codec;
mod validation;

pub use catalog::{
    EffectManagementCatalog, EffectManagementEvidence, PreparedEffectMutation, PreparedEffectPlan,
};

use crate::authority::{AuthorityError, EffectTime};
use crate::dispatch::{AttemptIdentity, Disposition, EffectManagementFact};
use latent_state::embedded::StoreError;
use serde::{Deserialize, Serialize};

pub const PLAN_PREFIX: &[u8] = b"effect-management-plan-v1\0";
pub const RECEIPT_PREFIX: &[u8] = b"effect-management-receipt-v1\0";
pub const COUNTER_PREFIX: &[u8] = b"effect-management-counter-v1\0";
pub const SLOT_PREFIX: &[u8] = b"effect-management-slot-v1\0";
pub const RESERVATION_OWNER_PREFIX: &[u8] = b"effect-management-v1\0";
pub const MAXIMUM_PLAN_BYTES: usize = 16 * 1024;
pub const MAXIMUM_RECEIPT_BYTES: usize = 32 * 1024;
pub const RESERVED_DISPOSITION_BYTES: u64 = 40 * 1024;
pub const MAXIMUM_PLAN_LIFETIME_MILLIS: u64 = 30_000;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum EffectManagementAction {
    Redrive,
    Reconcile,
    Terminate,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum EffectManagementSafety {
    KnownNonexecution,
    QualifiedDeduplication { valid_until_millis: u64 },
    ProviderReceiptLookup,
    AdministratorDeclared,
}

/// The authenticated host supplies actor and caller scope. The original request
/// digest includes the entire current-publication selector and exact requested
/// action/precondition; its bytes do not authorize lookup, plan or mutation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EffectManagementInput {
    pub actor_tenant: String,
    pub actor_subject: String,
    pub namespace: String,
    pub incarnation: u64,
    pub caller_scope: String,
    pub command: String,
    pub command_attempt: u64,
    pub effect: String,
    pub operation_id: String,
    pub action: EffectManagementAction,
    pub expected_version: [u8; 32],
    pub expected_policy_digest: String,
    pub original_request_digest: [u8; 32],
    pub reason: String,
    pub retry_delay_millis: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EffectManagementRequest(EffectManagementInput);

impl EffectManagementRequest {
    pub fn new(input: EffectManagementInput) -> Result<Self, EffectManagementError> {
        let value = Self(input);
        value.validate()?;
        Ok(value)
    }
    #[must_use]
    pub fn input(&self) -> &EffectManagementInput {
        &self.0
    }
    pub(super) fn validate(&self) -> Result<(), EffectManagementError> {
        let input = &self.0;
        for value in [
            &input.actor_tenant,
            &input.actor_subject,
            &input.namespace,
            &input.caller_scope,
            &input.command,
            &input.operation_id,
            &input.expected_policy_digest,
        ] {
            if value.is_empty()
                || value.len() > 256
                || value.capacity() > 1024
                || value.chars().any(char::is_control)
            {
                return Err(EffectManagementError::Invalid);
            }
        }
        crate::effect_identity::parse(&input.effect)?;
        if input.incarnation == 0
            || input.command_attempt == 0
            || input.expected_version == [0; 32]
            || input.original_request_digest == [0; 32]
            || input.reason.is_empty()
            || input.reason.len() > 1024
            || input.reason.capacity() > 4096
            || input.reason.chars().any(char::is_control)
            || match input.action {
                EffectManagementAction::Redrive => {
                    !(1..=60_000).contains(&input.retry_delay_millis)
                }
                _ => input.retry_delay_millis != 0,
            }
        {
            return Err(EffectManagementError::Invalid);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EffectManagementPlan {
    pub(super) request: EffectManagementRequest,
    pub(super) sequence: u32,
    pub(super) original_attempt: Option<AttemptIdentity>,
    pub(super) before: Disposition,
    pub(super) safety: EffectManagementSafety,
    pub(super) prepared_at_millis: u64,
    pub(super) expires_at_millis: u64,
}
impl EffectManagementPlan {
    #[must_use]
    pub fn request(&self) -> &EffectManagementRequest {
        &self.request
    }
    #[must_use]
    pub const fn sequence(&self) -> u32 {
        self.sequence
    }
    #[must_use]
    pub fn original_attempt(&self) -> Option<&AttemptIdentity> {
        self.original_attempt.as_ref()
    }
    #[must_use]
    pub const fn before(&self) -> Disposition {
        self.before
    }
    #[must_use]
    pub const fn safety(&self) -> EffectManagementSafety {
        self.safety
    }
    #[must_use]
    pub const fn prepared_at_millis(&self) -> u64 {
        self.prepared_at_millis
    }
    #[must_use]
    pub const fn expires_at_millis(&self) -> u64 {
        self.expires_at_millis
    }
    pub fn digest(&self) -> Result<[u8; 32], EffectManagementError> {
        Ok(codec::digest(
            b"lsf-effect-management-plan-v1\0",
            &self.encode()?,
        ))
    }
    pub fn encode(&self) -> Result<Vec<u8>, EffectManagementError> {
        self.validate()?;
        codec::encode(b"LEMP\x01", self, MAXIMUM_PLAN_BYTES)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, EffectManagementError> {
        let plan: Self = codec::decode(b"LEMP\x01", bytes, MAXIMUM_PLAN_BYTES)?;
        plan.validate()?;
        Ok(plan)
    }
    pub(super) fn validate(&self) -> Result<(), EffectManagementError> {
        self.request.validate()?;
        if !(1..=128).contains(&self.sequence)
            || self.prepared_at_millis == 0
            || self.expires_at_millis <= self.prepared_at_millis
            || self.expires_at_millis - self.prepared_at_millis > MAXIMUM_PLAN_LIFETIME_MILLIS
            || self.original_attempt.as_ref().is_some_and(|attempt| {
                attempt.effect() != self.request.0.effect
                    || attempt.owner_epoch() == 0
                    || attempt.claim_generation() == 0
                    || !(1..=128).contains(&attempt.attempt())
            })
        {
            return Err(EffectManagementError::Invalid);
        }
        let valid = match (self.request.0.action, self.safety) {
            (EffectManagementAction::Redrive, EffectManagementSafety::KnownNonexecution) => {
                self.before == Disposition::KnownFailed && self.original_attempt.is_some()
            }
            (
                EffectManagementAction::Redrive,
                EffectManagementSafety::QualifiedDeduplication { valid_until_millis },
            ) => {
                matches!(
                    self.before,
                    Disposition::KnownFailed | Disposition::Uncertain
                ) && self.original_attempt.is_some()
                    && valid_until_millis > self.prepared_at_millis
            }
            (EffectManagementAction::Reconcile, EffectManagementSafety::ProviderReceiptLookup) => {
                matches!(
                    self.before,
                    Disposition::Uncertain | Disposition::KnownFailed
                ) && self.original_attempt.is_some()
            }
            (EffectManagementAction::Terminate, EffectManagementSafety::AdministratorDeclared) => {
                self.before != Disposition::Dispatching && !self.before.terminal()
            }
            _ => false,
        };
        if !valid {
            return Err(EffectManagementError::Invalid);
        }
        Ok(())
    }
    pub(super) fn check_time(&self, time: EffectTime) -> Result<(), EffectManagementError> {
        if !time.continuity_proven || time.unix_millis < self.prepared_at_millis {
            return Err(AuthorityError::ClockDiscontinuity.into());
        }
        if time.unix_millis >= self.expires_at_millis {
            return Err(AuthorityError::Expired.into());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EffectManagementReceipt {
    pub(super) plan: EffectManagementPlan,
    pub(super) after: Disposition,
    pub(super) after_version: [u8; 32],
    pub(super) fact: EffectManagementFact,
    pub(super) provider_receipt: Option<String>,
    pub(super) provider_observed_at_millis: Option<u64>,
    pub(super) completed_at_millis: u64,
}
impl EffectManagementReceipt {
    #[must_use]
    pub fn plan(&self) -> &EffectManagementPlan {
        &self.plan
    }
    #[must_use]
    pub const fn after(&self) -> Disposition {
        self.after
    }
    #[must_use]
    pub const fn after_version(&self) -> [u8; 32] {
        self.after_version
    }
    #[must_use]
    pub const fn fact(&self) -> EffectManagementFact {
        self.fact
    }
    #[must_use]
    pub fn provider_receipt(&self) -> Option<&str> {
        self.provider_receipt.as_deref()
    }
    #[must_use]
    pub const fn provider_observed_at_millis(&self) -> Option<u64> {
        self.provider_observed_at_millis
    }
    #[must_use]
    pub const fn completed_at_millis(&self) -> u64 {
        self.completed_at_millis
    }
    pub fn digest(&self) -> Result<[u8; 32], EffectManagementError> {
        Ok(codec::digest(
            b"lsf-effect-management-receipt-v1\0",
            &self.encode()?,
        ))
    }
    pub fn encode(&self) -> Result<Vec<u8>, EffectManagementError> {
        self.validate()?;
        codec::encode(b"LEMR\x01", self, MAXIMUM_RECEIPT_BYTES)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, EffectManagementError> {
        let receipt: Self = codec::decode(b"LEMR\x01", bytes, MAXIMUM_RECEIPT_BYTES)?;
        receipt.validate()?;
        Ok(receipt)
    }
    fn validate(&self) -> Result<(), EffectManagementError> {
        self.plan.validate()?;
        let valid = matches!(
            (self.plan.request.0.action, self.fact, self.after),
            (
                EffectManagementAction::Redrive,
                EffectManagementFact::RedriveScheduled,
                Disposition::RetryScheduled
            ) | (
                EffectManagementAction::Reconcile,
                EffectManagementFact::ProviderConfirmed,
                Disposition::ProviderAcknowledged
            ) | (
                EffectManagementAction::Terminate,
                EffectManagementFact::AdministratorTerminated,
                Disposition::DeadLettered
            )
        );
        if !valid
            || self.after_version == [0; 32]
            || self.completed_at_millis < self.plan.prepared_at_millis
            || self.completed_at_millis >= self.plan.expires_at_millis
            || (self.fact == EffectManagementFact::ProviderConfirmed)
                != self.provider_receipt.is_some()
            || self.provider_receipt.is_some() != self.provider_observed_at_millis.is_some()
            || self
                .provider_observed_at_millis
                .is_some_and(|time| time == 0 || time > self.completed_at_millis)
            || self.provider_receipt.as_ref().is_some_and(|value| {
                value.is_empty()
                    || value.len() > 256
                    || value.capacity() > 1024
                    || value.chars().any(char::is_control)
            })
        {
            return Err(EffectManagementError::Invalid);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EffectManagementError {
    Invalid,
    Conflict,
    Capacity,
    NotFound,
    PermissionDenied,
    PhysicalOwnerLive,
    RestoreReviewRequired,
    Closed,
    RecoveryRequired,
    InvalidAuthorizationFence,
    Store(StoreError),
    Authority(AuthorityError),
}
impl From<StoreError> for EffectManagementError {
    fn from(value: StoreError) -> Self {
        Self::Store(value)
    }
}
impl From<AuthorityError> for EffectManagementError {
    fn from(value: AuthorityError) -> Self {
        Self::Authority(value)
    }
}

#[cfg(test)]
mod tests;

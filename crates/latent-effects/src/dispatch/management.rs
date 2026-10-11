use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use super::{AttemptIdentity, AuthorityError, Disposition, EffectRecord, EffectTime};
use crate::runtime::ProviderConfirmation;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum EffectManagementFact {
    RedriveScheduled,
    ProviderConfirmed,
    AdministratorTerminated,
}

/// Latest management provenance is separate from immutable physical-attempt
/// history. Administrative termination cannot manufacture a provider receipt.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EffectManagementStamp {
    pub(crate) sequence: u32,
    pub(crate) operation_digest: String,
    pub(crate) fact: EffectManagementFact,
    pub(crate) original_attempt: Option<AttemptIdentity>,
    pub(crate) provider_receipt: Option<String>,
    pub(crate) provider_observed_at_millis: Option<u64>,
    pub(crate) observed_at_millis: u64,
}

impl EffectManagementStamp {
    #[must_use]
    pub const fn sequence(&self) -> u32 {
        self.sequence
    }
    #[must_use]
    pub fn operation_digest(&self) -> &str {
        &self.operation_digest
    }
    #[must_use]
    pub const fn fact(&self) -> EffectManagementFact {
        self.fact
    }
    #[must_use]
    pub fn original_attempt(&self) -> Option<&AttemptIdentity> {
        self.original_attempt.as_ref()
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
    pub const fn observed_at_millis(&self) -> u64 {
        self.observed_at_millis
    }

    pub(super) fn validate(&self, record: &EffectRecord) -> Result<(), AuthorityError> {
        crate::effect_identity::parse(&self.operation_digest)?;
        let authority = record.authority()?;
        if !(1..=128).contains(&self.sequence)
            || self.observed_at_millis > record.last_clock_millis
            || self.observed_at_millis < record.authority()?.committed_at_millis()
            || self.original_attempt.as_ref().is_some_and(|attempt| {
                attempt.effect() != authority.link().effect
                    || attempt.attempt() > record.attempt
                    || attempt.owner_epoch() == 0
                    || attempt.claim_generation() == 0
                    || attempt.owner_epoch() > record.owner_epoch
                    || attempt.claim_generation() > record.claim_generation
            })
            || (self.fact == EffectManagementFact::ProviderConfirmed)
                != self.provider_receipt.is_some()
            || self.provider_receipt.is_some() != self.provider_observed_at_millis.is_some()
            || self
                .provider_observed_at_millis
                .is_some_and(|time| time == 0 || time > self.observed_at_millis)
            || self.provider_receipt.as_ref().is_some_and(|receipt| {
                receipt.is_empty() || receipt.len() > 256 || receipt.chars().any(char::is_control)
            })
        {
            return Err(AuthorityError::Invalid);
        }
        match self.fact {
            EffectManagementFact::ProviderConfirmed
                if !record.send_started
                    || self.original_attempt.is_none()
                    || record.disposition != Disposition::ProviderAcknowledged =>
            {
                Err(AuthorityError::Invalid)
            }
            EffectManagementFact::AdministratorTerminated
                if record.disposition != Disposition::DeadLettered =>
            {
                Err(AuthorityError::Invalid)
            }
            _ => Ok(()),
        }
    }
}

impl EffectRecord {
    pub(crate) fn confirm_managed(
        &mut self,
        confirmation: &ProviderConfirmation,
        time: EffectTime,
    ) -> Result<(), AuthorityError> {
        self.check_clock(time)?;
        if !matches!(
            self.disposition,
            Disposition::Uncertain | Disposition::KnownFailed
        ) || !self.send_started
            || confirmation.attempt().effect() != self.authority()?.link().effect
            || confirmation.attempt().attempt() != self.attempt
            || confirmation.observed_at_millis() > time.unix_millis
            || self.latest.as_ref().is_none_or(|receipt| {
                confirmation.observed_at_millis() < receipt.observed_at_millis
            })
        {
            return Err(AuthorityError::Stale);
        }
        self.disposition = Disposition::ProviderAcknowledged;
        Ok(())
    }

    pub(crate) fn terminate_managed(&mut self, time: EffectTime) -> Result<(), AuthorityError> {
        self.check_clock(time)?;
        if self.disposition == Disposition::Dispatching || self.disposition.terminal() {
            return Err(AuthorityError::Stale);
        }
        self.disposition = Disposition::DeadLettered;
        Ok(())
    }

    pub(crate) fn stamp_managed(
        &mut self,
        stamp: EffectManagementStamp,
    ) -> Result<(), AuthorityError> {
        if self
            .management
            .as_ref()
            .is_some_and(|previous| previous.sequence >= stamp.sequence)
        {
            return Err(AuthorityError::Stale);
        }
        stamp.validate(self)?;
        self.management = Some(stamp);
        Ok(())
    }
}

/// Opaque CAS of the exact supported row bytes, including namespace incarnation,
/// immutable payload/authority and management provenance. Decode failure remains
/// a format/storage error; it is never represented as an absent version.
pub fn effect_record_version(bytes: &[u8]) -> Result<[u8; 32], AuthorityError> {
    EffectRecord::decode(bytes)?;
    let mut hash = Sha256::new();
    hash.update(b"lsf-effect-record-version-v1\0");
    hash.update(bytes);
    Ok(hash.finalize().into())
}

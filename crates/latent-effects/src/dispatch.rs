//! Generation-checked durable effect transitions. The selected atomic store
//! applies these transitions under its writer fence, then persists the returned
//! bounded record before the physical provider owner may send. Claim expiry is
//! never evidence that an earlier physical attempt stopped.

use crate::authority::{AuthorityError, DurableEffectAuthority, EffectTime};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Disposition {
    Pending,
    Dispatching,
    ProviderAcknowledged,
    KnownFailed,
    Uncertain,
    RetryScheduled,
    PolicyBlocked,
    Expired,
    DeadLettered,
}

impl Disposition {
    #[must_use]
    pub const fn terminal(self) -> bool {
        matches!(
            self,
            Self::ProviderAcknowledged | Self::Expired | Self::DeadLettered
        )
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AttemptIdentity {
    effect: String,
    owner_epoch: u64,
    claim_generation: u64,
    attempt: u32,
    retry_horizon_millis: Option<u64>,
}

impl AttemptIdentity {
    #[must_use]
    pub const fn owner_epoch(&self) -> u64 {
        self.owner_epoch
    }

    #[must_use]
    pub const fn claim_generation(&self) -> u64 {
        self.claim_generation
    }

    #[must_use]
    pub const fn attempt(&self) -> u32 {
        self.attempt
    }

    #[must_use]
    pub fn effect(&self) -> &str {
        &self.effect
    }

    #[must_use]
    pub const fn retry_horizon_millis(&self) -> Option<u64> {
        self.retry_horizon_millis
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AttemptReceipt {
    pub disposition: Disposition,
    pub reason: String,
    pub provider_receipt: Option<String>,
    pub observed_at_millis: u64,
}

impl AttemptReceipt {
    pub(crate) fn valid(&self) -> bool {
        matches!(
            self.disposition,
            Disposition::ProviderAcknowledged
                | Disposition::KnownFailed
                | Disposition::Uncertain
                | Disposition::PolicyBlocked
                | Disposition::Expired
        ) && self.reason.len() <= 128
            && !self.reason.chars().any(char::is_control)
            && self.provider_receipt.as_ref().is_none_or(|value| {
                !value.is_empty() && value.len() <= 256 && !value.chars().any(char::is_control)
            })
            && (self.disposition == Disposition::ProviderAcknowledged)
                == self.provider_receipt.is_some()
    }
}

/// Persist one compact latest receipt and a history sequence. Actual history
/// rows are separate bounded records/pages, not an ever-growing inline vector.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EffectRecord {
    authority_record: Vec<u8>,
    disposition: Disposition,
    owner_epoch: u64,
    claim_generation: u64,
    attempt: u32,
    send_started: bool,
    retry_at_millis: u64,
    retry_horizon_millis: Option<u64>,
    last_clock_millis: u64,
    history_sequence: u64,
    latest: Option<AttemptReceipt>,
}

impl EffectRecord {
    pub fn committed(authority: &DurableEffectAuthority) -> Result<Self, AuthorityError> {
        Ok(Self {
            authority_record: authority.encode()?,
            disposition: Disposition::Pending,
            owner_epoch: 0,
            claim_generation: 0,
            attempt: 0,
            send_started: false,
            retry_at_millis: 0,
            retry_horizon_millis: None,
            last_clock_millis: authority.committed_at_millis(),
            history_sequence: 0,
            latest: None,
        })
    }

    pub fn authority(&self) -> Result<DurableEffectAuthority, AuthorityError> {
        DurableEffectAuthority::decode(&self.authority_record)
    }

    #[must_use]
    pub const fn disposition(&self) -> Disposition {
        self.disposition
    }

    #[must_use]
    pub const fn attempts(&self) -> u32 {
        self.attempt
    }

    #[must_use]
    pub const fn history_sequence(&self) -> u64 {
        self.history_sequence
    }

    #[must_use]
    pub const fn owner_epoch(&self) -> u64 {
        self.owner_epoch
    }

    #[must_use]
    pub const fn claim_generation(&self) -> u64 {
        self.claim_generation
    }

    #[must_use]
    pub const fn retry_at_millis(&self) -> u64 {
        self.retry_at_millis
    }

    #[must_use]
    pub const fn send_started(&self) -> bool {
        self.send_started
    }

    /// A missing exact decoder or current policy denies an unclaimed intent.
    /// Physical in-flight work and terminal outcomes cannot be overwritten.
    pub fn block_eligible(&mut self, time: EffectTime) -> Result<(), AuthorityError> {
        self.check_clock(time)?;
        if !matches!(
            self.disposition,
            Disposition::Pending | Disposition::RetryScheduled
        ) {
            return Err(AuthorityError::Stale);
        }
        self.disposition = if time.unix_millis >= self.authority()?.expires_at_millis() {
            Disposition::Expired
        } else {
            Disposition::PolicyBlocked
        };
        Ok(())
    }

    #[must_use]
    pub fn latest(&self) -> Option<&AttemptReceipt> {
        self.latest.as_ref()
    }

    /// Only `Pending` or explicitly qualified `RetryScheduled` work is claimable.
    /// The node calls this inside durable CAS; two clones are not two owners.
    pub fn claim(
        &mut self,
        owner_epoch: u64,
        time: EffectTime,
    ) -> Result<AttemptIdentity, AuthorityError> {
        let authority = self.authority()?;
        self.check_clock(time)?;
        if owner_epoch == 0 {
            return Err(AuthorityError::Invalid);
        }
        if time.unix_millis >= authority.expires_at_millis() {
            if self.disposition == Disposition::Dispatching {
                return Err(AuthorityError::Unavailable);
            }
            if self.disposition.terminal() {
                return Err(AuthorityError::Stale);
            }
            self.disposition = Disposition::Expired;
            return Err(AuthorityError::Expired);
        }
        if !matches!(
            self.disposition,
            Disposition::Pending | Disposition::RetryScheduled
        ) || time.unix_millis < self.retry_at_millis
        {
            return Err(AuthorityError::Stale);
        }
        if self
            .retry_horizon_millis
            .is_some_and(|horizon| time.unix_millis >= horizon)
        {
            self.disposition = Disposition::PolicyBlocked;
            return Err(AuthorityError::PolicyBlocked);
        }
        if self.attempt >= authority.ceiling().maximum_attempts {
            self.disposition = Disposition::DeadLettered;
            return Err(AuthorityError::Capacity);
        }
        let generation = self
            .claim_generation
            .checked_add(1)
            .ok_or(AuthorityError::Capacity)?;
        let attempt = self
            .attempt
            .checked_add(1)
            .ok_or(AuthorityError::Capacity)?;
        self.owner_epoch = owner_epoch;
        self.claim_generation = generation;
        self.attempt = attempt;
        self.send_started = false;
        self.disposition = Disposition::Dispatching;
        Ok(AttemptIdentity {
            effect: authority.link().effect.clone(),
            owner_epoch,
            claim_generation: generation,
            attempt,
            retry_horizon_millis: self.retry_horizon_millis,
        })
    }

    /// Persist this marker before the physical send. If its persistence is
    /// uncertain, no send is authorized and durable identity must be recovered.
    pub fn begin_send(&mut self, claim: &AttemptIdentity) -> Result<(), AuthorityError> {
        self.check_claim(claim)?;
        if self.send_started {
            return Err(AuthorityError::Stale);
        }
        self.send_started = true;
        Ok(())
    }

    /// Physical network work has retired before its worker presents a receipt.
    /// A stale worker may not overwrite a replacement attempt or terminal row.
    pub fn complete(
        &mut self,
        claim: &AttemptIdentity,
        receipt: AttemptReceipt,
    ) -> Result<(), AuthorityError> {
        self.check_claim(claim)?;
        if !receipt.valid() {
            return Err(AuthorityError::Invalid);
        }
        if receipt.observed_at_millis < self.last_clock_millis {
            return Err(AuthorityError::ClockDiscontinuity);
        }
        if !self.send_started
            && matches!(
                receipt.disposition,
                Disposition::ProviderAcknowledged | Disposition::Uncertain
            )
        {
            return Err(AuthorityError::Invalid);
        }
        let sequence = self
            .history_sequence
            .checked_add(1)
            .ok_or(AuthorityError::Capacity)?;
        self.last_clock_millis = receipt.observed_at_millis;
        self.disposition = receipt.disposition;
        self.latest = Some(receipt);
        self.history_sequence = sequence;
        Ok(())
    }

    /// This startup operation requires exclusive new-process store ownership,
    /// an advanced epoch, and affirmative old physical-owner retirement. Lease
    /// expiry alone cannot satisfy the supplied proof.
    pub fn recover_interrupted(
        &mut self,
        new_epoch: u64,
        old_process_retired: bool,
        time: EffectTime,
    ) -> Result<(), AuthorityError> {
        self.check_clock(time)?;
        if self.disposition != Disposition::Dispatching {
            return Ok(());
        }
        if !old_process_retired || new_epoch <= self.owner_epoch {
            return Err(AuthorityError::Unavailable);
        }
        let generation = self
            .claim_generation
            .checked_add(1)
            .ok_or(AuthorityError::Capacity)?;
        let sequence = self
            .history_sequence
            .checked_add(1)
            .ok_or(AuthorityError::Capacity)?;
        self.owner_epoch = new_epoch;
        self.claim_generation = generation;
        self.disposition = if self.send_started {
            Disposition::Uncertain
        } else {
            Disposition::KnownFailed
        };
        self.latest = Some(AttemptReceipt {
            disposition: self.disposition,
            reason: if self.send_started {
                "process-lost-after-send-boundary"
            } else {
                "retired-process-before-send-boundary"
            }
            .into(),
            provider_receipt: None,
            observed_at_millis: time.unix_millis,
        });
        self.history_sequence = sequence;
        Ok(())
    }

    /// Concrete adapter qualification supplies the safety proof, not an
    /// idempotency string, timeout or missing remote status response. This is
    /// internal finite effect retry, never guest/command replay.
    pub fn schedule_retry(
        &mut self,
        proof: RetryProof,
        time: EffectTime,
        delay_millis: u64,
    ) -> Result<(), AuthorityError> {
        self.check_clock(time)?;
        let authority = self.authority()?;
        if delay_millis == 0 || delay_millis > 60_000 {
            return Err(AuthorityError::Invalid);
        }
        if !matches!(
            self.disposition,
            Disposition::KnownFailed | Disposition::Uncertain
        ) {
            return Err(AuthorityError::Stale);
        }
        let retry_at = time
            .unix_millis
            .checked_add(delay_millis)
            .ok_or(AuthorityError::Capacity)?;
        let horizon = match proof {
            RetryProof::KnownNonexecution
                if self.disposition == Disposition::KnownFailed && !self.send_started =>
            {
                None
            }
            RetryProof::QualifiedDeduplication {
                valid_until_millis,
                same_payload,
                same_provider_incarnation,
            } if same_payload && same_provider_incarnation && retry_at < valid_until_millis => {
                Some(valid_until_millis)
            }
            _ => return Err(AuthorityError::PolicyBlocked),
        };
        if retry_at >= authority.expires_at_millis() {
            return Err(AuthorityError::Expired);
        }
        self.retry_at_millis = retry_at;
        self.retry_horizon_millis = horizon;
        self.disposition = Disposition::RetryScheduled;
        Ok(())
    }

    pub fn encode(&self) -> Result<Vec<u8>, AuthorityError> {
        self.validate()?;
        let body = serde_json::to_vec(self).map_err(|_| AuthorityError::Invalid)?;
        if body.len() > 65_536 {
            return Err(AuthorityError::Capacity);
        }
        let mut bytes = b"LER\0\x01".to_vec();
        bytes.extend(body);
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, AuthorityError> {
        if bytes.len() > 65_541 {
            return Err(AuthorityError::Capacity);
        }
        if !bytes.starts_with(b"LER\0\x01") {
            return Err(AuthorityError::UnsupportedFormat);
        }
        let record: Self =
            serde_json::from_slice(&bytes[5..]).map_err(|_| AuthorityError::Invalid)?;
        record.validate()?;
        Ok(record)
    }

    fn validate(&self) -> Result<(), AuthorityError> {
        let authority = self.authority()?;
        if self.attempt > authority.ceiling().maximum_attempts
            || self.last_clock_millis < authority.committed_at_millis()
            || self.history_sequence > u64::from(self.attempt)
            || (self.history_sequence == 0) != self.latest.is_none()
            || self.latest.as_ref().is_some_and(|receipt| {
                !receipt.valid() || receipt.observed_at_millis > self.last_clock_millis
            })
            || (self.attempt > 0 && (self.owner_epoch == 0 || self.claim_generation == 0))
            || (self.send_started && self.attempt == 0)
        {
            return Err(AuthorityError::Invalid);
        }
        let has_receipt = |expected| {
            self.latest
                .as_ref()
                .is_some_and(|receipt| receipt.disposition == expected)
        };
        let valid = match self.disposition {
            Disposition::Pending => {
                self.attempt == 0 && !self.send_started && self.latest.is_none()
            }
            Disposition::Dispatching => self.attempt > 0,
            Disposition::ProviderAcknowledged => {
                self.send_started && has_receipt(Disposition::ProviderAcknowledged)
            }
            Disposition::KnownFailed => has_receipt(Disposition::KnownFailed),
            Disposition::Uncertain => self.send_started && has_receipt(Disposition::Uncertain),
            Disposition::RetryScheduled => {
                self.retry_at_millis > 0
                    && (has_receipt(Disposition::KnownFailed)
                        || has_receipt(Disposition::Uncertain))
            }
            Disposition::DeadLettered => {
                self.attempt == authority.ceiling().maximum_attempts
                    && (has_receipt(Disposition::KnownFailed)
                        || has_receipt(Disposition::Uncertain))
            }
            Disposition::PolicyBlocked | Disposition::Expired => true,
        };
        if !valid {
            return Err(AuthorityError::Invalid);
        }
        Ok(())
    }

    fn check_claim(&self, claim: &AttemptIdentity) -> Result<(), AuthorityError> {
        if self.disposition != Disposition::Dispatching
            || claim.effect != self.authority()?.link().effect
            || claim.owner_epoch != self.owner_epoch
            || claim.claim_generation != self.claim_generation
            || claim.attempt != self.attempt
        {
            return Err(AuthorityError::Stale);
        }
        Ok(())
    }

    fn check_clock(&mut self, time: EffectTime) -> Result<(), AuthorityError> {
        if !time.continuity_proven || time.unix_millis < self.last_clock_millis {
            return Err(AuthorityError::ClockDiscontinuity);
        }
        self.last_clock_millis = time.unix_millis;
        Ok(())
    }
}

/// Trusted concrete-adapter/reconciler port. Never accepted from a guest or
/// operator's unvalidated text; the caller supplies measured provider evidence.
#[derive(Debug, Clone, Copy)]
pub enum RetryProof {
    KnownNonexecution,
    QualifiedDeduplication {
        valid_until_millis: u64,
        same_payload: bool,
        same_provider_incarnation: bool,
    },
}

#[cfg(test)]
mod tests;

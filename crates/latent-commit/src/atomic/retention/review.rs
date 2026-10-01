//! Explicit host-reviewed terminalization, separate from provider receipts.
mod clock;
mod operation;
mod plan;
mod purge;
mod release;
mod retired;
mod retry_index;
pub use release::{FloorReleaseRequest, PreparedFloorRelease};
pub use retired::RetiredCommand;
pub(in crate::atomic) use retry_index::{RetryIndex, RETRY_INDEX_PREFIX};

use crate::atomic::{
    codec::{Decoder, Encoder},
    id, AtomicError, CommandRecord, Identity,
};
use latent_core::transaction_contract::CommandKey;

const AUDIT_BYTES: usize = 2048;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RetentionAction {
    Terminalize,
    Purge,
}

/// At most one effect closure advances per physical callback. An unfinished
/// review or purge is durable and never implies that dependencies are released.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RetentionProgress {
    pub command: Identity,
    pub terminalized_effects: u64,
    pub purged_effects: u64,
    pub total_effects: u64,
    pub purged_attempts: u64,
    pub total_attempts: u64,
    pub complete: bool,
}

/// Host-derived authenticated attribution and original, reviewed dependencies.
/// Neither IDs nor request fields install a destructive policy. The callback
/// rechecks the exact original scope and policy at durable acceptance.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RetentionRequest {
    pub key: CommandKey,
    pub expected_command_digest: Identity,
    pub actor: String,
    pub operation_id: String,
    pub policy: String,
    pub retain_until_millis: u64,
    /// Original provider/inbox retention promise, checked by the host callback.
    /// An inbox without an installed original horizon cannot be purged.
    pub inbox_expires_at_millis: Option<u64>,
}
impl RetentionRequest {
    pub fn command_digest(record: &CommandRecord) -> Result<Identity, AtomicError> {
        let mut original = record.clone();
        original.retention_review.clear();
        Ok(Identity::derive(
            b"lsf-retention-command-v1\0",
            &[&original.encode()?],
        ))
    }
    fn validate(&self, record: &CommandRecord, now: u64) -> Result<(), AtomicError> {
        for value in [&self.actor, &self.operation_id, &self.policy] {
            id(value)?;
        }
        if self.key != *record.key()
            || self.expected_command_digest != Self::command_digest(record)?
        {
            return Err(AtomicError::Conflict);
        }
        let maximum = now.checked_add(604_800_000).ok_or(AtomicError::Limit)?;
        if self.retain_until_millis <= now || self.retain_until_millis > maximum {
            return Err(AtomicError::Invalid);
        }
        match (&record.inbox, self.inbox_expires_at_millis) {
            (None, None) => {}
            (Some(_), Some(horizon)) if horizon >= record.admitted_at && horizon <= now => {}
            _ => return Err(AtomicError::UnsupportedFormat),
        }
        Ok(())
    }
}

/// A bounded attributable stop/release review. The original measured effect
/// receipts remain in their original history; this row grants no dispatch.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(in crate::atomic) struct RetentionAudit {
    pub command: Identity,
    pub attempt: u64,
    pub command_digest: Identity,
    pub request_digest: Identity,
    pub actor: String,
    pub operation_id: String,
    pub policy: String,
    pub reviewed_at: u64,
    pub retain_until: u64,
    pub inbox_expires: Option<u64>,
    pub terminalized: u64,
    pub effect_count: u64,
    pub purged: u64,
    pub purged_attempts: u64,
    pub purging: bool,
    pub effect_before_bytes: u64,
    pub effect_after_bytes: u64,
}
impl RetentionAudit {
    pub fn capture(record: &CommandRecord) -> Result<Option<Self>, AtomicError> {
        if record.retention_review.is_empty() {
            Ok(None)
        } else {
            Self::decode(&record.retention_review).map(Some)
        }
    }
    pub fn encode(&self) -> Result<Vec<u8>, AtomicError> {
        self.validate()?;
        let mut out = Encoder::new(b"LRA\0\x01");
        out.identity(self.command);
        out.number(self.attempt);
        out.identity(self.command_digest);
        out.identity(self.request_digest);
        for text in [&self.actor, &self.operation_id, &self.policy] {
            out.text(text)?;
        }
        out.number(self.reviewed_at);
        out.number(self.retain_until);
        out.0.push(u8::from(self.inbox_expires.is_some()));
        if let Some(horizon) = self.inbox_expires {
            out.number(horizon);
        }
        for value in [
            self.terminalized,
            self.effect_count,
            self.purged,
            self.purged_attempts,
            self.effect_before_bytes,
            self.effect_after_bytes,
        ] {
            out.number(value);
        }
        out.0.push(u8::from(self.purging));
        out.finish(AUDIT_BYTES)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, AtomicError> {
        let mut input = Decoder::new(bytes, b"LRA\0\x01", AUDIT_BYTES)?;
        let mut audit = Self {
            command: input.identity()?,
            attempt: input.number()?,
            command_digest: input.identity()?,
            request_digest: input.identity()?,
            actor: input.text(256)?,
            operation_id: input.text(256)?,
            policy: input.text(256)?,
            reviewed_at: input.number()?,
            retain_until: input.number()?,
            inbox_expires: None,
            terminalized: 0,
            effect_count: 0,
            purged: 0,
            purged_attempts: 0,
            purging: false,
            effect_before_bytes: 0,
            effect_after_bytes: 0,
        };
        audit.inbox_expires = match input.byte()? {
            0 => None,
            1 => Some(input.number()?),
            _ => return Err(AtomicError::Corrupt),
        };
        audit.terminalized = input.number()?;
        audit.effect_count = input.number()?;
        audit.purged = input.number()?;
        audit.purged_attempts = input.number()?;
        audit.effect_before_bytes = input.number()?;
        audit.effect_after_bytes = input.number()?;
        audit.purging = match input.byte()? {
            0 => false,
            1 => true,
            _ => return Err(AtomicError::Corrupt),
        };
        input.finish()?;
        audit.validate().map_err(|_| AtomicError::Corrupt)?;
        Ok(audit)
    }
    pub fn verify(&self, record: &CommandRecord) -> Result<(), AtomicError> {
        if self.command != record.id()
            || self.attempt != record.attempt()
            || self.command_digest != RetentionRequest::command_digest(record)?
            || self.reviewed_at != record.clock_floor()
            || self.reviewed_at < record.identity_expires()
            || record.inbox.is_some() != self.inbox_expires.is_some()
            || self.terminalized > record.effects.len() as u64
            || self.effect_count != record.effects.len() as u64
            || (self.purging && self.terminalized != record.effects.len() as u64)
            || self.purged > self.terminalized
            || self.purged_attempts >= record.attempt
        {
            return Err(AtomicError::Corrupt);
        }
        Ok(())
    }
    pub fn matches(&self, request: &RetentionRequest) -> Result<(), AtomicError> {
        if self.request_digest != request.expected_command_digest
            || self.actor != request.actor
            || self.operation_id != request.operation_id
            || self.policy != request.policy
            || self.retain_until != request.retain_until_millis
            || self.inbox_expires != request.inbox_expires_at_millis
        {
            return Err(AtomicError::Conflict);
        }
        Ok(())
    }
    pub fn growth(&self) -> Result<u64, AtomicError> {
        let growth = self
            .effect_after_bytes
            .saturating_sub(self.effect_before_bytes);
        if growth > super::EFFECT_GROWTH_RESERVED_BYTES {
            return Err(AtomicError::Limit);
        }
        Ok(growth)
    }
    pub fn reservation(&self) -> Result<u64, AtomicError> {
        if self.terminalized == self.effect_count {
            return Ok(0);
        }
        super::AUDIT_RESERVED_BYTES
            .checked_sub(self.encode()?.len() as u64 * 2)
            .ok_or(AtomicError::Corrupt)
    }
    pub fn progress(&self, record: &CommandRecord, action: RetentionAction) -> RetentionProgress {
        RetentionProgress {
            command: self.command,
            terminalized_effects: self.terminalized,
            purged_effects: self.purged,
            total_effects: record.effects.len() as u64,
            purged_attempts: self.purged_attempts,
            total_attempts: record.attempt,
            complete: match action {
                RetentionAction::Terminalize => self.terminalized == record.effects.len() as u64,
                RetentionAction::Purge => false,
            },
        }
    }
    fn validate(&self) -> Result<(), AtomicError> {
        for value in [&self.actor, &self.operation_id, &self.policy] {
            id(value)?;
        }
        if self.command == Identity([0; 32])
            || self.command_digest == Identity([0; 32])
            || self.request_digest == Identity([0; 32])
            || !(1..=16).contains(&self.attempt)
            || self.retain_until <= self.reviewed_at
            || self
                .retain_until
                .checked_sub(self.reviewed_at)
                .is_none_or(|age| age > 604_800_000)
            || self
                .inbox_expires
                .is_some_and(|horizon| horizon > self.reviewed_at)
            || self.effect_count > 128
            || self.terminalized > self.effect_count
            || self.purged > self.terminalized
            || self.purged_attempts >= self.attempt
            || (!self.purging && self.purged != 0)
            || (!self.purging && self.purged_attempts != 0)
            || (self.purged_attempts != 0 && self.purged != self.effect_count)
            || self.effect_before_bytes > 128 * 65_541
            || self.effect_after_bytes > 128 * 65_541
        {
            return Err(AtomicError::Invalid);
        }
        self.growth()?;
        Ok(())
    }
}

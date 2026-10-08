//! The sole complete state/result/outbox/inbox envelope. These worker-borrowed
//! ports contain no executor, native view owner, guest heap, network dispatch or
//! application retry. The host supplies current sealed authority at acceptance.

mod captured;
mod codec;
mod ownership;
mod record;
mod validation;
mod writer;
pub use captured::{CapturedIntent, IntentCaptureContext};
pub use ownership::{AttemptRetirement, PhysicalAttemptWork, RetiredAttempt};
pub use record::{
    command_row_key, result_row_key, CommandRecord, DurableResult, InboxIdentity, SourceIdentity,
};
pub use validation::{validate_linked_row, validate_row, validate_view};
pub use writer::{
    inspect, AdmissionDecision, AdmittedCommand, CompleteEnvelope, EnvelopeNamespaceExpectation,
    PreparedAdmission, PreparedDisposition, RetryRequest, StagedIntent,
};

use latent_core::transaction_contract::{self as contract, CommandFingerprint, CommandKey};
use latent_effects::authority::AuthorityError;
use latent_state::{embedded::StoreError, session::StateError};
use sha2::{Digest, Sha256};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AtomicError {
    Invalid,
    Limit,
    Conflict,
    PermissionDenied,
    Expired,
    Corrupt,
    UnsupportedFormat,
    Unavailable,
    RecoveryRequired,
    InProgress,
    NotFound,
}
impl From<StoreError> for AtomicError {
    fn from(error: StoreError) -> Self {
        match error {
            StoreError::Invalid => Self::Invalid,
            StoreError::Capacity => Self::Limit,
            StoreError::Conflict => Self::Conflict,
            StoreError::Corrupt => Self::Corrupt,
            StoreError::UnsupportedFormat => Self::UnsupportedFormat,
            StoreError::Unavailable => Self::Unavailable,
            StoreError::CommitUncertain => Self::RecoveryRequired,
            StoreError::SnapshotExpired => Self::Expired,
        }
    }
}
impl From<StateError> for AtomicError {
    fn from(error: StateError) -> Self {
        match error {
            StateError::Conflict => Self::Conflict,
            StateError::PermissionDenied => Self::PermissionDenied,
            StateError::Corrupt => Self::Corrupt,
            StateError::UnsupportedFormat => Self::UnsupportedFormat,
            StateError::Unavailable => Self::Unavailable,
            StateError::RecoveryRequired => Self::RecoveryRequired,
            StateError::Expired => Self::Expired,
            StateError::Limit => Self::Limit,
            _ => Self::Invalid,
        }
    }
}
impl From<AuthorityError> for AtomicError {
    fn from(error: AuthorityError) -> Self {
        match error {
            AuthorityError::Capacity => Self::Limit,
            AuthorityError::PolicyBlocked => Self::PermissionDenied,
            AuthorityError::UnsupportedFormat => Self::UnsupportedFormat,
            AuthorityError::Expired => Self::Expired,
            AuthorityError::Stale => Self::Conflict,
            AuthorityError::Unavailable => Self::Unavailable,
            AuthorityError::ClockDiscontinuity => Self::RecoveryRequired,
            AuthorityError::Invalid => Self::Invalid,
        }
    }
}

/// Domain-separated SHA-256 identity, never a grant or a dump of business input.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct Identity([u8; 32]);
impl Identity {
    #[must_use]
    pub const fn bytes(self) -> [u8; 32] {
        self.0
    }
    #[must_use]
    pub fn hex(self) -> String {
        const HEX: &[u8; 16] = b"0123456789abcdef";
        let mut text = String::with_capacity(64);
        for byte in self.0 {
            text.push(char::from(HEX[usize::from(byte >> 4)]));
            text.push(char::from(HEX[usize::from(byte & 15)]));
        }
        text
    }
    pub(super) fn derive(domain: &[u8], parts: &[&[u8]]) -> Self {
        let mut hash = Sha256::new();
        hash.update(domain);
        for part in parts {
            hash.update((part.len() as u64).to_le_bytes());
            hash.update(part);
        }
        Self(hash.finalize().into())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReplayPolicy {
    Full,
    ReceiptOnly,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ResultPolicy {
    pub replay: ReplayPolicy,
    pub maximum_result_bytes: usize,
    pub result_millis: u64,
    pub identity_millis: u64,
    pub maximum_attempts: u64,
}
impl ResultPolicy {
    pub fn validate(self) -> Result<(), AtomicError> {
        if self.maximum_result_bytes > contract::VALUE_BYTES
            || self.result_millis == 0
            || self.identity_millis < self.result_millis
            || self.identity_millis > 604_800_000
            || !(1..=16).contains(&self.maximum_attempts)
        {
            return Err(AtomicError::Invalid);
        }
        Ok(())
    }
    pub(super) fn reservation(self) -> Result<u64, AtomicError> {
        self.validate()?;
        let body = match self.replay {
            ReplayPolicy::Full => self.maximum_result_bytes + contract::METADATA_BYTES,
            ReplayPolicy::ReceiptOnly => 0,
        };
        u64::try_from(body + codec::METADATA_BYTES).map_err(|_| AtomicError::Limit)
    }
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Outcome {
    Pending,
    Committed,
    Rejected,
    Aborted,
}
#[derive(Debug, Clone, Copy)]
pub struct CommandTime {
    pub unix_millis: u64,
    pub continuity_proven: bool,
}
impl CommandTime {
    pub(super) fn check(self, floor: u64) -> Result<(), AtomicError> {
        if !self.continuity_proven || self.unix_millis < floor {
            Err(AtomicError::RecoveryRequired)
        } else {
            Ok(())
        }
    }
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CommandAccess {
    Admit,
    Replay,
    FinalClaim,
    FinalDisposition,
}

pub struct AdmissionInput {
    pub key: CommandKey,
    pub fingerprint: CommandFingerprint,
    pub source: SourceIdentity,
    pub result_read_policy: String,
    pub result_policy: ResultPolicy,
    pub inbox: Option<InboxIdentity>,
    pub owner_epoch: u64,
}

pub(super) fn id(value: &str) -> Result<(), AtomicError> {
    contract::identity(value).map_err(|_| AtomicError::Invalid)?;
    if value.chars().any(char::is_control) {
        return Err(AtomicError::Invalid);
    }
    Ok(())
}
pub(super) fn incarnation(key: &CommandKey) -> Result<u64, AtomicError> {
    let value = key
        .incarnation
        .parse::<u64>()
        .map_err(|_| AtomicError::Invalid)?;
    if value == 0 || value.to_string() != key.incarnation {
        return Err(AtomicError::Invalid);
    }
    Ok(value)
}
pub fn command_identity(key: &CommandKey) -> Result<Identity, AtomicError> {
    incarnation(key)?;
    let mut hash = Sha256::new();
    key.visit_identity_bytes(|bytes| hash.update(bytes))
        .map_err(|_| AtomicError::Invalid)?;
    Ok(Identity(hash.finalize().into()))
}
pub fn fingerprint(
    input: &CommandFingerprint,
    inbox: Option<&InboxIdentity>,
) -> Result<Identity, AtomicError> {
    let mut hash = Sha256::new();
    input
        .visit_identity_bytes(|bytes| hash.update(bytes))
        .map_err(|_| AtomicError::Invalid)?;
    hash.update([u8::from(inbox.is_some())]);
    if let Some(inbox) = inbox {
        inbox.validate()?;
        for text in [&inbox.provider, &inbox.binding, &inbox.message] {
            hash.update((text.len() as u64).to_le_bytes());
            hash.update(text.as_bytes());
        }
        hash.update(inbox.payload_digest.0);
    }
    Ok(Identity(hash.finalize().into()))
}

#[cfg(test)]
mod tests;

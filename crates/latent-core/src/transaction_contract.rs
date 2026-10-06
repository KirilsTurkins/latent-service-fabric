//! Bounded Phase 4 value and canonical identity contracts. No engine or authority.

use std::collections::BTreeSet;

pub const PROFILE: &str = "lsf-transaction-v1";
pub const KEY_BYTES: usize = 1024;
pub const VALUE_BYTES: usize = 1024 * 1024;
pub const IDENTITY_BYTES: usize = 256;
pub const VERSION_BYTES: usize = 256;
pub const MEDIA_TYPE_BYTES: usize = 128;
pub const METADATA_PAIRS: usize = 32;
pub const METADATA_BYTES: usize = 8192;
pub const PAGE_ENTRIES: u32 = 128;
pub const PAGE_BYTES: usize = 1024 * 1024;
pub const PRECONDITIONS: usize = 128;
pub const DEFAULT_INTENTS: u32 = 32;
pub const MAX_INTENTS: u32 = 128;
/// One shared ledger covers encoded mutations, intents, command result and inbox.
pub const STAGED_BYTES: usize = 8 * 1024 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ContractError {
    InvalidPresentValue,
    ByteLimit,
    CountLimit,
    Duplicate,
    UnsupportedVersion,
}

/// Absent differs from an empty present value. Length is UTF-8 bytes, not chars.
pub fn identity(value: &str) -> Result<(), ContractError> {
    if value.is_empty() || value.contains('\0') {
        return Err(ContractError::InvalidPresentValue);
    }
    bounded(value.len(), IDENTITY_BYTES)
}

pub fn bounded(length: usize, maximum: usize) -> Result<(), ContractError> {
    if length > maximum {
        Err(ContractError::ByteLimit)
    } else {
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Value {
    pub bytes: Vec<u8>,
    pub media_type: String,
    pub metadata: Vec<(String, String)>,
}

impl Value {
    pub fn validate(&self) -> Result<(), ContractError> {
        bounded(self.bytes.len(), VALUE_BYTES)?;
        if self.media_type.is_empty()
            || !self.media_type.is_ascii()
            || !self
                .media_type
                .bytes()
                .all(|byte| (32..=126).contains(&byte))
        {
            return Err(ContractError::InvalidPresentValue);
        }
        bounded(self.media_type.len(), MEDIA_TYPE_BYTES)?;
        bounded(self.metadata.len(), METADATA_PAIRS).map_err(|_| ContractError::CountLimit)?;
        let mut names = BTreeSet::new();
        let mut bytes = 0_usize;
        for (key, value) in &self.metadata {
            identity(key)?;
            bounded(value.len(), 1024)?;
            if !names.insert(key) {
                return Err(ContractError::Duplicate);
            }
            bytes = bytes
                .checked_add(key.len())
                .and_then(|n| n.checked_add(value.len()))
                .ok_or(ContractError::ByteLimit)?;
        }
        bounded(bytes, METADATA_BYTES)
    }
}

/// Recovery scope is derived/approved by the host. Supplying this record alone
/// grants no read, replay, invoke, shared-scope or management permission.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommandKey {
    pub tenant: String,
    pub namespace: String,
    pub incarnation: String,
    pub recovery_scope: String,
    pub operation: String,
    pub entity: Option<String>,
    pub client_key: String,
}

fn frame(value: &[u8], write: &mut impl FnMut(&[u8])) {
    write(&(value.len() as u64).to_le_bytes());
    write(value);
}

impl CommandKey {
    /// Consumers use SHA-256 over these bytes. Routes, credentials, activation
    /// correlation IDs and revisions do not enter durable business identity.
    pub fn visit_identity_bytes(&self, mut write: impl FnMut(&[u8])) -> Result<(), ContractError> {
        for value in [
            &self.tenant,
            &self.namespace,
            &self.incarnation,
            &self.recovery_scope,
            &self.operation,
            &self.client_key,
        ] {
            identity(value)?;
        }
        if let Some(entity) = &self.entity {
            identity(entity)?;
        }
        write(b"lsf-command-key-v1\0");
        for value in [
            &self.tenant,
            &self.namespace,
            &self.incarnation,
            &self.recovery_scope,
            &self.operation,
        ] {
            frame(value.as_bytes(), &mut write);
        }
        write(&[u8::from(self.entity.is_some())]);
        if let Some(entity) = &self.entity {
            frame(entity.as_bytes(), &mut write);
        }
        frame(self.client_key.as_bytes(), &mut write);
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ExpectedVersion {
    Absent,
    Present(Vec<u8>),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Precondition {
    pub key: Vec<u8>,
    pub expected: ExpectedVersion,
}

/// Input has already been canonicalized using the admitted application input
/// format; arbitrary JSON reserialization is not a canonicalization algorithm.
/// Metadata here contains only explicitly declared business-significant fields.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommandFingerprint {
    pub input_format: String,
    pub input: Value,
    pub expected_versions: Vec<Precondition>,
}

impl CommandFingerprint {
    pub fn visit_identity_bytes(&self, mut write: impl FnMut(&[u8])) -> Result<(), ContractError> {
        identity(&self.input_format)?;
        self.input.validate()?;
        bounded(self.expected_versions.len(), PRECONDITIONS)
            .map_err(|_| ContractError::CountLimit)?;
        let mut conditions: Vec<_> = self.expected_versions.iter().collect();
        conditions.sort_by(|left, right| left.key.cmp(&right.key));
        let mut previous: Option<&[u8]> = None;
        for condition in &conditions {
            if condition.key.is_empty() {
                return Err(ContractError::InvalidPresentValue);
            }
            bounded(condition.key.len(), KEY_BYTES)?;
            if previous == Some(condition.key.as_slice()) {
                return Err(ContractError::Duplicate);
            }
            previous = Some(&condition.key);
            if let ExpectedVersion::Present(version) = &condition.expected {
                if version.is_empty() {
                    return Err(ContractError::InvalidPresentValue);
                }
                bounded(version.len(), VERSION_BYTES)?;
            }
        }
        write(b"lsf-command-fingerprint-v1\0");
        frame(self.input_format.as_bytes(), &mut write);
        frame(self.input.media_type.as_bytes(), &mut write);
        frame(&self.input.bytes, &mut write);
        let mut metadata: Vec<_> = self.input.metadata.iter().collect();
        metadata.sort_by(|left, right| left.0.as_bytes().cmp(right.0.as_bytes()));
        write(&(metadata.len() as u64).to_le_bytes());
        for (key, value) in metadata {
            frame(key.as_bytes(), &mut write);
            frame(value.as_bytes(), &mut write);
        }
        write(&(conditions.len() as u64).to_le_bytes());
        for condition in conditions {
            frame(&condition.key, &mut write);
            match &condition.expected {
                ExpectedVersion::Absent => write(&[0]),
                ExpectedVersion::Present(version) => {
                    write(&[1]);
                    frame(version, &mut write);
                }
            }
        }
        Ok(())
    }
}

/// Durable metadata and application state are separate axes. A terminal business
/// rejection is durable, while its staged mutations/effects are discarded.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CommandOutcome {
    InProgress,
    Committed,
    Rejected,
    Aborted,
    Unknown,
    RecoveryRequired,
    Expired,
}

/// Unknown/expired lookup is never proof of technical abort or permission to
/// retry. A caller submits the attributable server-issued fence explicitly.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AbortFence {
    pub command_id: String,
    pub attempt_id: String,
    pub transaction_id: String,
    pub owner_fence: Vec<u8>,
}

pub const DURABLE_RESULT_FORMAT: &str = "lsf-command-result-v1";
pub const DURABLE_INTENT_FORMAT: &str = "lsf-effect-intent-v1";
pub const DURABLE_INBOX_FORMAT: &str = "lsf-inbox-record-v1";
pub const DURABLE_ORDERING_FORMAT: &str = "lsf-ordering-record-v1";
pub const DURABLE_CHECKPOINT_FORMAT: &str = "lsf-checkpoint-record-v1";

#[cfg(test)]
mod tests {
    use super::*;

    fn key() -> CommandKey {
        CommandKey {
            tenant: "tenant".into(),
            namespace: "app".into(),
            incarnation: "i1".into(),
            recovery_scope: "caller/alice".into(),
            operation: "save".into(),
            entity: None,
            client_key: "one".into(),
        }
    }

    fn bytes(key: &CommandKey) -> Vec<u8> {
        let mut bytes = Vec::new();
        key.visit_identity_bytes(|part| bytes.extend_from_slice(part))
            .unwrap();
        bytes
    }

    #[test]
    fn caller_and_incarnation_prevent_foreign_replay() {
        let original = key();
        let mut different = original.clone();
        different.recovery_scope = "caller/bob".into();
        assert_ne!(bytes(&original), bytes(&different));
        different = original.clone();
        different.incarnation = "i2".into();
        assert_ne!(bytes(&original), bytes(&different));
        different.entity = Some(String::new());
        assert_eq!(
            different.visit_identity_bytes(|_| {}),
            Err(ContractError::InvalidPresentValue)
        );
    }

    #[test]
    fn byte_and_presence_boundaries_are_exact() {
        assert_eq!(identity(""), Err(ContractError::InvalidPresentValue));
        assert!(identity(&"é".repeat(128)).is_ok());
        assert_eq!(identity(&"é".repeat(129)), Err(ContractError::ByteLimit));
        let mut value = Value {
            bytes: vec![0; VALUE_BYTES],
            media_type: "application/octet-stream".into(),
            metadata: vec![],
        };
        assert!(value.validate().is_ok());
        value.bytes.push(0);
        assert_eq!(value.validate(), Err(ContractError::ByteLimit));
        value.bytes.clear();
        for media_type in ["text/plain\n", "text/plain\t", "application/é"] {
            value.media_type = media_type.into();
            assert_eq!(value.validate(), Err(ContractError::InvalidPresentValue));
        }
        value.media_type = "application/octet-stream".into();
        value.metadata = vec![("x".into(), String::new()), ("x".into(), "a".into())];
        assert_eq!(value.validate(), Err(ContractError::Duplicate));
    }

    #[test]
    fn fingerprint_sorts_but_never_erases_presence_or_stale_edit_inputs() {
        let mut fingerprint = CommandFingerprint {
            input_format: "raw-v1".into(),
            input: Value {
                bytes: vec![],
                media_type: "application/octet-stream".into(),
                metadata: vec![],
            },
            expected_versions: vec![
                Precondition {
                    key: b"b".to_vec(),
                    expected: ExpectedVersion::Absent,
                },
                Precondition {
                    key: b"a".to_vec(),
                    expected: ExpectedVersion::Present(b"i1:2".to_vec()),
                },
            ],
        };
        let mut original = vec![];
        fingerprint
            .visit_identity_bytes(|part| original.extend_from_slice(part))
            .unwrap();
        fingerprint.expected_versions.reverse();
        let mut reordered = vec![];
        fingerprint
            .visit_identity_bytes(|part| reordered.extend_from_slice(part))
            .unwrap();
        assert_eq!(original, reordered);
        fingerprint.expected_versions[0].expected = ExpectedVersion::Present(vec![]);
        assert_eq!(
            fingerprint.visit_identity_bytes(|_| {}),
            Err(ContractError::InvalidPresentValue)
        );
    }
}

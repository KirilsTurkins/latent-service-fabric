use super::super::{identifier, invalid, MAX_DOCUMENT_BYTES};
use latent_core::PlatformError;
use serde::{Deserialize, Serialize};

/// All limits include tombstones and retained history. Capacity exhaustion
/// rejects new records; it never erases a revision to make a stale create valid.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PolicyStoreLimits {
    pub maximum_records: usize,
    pub maximum_outcomes: usize,
    pub maximum_catalog_bytes: usize,
    pub maximum_read_owners: usize,
    pub maximum_page_records: usize,
}
impl Default for PolicyStoreLimits {
    fn default() -> Self {
        Self {
            maximum_records: 128,
            maximum_outcomes: 256,
            maximum_catalog_bytes: 4 * 1024 * 1024,
            maximum_read_owners: 32,
            maximum_page_records: 16,
        }
    }
}
impl PolicyStoreLimits {
    pub fn validate(self) -> Result<(), PlatformError> {
        if !(1..=256).contains(&self.maximum_records)
            || !(1..=256).contains(&self.maximum_outcomes)
            || !(4096..=16 * 1024 * 1024).contains(&self.maximum_catalog_bytes)
            || !(1..=128).contains(&self.maximum_read_owners)
            || !(1..=32).contains(&self.maximum_page_records)
        {
            return Err(invalid());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum RecordKind {
    Policy,
    ProviderBinding,
}

/// Read-only history. An object, digest or generation is never execution permission.
#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RecordView {
    pub tenant: String,
    pub id: String,
    pub kind: RecordKind,
    pub revision: u64,
    pub digest: String,
    /// Revocation retains identity and revision but releases document storage.
    pub document: Option<String>,
}
impl RecordView {
    pub(super) fn matches(&self, tenant: &str, kind: RecordKind, id: &str) -> bool {
        self.tenant == tenant && self.kind == kind && self.id == id
    }
}

/// Borrowed, bounded before normalization/copying. `None` revokes an existing
/// record. `expected_revision = 0` creates only an identity never seen before.
#[derive(Clone, Copy)]
pub struct MutationRequest<'a> {
    pub tenant: &'a str,
    pub actor: &'a str,
    pub id: &'a str,
    pub kind: RecordKind,
    pub operation_id: &'a str,
    pub expected_revision: u64,
    pub document: Option<&'a [u8]>,
}
impl MutationRequest<'_> {
    pub(super) fn validate(&self) -> Result<(), PlatformError> {
        if ![self.tenant, self.actor, self.id, self.operation_id]
            .into_iter()
            .all(identifier)
            || self
                .document
                .is_some_and(|value| value.len() > MAX_DOCUMENT_BYTES)
        {
            return Err(invalid());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OperationReceipt {
    pub operation_id: String,
    pub tenant: String,
    pub id: String,
    pub kind: RecordKind,
    pub revision: u64,
    pub digest: String,
    pub revoked: bool,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct Outcome {
    pub fingerprint: String,
    pub receipt: OperationReceipt,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct Image {
    pub format_version: u32,
    pub generation: u64,
    pub records: Vec<RecordView>,
    pub outcomes: Vec<Outcome>,
}
impl Image {
    pub fn empty() -> Self {
        Self {
            format_version: 1,
            generation: 1,
            records: Vec::new(),
            outcomes: Vec::new(),
        }
    }
}

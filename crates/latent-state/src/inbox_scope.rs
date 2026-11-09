//! Durable first-source descriptions. The operator and protected recovery owners
//! must independently establish creation and restore authority; these rows and
//! plans are not evidence that older history has not been restored.

use crate::embedded::{
    AtomicBatch, ExpectedRow, Family, ReadView, RowKey, RowMutation, StoreError,
};
use latent_core::{StateNamespaceId, TenantId};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

const PREFIX: &[u8] = b"inbox-source-v1\0";
const MAX_BYTES: usize = 2048;

/// A host-selected logical subscription and its authenticated first origin.
/// Neither this value nor its stable key grants broker or namespace access.
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct InboxScope {
    pub tenant: String,
    pub namespace: String,
    pub incarnation: u64,
    pub processing_scope: String,
    pub provider: String,
    pub stream: String,
    pub stream_created: String,
}

impl InboxScope {
    fn validate(&self) -> Result<(), StoreError> {
        for value in [
            &self.tenant,
            &self.namespace,
            &self.processing_scope,
            &self.provider,
            &self.stream,
            &self.stream_created,
        ] {
            if value.is_empty() || value.len() > 128 || value.chars().any(char::is_control) {
                return Err(StoreError::Invalid);
            }
        }
        if self.incarnation == 0 {
            return Err(StoreError::Invalid);
        }
        Ok(())
    }

    fn key(&self) -> Result<RowKey, StoreError> {
        self.validate()?;
        let mut hash = Sha256::new();
        hash.update(PREFIX);
        let incarnation = self.incarnation.to_le_bytes();
        for part in [
            self.tenant.as_bytes(),
            self.namespace.as_bytes(),
            incarnation.as_slice(),
            self.processing_scope.as_bytes(),
        ] {
            hash.update((part.len() as u64).to_le_bytes());
            hash.update(part);
        }
        let mut key = PREFIX.to_vec();
        key.extend_from_slice(&hash.finalize());
        Ok(RowKey {
            family: Family::Maintenance,
            key,
        })
    }

    /// Derive the existing trusted-input scope identifier from the exact
    /// descriptive source. This digest does not authorize creating the record.
    pub fn input_binding(&self) -> Result<String, StoreError> {
        self.validate()?;
        let incarnation = self.incarnation.to_le_bytes();
        let mut hash = Sha256::new();
        hash.update(b"lsf-jetstream-input-scope-v1\0");
        for part in [
            self.tenant.as_bytes(),
            self.provider.as_bytes(),
            self.stream.as_bytes(),
            self.stream_created.as_bytes(),
            self.processing_scope.as_bytes(),
            self.namespace.as_bytes(),
            incarnation.as_slice(),
        ] {
            hash.update((part.len() as u64).to_le_bytes());
            hash.update(part);
        }
        Ok(format!(
            "{:x}",
            latent_core::digest::HexDigest(hash.finalize())
        ))
    }

    fn encode(&self) -> Result<Vec<u8>, StoreError> {
        self.validate()?;
        let mut bytes = serde_json::to_vec(self).map_err(|_| StoreError::Invalid)?;
        if bytes.len() > MAX_BYTES - 32 {
            return Err(StoreError::Capacity);
        }
        // Detect damaged bytes; this checksum is not an authentication or
        // protected-restore continuity proof.
        let mut hash = Sha256::new();
        hash.update(PREFIX);
        hash.update(&bytes);
        bytes.extend_from_slice(&hash.finalize());
        Ok(bytes)
    }

    fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        if bytes.len() <= 32 || bytes.len() > MAX_BYTES {
            return Err(StoreError::Corrupt);
        }
        let value: Self =
            serde_json::from_slice(&bytes[..bytes.len() - 32]).map_err(|_| StoreError::Corrupt)?;
        if value.encode().map_err(|_| StoreError::Corrupt)? != bytes {
            return Err(StoreError::Corrupt);
        }
        Ok(value)
    }
}

pub fn validate_row(key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    if key.family != Family::Maintenance || !key.key.starts_with(PREFIX) {
        return Err(StoreError::UnsupportedFormat);
    }
    let record = InboxScope::decode(bytes)?;
    if record.key().map_err(|_| StoreError::Corrupt)? != *key {
        return Err(StoreError::Corrupt);
    }
    Ok(())
}

pub fn census_contribution(
    view: &ReadView,
    key: &RowKey,
    bytes: &[u8],
) -> Result<crate::tenant::TenantCensusContribution, StoreError> {
    validate_row(key, bytes)?;
    let record = InboxScope::decode(bytes)?;
    let tenant = TenantId(record.tenant);
    let namespace = StateNamespaceId(record.namespace);
    let current = crate::namespace::catalog::NamespaceCatalog::read_in(view, &tenant, &namespace)
        .map_err(|_| StoreError::Corrupt)?
        .ok_or(StoreError::Corrupt)?;
    if current.record().version.incarnation < record.incarnation {
        return Err(StoreError::Corrupt);
    }
    Ok(crate::tenant::TenantCensusContribution::Usage {
        tenant,
        usage: crate::tenant::TenantUsage {
            metadata_rows: 1,
            metadata_bytes: crate::tenant::row_charge(key, bytes)?,
            ..Default::default()
        },
    })
}

/// A lower atomic plan only. The installed owner must establish trusted origin,
/// explicit initial-scope approval, older-restore continuity, and a final host
/// acceptance fence before publishing; this type does not establish any of them.
pub struct PreparedInboxScope {
    batch: AtomicBatch,
    existing: bool,
}
impl PreparedInboxScope {
    pub fn prepare(view: &ReadView, record: &InboxScope) -> Result<Self, StoreError> {
        let key = record.key()?;
        let bytes = record.encode()?;
        let tenant = TenantId(record.tenant.clone());
        let namespace = StateNamespaceId(record.namespace.clone());
        crate::tenant::inspect(view, &tenant)?.ok_or(StoreError::UnsupportedFormat)?;
        let mut expectations = crate::recovery::namespace_readiness_expectations(
            view,
            &tenant,
            &namespace,
            record.incarnation,
        )?
        .to_vec();
        let original = view.get(&key)?;
        if let Some(old) = &original {
            validate_row(&key, old)?;
            if *old != bytes {
                return Err(StoreError::Conflict);
            }
        }
        let existing = original.is_some();
        expectations.push(ExpectedRow {
            key: key.clone(),
            value: original,
        });
        let mut batch = AtomicBatch {
            expectations,
            mutations: Vec::new(),
        };
        if existing {
            crate::tenant::prepare_update(view, &tenant, Default::default())?
                .append_read_expectations(&mut batch)?;
        } else {
            let delta = crate::tenant::TenantDelta {
                added: crate::tenant::TenantUsage {
                    metadata_rows: 1,
                    metadata_bytes: crate::tenant::row_charge(&key, &bytes)?,
                    ..Default::default()
                },
                ..Default::default()
            };
            batch.mutations.push(RowMutation {
                key,
                value: Some(bytes),
            });
            crate::tenant::prepare_update(view, &tenant, delta)?.append_to(&mut batch)?;
        }
        Ok(Self { batch, existing })
    }
    #[must_use]
    pub fn existing(&self) -> bool {
        self.existing
    }
    #[must_use]
    pub fn into_batch(self) -> AtomicBatch {
        self.batch
    }
}

/// Capture an already-published exact source for a dependent atomic writer.
/// Missing history is never interpreted as approval to create a new scope.
pub fn require_existing(view: &ReadView, scope: &InboxScope) -> Result<ExpectedRow, StoreError> {
    let plan = PreparedInboxScope::prepare(view, scope)?;
    if !plan.existing {
        return Err(StoreError::Conflict);
    }
    let key = scope.key()?;
    plan.batch
        .expectations
        .into_iter()
        .find(|expected| expected.key == key && expected.value.is_some())
        .ok_or(StoreError::Corrupt)
}

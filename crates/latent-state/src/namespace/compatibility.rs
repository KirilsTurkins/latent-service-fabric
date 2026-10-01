//! Bounded application-schema and retained-work compatibility decisions. These
//! descriptors never authorize publication, migration, dispatch or result reads.
//! The installed host reviewer binds tested evidence to exact package bytes.

use super::{identity, NamespaceError, NamespaceRecord};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

pub const SCHEMA_DEFINITION_BYTES: usize = 4096;
pub const SCHEMAS_PER_REVISION: usize = 8;
pub const REVISIONS_PER_COMPOSITION: usize = 8;
pub const RETAINED_FORMATS: usize = 128;
pub const RETAINED_ROWS: u64 = 65_536;
pub const RETAINED_BYTES: u64 = 128 * 1024 * 1024;

/// Hash of exact bounded application definition bytes, separate from the engine,
/// package, WIT and publication identities. No inferred structural compatibility.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct SchemaId(String);

impl SchemaId {
    pub fn from_definition(bytes: &[u8]) -> Result<Self, NamespaceError> {
        if bytes.is_empty() || bytes.len() > SCHEMA_DEFINITION_BYTES {
            return Err(NamespaceError::Invalid);
        }
        let digest: [u8; 32] = Sha256::digest(bytes).into();
        Self::parse(&format!("sha256:{}", hex(&digest)))
    }

    pub fn parse(text: &str) -> Result<Self, NamespaceError> {
        if text.len() != 71
            || !text.starts_with("sha256:")
            || !text.as_bytes()[7..]
                .iter()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(byte))
        {
            return Err(NamespaceError::Invalid);
        }
        Ok(Self(text.into()))
    }

    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SchemaDeclaration {
    pub package_digest: [u8; 32],
    pub readers: Vec<SchemaId>,
    pub writers: Vec<SchemaId>,
}

impl SchemaDeclaration {
    /// Canonical sorted exact sets: duplicate/unknown/oversized declarations
    /// refuse rather than truncating. This is still descriptive, not evidence.
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, NamespaceError> {
        if self.package_digest == [0; 32] {
            return Err(NamespaceError::Invalid);
        }
        let mut bytes = b"application-schema-declaration-v1\0".to_vec();
        bytes.extend_from_slice(&self.package_digest);
        for schemas in [&self.readers, &self.writers] {
            if schemas.is_empty() || schemas.len() > SCHEMAS_PER_REVISION {
                return Err(NamespaceError::Capacity);
            }
            let mut sorted = schemas.iter().collect::<Vec<_>>();
            sorted.sort();
            if sorted.windows(2).any(|pair| pair[0] == pair[1]) {
                return Err(NamespaceError::Invalid);
            }
            bytes.push(u8::try_from(sorted.len()).map_err(|_| NamespaceError::Capacity)?);
            for schema in sorted {
                bytes.extend_from_slice(schema.as_str().as_bytes());
            }
        }
        Ok(bytes)
    }

    pub fn digest(&self) -> Result<[u8; 32], NamespaceError> {
        Ok(Sha256::digest(self.canonical_bytes()?).into())
    }
}

/// Constructed only after the configured host's exact-evidence reviewer accepts.
/// It supplies tested compatibility metadata; present policy/publication fences
/// remain mandatory and are independent from schema/history generations.
#[derive(Debug, Clone)]
pub struct ReviewedSchema {
    declaration: SchemaDeclaration,
    declaration_digest: [u8; 32],
    proof_digest: [u8; 32],
}

impl ReviewedSchema {
    pub fn accept_with(
        declaration: SchemaDeclaration,
        actual_package_digest: [u8; 32],
        proof_digest: [u8; 32],
        review: impl FnOnce(&SchemaDeclaration, [u8; 32], [u8; 32]) -> Result<(), NamespaceError>,
    ) -> Result<Self, NamespaceError> {
        let declaration_digest = declaration.digest()?;
        if declaration.package_digest != actual_package_digest || proof_digest == [0; 32] {
            return Err(NamespaceError::PermissionDenied);
        }
        review(&declaration, declaration_digest, proof_digest)?;
        Ok(Self {
            declaration,
            declaration_digest,
            proof_digest,
        })
    }

    #[must_use]
    pub fn declaration(&self) -> &SchemaDeclaration {
        &self.declaration
    }

    #[must_use]
    pub fn declaration_digest(&self) -> [u8; 32] {
        self.declaration_digest
    }

    #[must_use]
    pub fn proof_digest(&self) -> [u8; 32] {
        self.proof_digest
    }

    pub fn require_namespace(&self, namespace: &NamespaceRecord) -> Result<(), NamespaceError> {
        namespace.validate()?;
        let actual = SchemaId::parse(&namespace.state_schema)?;
        if !self.declaration.readers.contains(&actual) {
            return Err(NamespaceError::UnsupportedFormat);
        }
        Ok(())
    }
}

/// Deployment, shared-state canary and rollback use the same closed decision.
/// A revision must read the current namespace AND every selected writer schema;
/// code rollback never changes committed values or renews old effect authority.
pub fn require_composition(
    namespace: &NamespaceRecord,
    revisions: &[ReviewedSchema],
) -> Result<(), NamespaceError> {
    namespace.validate()?;
    if revisions.is_empty() || revisions.len() > REVISIONS_PER_COMPOSITION {
        return Err(NamespaceError::Capacity);
    }
    for (index, revision) in revisions.iter().enumerate() {
        revision.require_namespace(namespace)?;
        if revisions[..index]
            .iter()
            .any(|prior| prior.declaration.package_digest == revision.declaration.package_digest)
        {
            return Err(NamespaceError::Invalid);
        }
        for writer in revisions {
            if writer
                .declaration
                .writers
                .iter()
                .any(|schema| !revision.declaration.readers.contains(schema))
            {
                return Err(NamespaceError::UnsupportedFormat);
            }
        }
    }
    Ok(())
}

/// Retained work is never decoded implicitly by an application state schema.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
#[repr(u8)]
pub enum RetainedKind {
    EffectEnvelope = 1,
    EffectPayload = 2,
    AdapterProfile = 3,
    SuccessResult = 4,
    RejectionResult = 5,
    CommandFingerprint = 6,
    CommandAttempt = 7,
    InboxIdentity = 8,
    OrderingGroup = 9,
    MigrationCheckpoint = 10,
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct RetainedFormat {
    pub kind: RetainedKind,
    pub identity: String,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct RetainedCount {
    pub rows: u64,
    pub bytes: u64,
    pub unresolved: u64,
}

/// The installed format owner observes actual linked rows from one coherent
/// read view. Totals and distinct identities are finite; no silent inventory cap.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RetainedInventory {
    entries: BTreeMap<RetainedFormat, RetainedCount>,
    total: RetainedCount,
}

impl RetainedInventory {
    pub fn observe(
        &mut self,
        format: RetainedFormat,
        count: RetainedCount,
    ) -> Result<(), NamespaceError> {
        identity(&format.identity)?;
        if count.rows == 0 || count.unresolved > count.rows {
            return Err(NamespaceError::Invalid);
        }
        if !self.entries.contains_key(&format) && self.entries.len() == RETAINED_FORMATS {
            return Err(NamespaceError::Capacity);
        }
        let add = |one: RetainedCount, two: RetainedCount| {
            let next = RetainedCount {
                rows: one
                    .rows
                    .checked_add(two.rows)
                    .ok_or(NamespaceError::Capacity)?,
                bytes: one
                    .bytes
                    .checked_add(two.bytes)
                    .ok_or(NamespaceError::Capacity)?,
                unresolved: one
                    .unresolved
                    .checked_add(two.unresolved)
                    .ok_or(NamespaceError::Capacity)?,
            };
            if next.rows > RETAINED_ROWS || next.bytes > RETAINED_BYTES {
                return Err(NamespaceError::Capacity);
            }
            Ok(next)
        };
        let total = add(self.total, count)?;
        let entry = add(
            self.entries.get(&format).copied().unwrap_or_default(),
            count,
        )?;
        self.entries.insert(format, entry);
        self.total = total;
        Ok(())
    }

    #[must_use]
    pub fn entries(&self) -> &BTreeMap<RetainedFormat, RetainedCount> {
        &self.entries
    }

    #[must_use]
    pub fn total(&self) -> RetainedCount {
        self.total
    }

    /// An installed, tested decoder must cover each exact retained identity.
    /// Migration/drain are separate operations; their plans do not satisfy this
    /// check until actual rows have been transformed or safely retired.
    pub fn require_decoders(&self, installed: &[RetainedFormat]) -> Result<(), NamespaceError> {
        if installed.len() > RETAINED_FORMATS {
            return Err(NamespaceError::Capacity);
        }
        for (index, format) in installed.iter().enumerate() {
            identity(&format.identity)?;
            if installed[..index].contains(format) {
                return Err(NamespaceError::Invalid);
            }
        }
        if self
            .entries
            .keys()
            .any(|format| !installed.contains(format))
        {
            return Err(NamespaceError::UnsupportedFormat);
        }
        Ok(())
    }

    pub fn require_retirement_drained(&self) -> Result<(), NamespaceError> {
        if self.total.unresolved != 0 {
            return Err(NamespaceError::RecoveryRequired);
        }
        Ok(())
    }
}

fn hex(bytes: &[u8; 32]) -> String {
    use std::fmt::Write as _;
    let mut output = String::with_capacity(64);
    for byte in bytes {
        write!(&mut output, "{byte:02x}").expect("writing a bounded String cannot fail");
    }
    output
}

#[cfg(test)]
mod tests;

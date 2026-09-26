use crate::{BlobRange, BlobReference};
use latent_core::{BlobDigest, Metadata, TenantId};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LocalBlobError {
    Invalid,
    PermissionDenied,
    NotFound,
    Corrupt,
    Capacity,
    Busy,
    Unavailable,
    Uncertain,
    Closed,
    Cancelled,
    DeadlineExceeded,
}
pub type Result<T> = std::result::Result<T, LocalBlobError>;
impl std::fmt::Display for LocalBlobError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "local blob operation: {self:?}")
    }
}
impl std::error::Error for LocalBlobError {}

#[derive(Debug, Clone, Copy, Serialize)]
pub struct LocalBlobLimits {
    pub maximum_objects: usize,
    pub maximum_object_bytes: u64,
    /// Logical file-byte ceiling including prepaid sidecar and marker capacity.
    pub maximum_disk_bytes: u64,
    pub maximum_stages: usize,
    pub maximum_stage_bytes: u64,
    pub maximum_handles: usize,
    pub maximum_metadata_bytes: usize,
    pub maximum_chunk_bytes: usize,
    pub maximum_work: usize,
}
impl Default for LocalBlobLimits {
    fn default() -> Self {
        Self {
            maximum_objects: 4096,
            maximum_object_bytes: 16 * 1024 * 1024,
            maximum_disk_bytes: 1024 * 1024 * 1024,
            maximum_stages: 16,
            maximum_stage_bytes: 128 * 1024 * 1024,
            maximum_handles: 128,
            maximum_metadata_bytes: 16 * 1024 * 1024,
            maximum_chunk_bytes: 64 * 1024,
            maximum_work: 16,
        }
    }
}
impl LocalBlobLimits {
    pub(super) fn validate(self) -> Result<()> {
        if self.maximum_objects == 0
            || self.maximum_objects > 100_000
            || self.maximum_object_bytes == 0
            || self.maximum_object_bytes > 1024 * 1024 * 1024
            || self.maximum_disk_bytes
                < self.maximum_object_bytes + super::DISK_ROOT_BYTES + super::DISK_ENTRY_BYTES
            || self.maximum_disk_bytes > 1024 * 1024 * 1024 * 1024
            || self.maximum_stages == 0
            || self.maximum_stages > 1024
            || self.maximum_stage_bytes < self.maximum_object_bytes
            || self.maximum_stage_bytes > self.maximum_disk_bytes
            || self.maximum_handles == 0
            || self.maximum_handles > 4096
            || self.maximum_metadata_bytes < 65536
            || self.maximum_metadata_bytes > 256 * 1024 * 1024
            || self.maximum_chunk_bytes == 0
            || self.maximum_chunk_bytes > 64 * 1024
            || self.maximum_work == 0
            || self.maximum_work > 256
        {
            return Err(LocalBlobError::Invalid);
        }
        Ok(())
    }
}
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct LocalBlobSnapshot {
    pub objects: usize,
    pub referenced_objects: usize,
    /// Published payload bytes, including unreclaimed released references.
    pub resident_disk_bytes: u64,
    /// Payload reservations plus bounded on-disk sidecars, including empty blobs.
    pub accounted_disk_bytes: u64,
    pub stages: usize,
    pub reserved_stage_bytes: u64,
    pub handles: usize,
    pub active_work: usize,
    pub metadata_bytes: usize,
    pub poisoned: bool,
    pub closed: bool,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct OwnerRecord {
    pub version: u8,
    pub namespace: String,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct StageRecord {
    pub version: u8,
    pub id: u64,
    pub tenant: String,
    pub media_type: String,
    pub expected_size: Option<u64>,
    pub maximum_size: u64,
}
#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct ReferenceRecord {
    pub version: u8,
    pub namespace: String,
    pub tenant: String,
    pub digest: String,
    pub size: u64,
    pub media_type: String,
}
impl ReferenceRecord {
    pub fn key(&self) -> String {
        let mut hash = Sha256::new();
        hash.update(b"LSF tenant blob reference v1\0");
        for value in [
            &self.namespace,
            &self.tenant,
            &self.digest,
            &self.media_type,
        ] {
            hash.update((value.len() as u64).to_le_bytes());
            hash.update(value.as_bytes());
        }
        hash.update(self.size.to_le_bytes());
        format!("{:x}", hash.finalize())
    }
    pub fn validate(&self, namespace: &str, maximum: u64) -> Result<()> {
        if self.version != 1
            || self.namespace != namespace
            || self.size > maximum
            || !self.digest.starts_with("sha256:")
            || self.digest.len() != 71
            || !hex(&self.digest[7..], 64)
        {
            return Err(LocalBlobError::Corrupt);
        }
        text(&self.tenant)?;
        text(&self.media_type)?;
        Ok(())
    }
    pub fn reference(&self) -> BlobReference {
        BlobReference {
            digest: BlobDigest(self.digest.clone()),
            size_bytes: self.size,
            media_type: self.media_type.clone(),
            tenant: TenantId(self.tenant.clone()),
            metadata: Metadata::new(),
        }
    }
    pub fn requested(
        namespace: &str,
        tenant: &TenantId,
        reference: &BlobReference,
        maximum: u64,
    ) -> Result<Self> {
        if tenant != &reference.tenant || !reference.metadata.is_empty() {
            return Err(LocalBlobError::PermissionDenied);
        }
        text(&tenant.0)?;
        text(&reference.media_type)?;
        if reference.digest.0.len() != 71 {
            return Err(LocalBlobError::Invalid);
        }
        let result = Self {
            version: 1,
            namespace: namespace.into(),
            tenant: tenant.0.clone(),
            digest: reference.digest.0.clone(),
            size: reference.size_bytes,
            media_type: reference.media_type.clone(),
        };
        result.validate(namespace, maximum)?;
        Ok(result)
    }
}
pub(super) fn text(value: &str) -> Result<()> {
    if value.is_empty() || value.len() > 128 || value.chars().any(char::is_control) {
        return Err(LocalBlobError::Invalid);
    }
    Ok(())
}
pub(super) fn hex(value: &str, length: usize) -> bool {
    value.len() == length
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
pub(super) fn range(range: &BlobRange, size: u64, maximum: usize) -> Result<usize> {
    if range
        .offset
        .checked_add(range.length)
        .is_none_or(|end| end > size)
        || range.length > maximum as u64
    {
        return Err(LocalBlobError::Invalid);
    }
    usize::try_from(range.length).map_err(|_| LocalBlobError::Invalid)
}

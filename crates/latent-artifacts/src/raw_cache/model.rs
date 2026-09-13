use super::{invalid, Result};
use latent_core::{ArtifactBlobDigest, PackageDigest};

/// Exact byte identity; neither variant asserts package validity or trust.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RawArtifactKey {
    Manifest(PackageDigest),
    Blob(ArtifactBlobDigest),
}

impl RawArtifactKey {
    pub(super) fn compact(self) -> Self {
        Self::from_name(&self.name()).expect("typed digest has canonical bounded spelling")
    }
    pub(super) fn digest(&self) -> &str {
        match self {
            Self::Manifest(value) => value.as_str(),
            Self::Blob(value) => value.as_str(),
        }
    }
    pub(super) fn name(&self) -> String {
        format!(
            "{}-{}",
            if matches!(self, Self::Manifest(_)) {
                "m"
            } else {
                "b"
            },
            &self.digest()[7..]
        )
    }
    pub(super) fn from_name(value: &str) -> Result<Self> {
        if value.len() != 66 {
            return Err(invalid("raw-cache-object-name"));
        }
        if let Some(hex) = value.strip_prefix("m-") {
            return format!("sha256:{hex}")
                .parse()
                .map(Self::Manifest)
                .map_err(|_| invalid("raw-cache-object-name"));
        }
        if let Some(hex) = value.strip_prefix("b-") {
            return format!("sha256:{hex}")
                .parse()
                .map(Self::Blob)
                .map_err(|_| invalid("raw-cache-object-name"));
        }
        Err(invalid("raw-cache-object-name"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn retained_keys_discard_caller_spare_capacity() {
        for manifest in [false, true] {
            let mut text = String::with_capacity(1024 * 1024);
            text.push_str("sha256:");
            text.push_str(&"1".repeat(64));
            let key = if manifest {
                RawArtifactKey::Manifest(text.try_into().unwrap())
            } else {
                RawArtifactKey::Blob(text.try_into().unwrap())
            }
            .compact();
            let capacity = match key {
                RawArtifactKey::Manifest(value) => value.into_string().capacity(),
                RawArtifactKey::Blob(value) => value.into_string().capacity(),
            };
            assert!(capacity <= 128);
        }
    }
}

/// Independent conservative bounds. All values are lowerable from hard ceilings.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RawArtifactCacheLimits {
    pub maximum_entries: usize,
    pub maximum_disk_bytes: u64,
    pub maximum_metadata_bytes: usize,
    pub maximum_staging_entries: usize,
    pub maximum_staging_bytes: u64,
    pub maximum_read_bytes: u64,
    pub maximum_reads: usize,
    pub maximum_pins: usize,
    pub maximum_work: usize,
    pub maximum_object_bytes: u64,
    pub maximum_recovery_entries: usize,
}

impl Default for RawArtifactCacheLimits {
    fn default() -> Self {
        Self {
            maximum_entries: 1024,
            maximum_disk_bytes: 256 * 1024 * 1024,
            maximum_metadata_bytes: 2 * 1024 * 1024,
            maximum_staging_entries: 2,
            maximum_staging_bytes: 128 * 1024 * 1024,
            maximum_read_bytes: 128 * 1024 * 1024,
            maximum_reads: 8,
            maximum_pins: 64,
            maximum_work: 4,
            maximum_object_bytes: 64 * 1024 * 1024,
            maximum_recovery_entries: 2048,
        }
    }
}

impl RawArtifactCacheLimits {
    pub fn validate(self) -> Result<()> {
        if self.maximum_entries == 0
            || self.maximum_entries > 65536
            || self.maximum_disk_bytes == 0
            || self.maximum_disk_bytes > 4 * 1024 * 1024 * 1024
            || self.maximum_metadata_bytes == 0
            || self.maximum_metadata_bytes > 64 * 1024 * 1024
            || self.maximum_staging_entries == 0
            || self.maximum_staging_entries > 32
            || self.maximum_staging_bytes == 0
            || self.maximum_staging_bytes > 512 * 1024 * 1024
            || self.maximum_read_bytes == 0
            || self.maximum_read_bytes > 512 * 1024 * 1024
            || self.maximum_reads == 0
            || self.maximum_reads > 64
            || self.maximum_pins == 0
            || self.maximum_pins > 4096
            || self.maximum_work == 0
            || self.maximum_work > 32
            || self.maximum_object_bytes == 0
            || self.maximum_object_bytes > 256 * 1024 * 1024
            || self.maximum_recovery_entries == 0
            || self.maximum_recovery_entries > 131_072
        {
            return Err(invalid("raw-cache-invalid-limits"));
        }
        if self
            .maximum_reads
            .checked_add(self.maximum_work)
            .and_then(|handles| handles.checked_mul(super::HANDLE_METADATA))
            .and_then(|bytes| bytes.checked_add(super::OWNER_METADATA))
            .is_none_or(|bytes| bytes > self.maximum_metadata_bytes)
        {
            return Err(invalid("raw-cache-invalid-limits"));
        }
        Ok(())
    }
}

/// Charged domains, not RSS. Pinned/deletion-pending bytes are subsets of disk
/// charges; staging reservations include their already-written file bytes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RawArtifactCacheSnapshot {
    pub limits: RawArtifactCacheLimits,
    pub entries: usize,
    pub resident_disk_bytes: u64,
    pub reserved_disk_bytes: u64,
    pub pinned_disk_bytes: u64,
    pub metadata_bytes: usize,
    pub staging_entries: usize,
    pub active_reads: usize,
    pub reserved_read_bytes: u64,
    pub retained_read_bytes: u64,
    pub active_work: usize,
    pub pins: usize,
    pub deletion_pending_bytes: u64,
    pub hits: u64,
    pub misses: u64,
    pub evictions: u64,
    pub corruptions: u64,
    pub pressure_rejections: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RawArtifactEviction {
    Removed,
    Absent,
    Pinned,
}

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct RawArtifactReclamation {
    pub examined: usize,
    pub removed: usize,
    pub reclaimed_bytes: u64,
    pub pinned: usize,
}

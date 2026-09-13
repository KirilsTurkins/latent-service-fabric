//! Versioned completion records bind exact persisted metadata to component identity.

use std::fs;
use std::path::Path;

use latent_core::PlatformError;
use latent_manifest::{
    __serde::{Deserialize, Serialize},
    __serde_json as json,
};

use super::{corrupt, read_bounded_file, COMPLETE_FILE};
use crate::{content_digest, ArtifactDescriptor};

#[cfg(test)]
pub(super) mod faults;

pub(super) const MAX_COMPLETION_RECORD_BYTES: usize = 1024;
const FORMAT_VERSION: u32 = 1;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde", deny_unknown_fields)]
pub(super) struct CompletionRecord {
    format_version: u32,
    component_digest: String,
    component_size_bytes: u64,
    metadata_digest: String,
    manifest_digest: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    admission_digest: Option<String>,
}

impl CompletionRecord {
    pub(super) fn from_payloads(
        descriptor: &ArtifactDescriptor,
        metadata_bytes: &[u8],
        manifest_bytes: &[u8],
    ) -> Self {
        Self {
            format_version: FORMAT_VERSION,
            component_digest: descriptor.release_digest.0.clone(),
            component_size_bytes: descriptor.size_bytes,
            metadata_digest: content_digest(metadata_bytes).0,
            manifest_digest: content_digest(manifest_bytes).0,
            admission_digest: None,
        }
    }

    pub(super) fn encode(&self) -> Result<Vec<u8>, PlatformError> {
        if !matches!(
            (self.format_version, self.admission_digest.as_deref()),
            (1, None) | (2, Some(_))
        ) || self
            .admission_digest
            .as_deref()
            .is_some_and(|value| !canonical_digest(value))
            || !canonical_digest(&self.component_digest)
            || !canonical_digest(&self.metadata_digest)
            || !canonical_digest(&self.manifest_digest)
        {
            return Err(invalid_record());
        }
        let bytes = json::to_vec(self).map_err(|_| invalid_record())?;
        if bytes.len() > MAX_COMPLETION_RECORD_BYTES {
            return Err(invalid_record());
        }
        Ok(bytes)
    }

    pub(super) fn bind_admission(&mut self, bytes: &[u8]) {
        self.format_version = 2;
        self.admission_digest = Some(content_digest(bytes).0);
    }
    pub(super) fn admission_digest(&self) -> Option<&str> {
        self.admission_digest.as_deref()
    }
    pub(super) fn same_artifact(&self, other: &Self) -> bool {
        self.component_digest == other.component_digest
            && self.component_size_bytes == other.component_size_bytes
            && self.metadata_digest == other.metadata_digest
            && self.manifest_digest == other.manifest_digest
    }
    pub(super) fn identity(&self) -> Result<[u8; 32], PlatformError> {
        use sha2::{Digest, Sha256};
        Ok(Sha256::digest(self.encode()?).into())
    }

    pub(super) fn read(entry: &Path) -> Result<Self, PlatformError> {
        let path = entry.join(COMPLETE_FILE);
        let metadata = fs::symlink_metadata(&path).map_err(|_| invalid_record())?;
        if !metadata.file_type().is_file() {
            return Err(invalid_record());
        }
        // The fixed record bound is a format rule, not a configurable payload quota.
        let bytes = read_bounded_file(
            &path,
            MAX_COMPLETION_RECORD_BYTES,
            "catalog completion record",
        )
        .map_err(|_| invalid_record())?;
        if bytes == b"complete\n" {
            return Err(corrupt("legacy catalog completion marker is unsupported"));
        }
        let record: Self = json::from_slice(&bytes).map_err(|_| invalid_record())?;
        if record.encode()? != bytes {
            return Err(invalid_record());
        }
        Ok(record)
    }

    pub(super) fn verify_metadata(&self, bytes: &[u8]) -> Result<(), PlatformError> {
        if content_digest(bytes).0 != self.metadata_digest {
            return Err(invalid_record());
        }
        Ok(())
    }

    pub(super) fn verify_manifest(&self, bytes: &[u8]) -> Result<(), PlatformError> {
        if content_digest(bytes).0 != self.manifest_digest {
            return Err(invalid_record());
        }
        Ok(())
    }

    pub(super) fn verify_component_association(
        &self,
        descriptor: &ArtifactDescriptor,
    ) -> Result<(), PlatformError> {
        if self.component_digest != descriptor.release_digest.0
            || self.component_size_bytes != descriptor.size_bytes
        {
            return Err(invalid_record());
        }
        Ok(())
    }
}

fn canonical_digest(value: &str) -> bool {
    value.strip_prefix("sha256:").is_some_and(|hex| {
        hex.len() == 64
            && hex
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    })
}

pub(super) fn invalid_record() -> PlatformError {
    corrupt("invalid catalog completion record")
}

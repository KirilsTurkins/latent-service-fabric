use latent_core::{PlatformError, PlatformErrorCode};

use super::{AdmissionBinding, PackageAdmissionUpload};

/// Shared per-operation/recovery ceilings. Only values below hard limits apply.
#[derive(Debug, Clone, Copy)]
pub struct AdmissionStorageLimits {
    pub max_receipt_bytes: usize,
    pub max_document_bytes: usize,
    pub max_layers: usize,
    pub max_evidence_per_kind: usize,
    pub max_auxiliary_bytes: usize,
    pub max_grant_bytes: usize,
}
impl Default for AdmissionStorageLimits {
    fn default() -> Self {
        Self {
            max_receipt_bytes: 16 * 1024,
            max_document_bytes: 256 * 1024,
            max_layers: 256,
            max_evidence_per_kind: 8,
            max_auxiliary_bytes: 16 * 1024 * 1024,
            max_grant_bytes: 256 * 1024,
        }
    }
}
impl AdmissionStorageLimits {
    pub fn validate(self) -> Result<(), PlatformError> {
        let hard = Self {
            max_auxiliary_bytes: 64 * 1024 * 1024,
            ..Self::default()
        };
        for (value, maximum) in [
            (self.max_receipt_bytes, hard.max_receipt_bytes),
            (self.max_document_bytes, hard.max_document_bytes),
            (self.max_layers, hard.max_layers),
            (self.max_evidence_per_kind, hard.max_evidence_per_kind),
            (self.max_auxiliary_bytes, hard.max_auxiliary_bytes),
            (self.max_grant_bytes, hard.max_grant_bytes),
        ] {
            if value == 0 || value > maximum {
                return Err(exhausted());
            }
        }
        Ok(())
    }

    pub fn check_upload(
        self,
        upload: &PackageAdmissionUpload,
        component_limit: usize,
    ) -> Result<(), PlatformError> {
        self.validate()?;
        if upload.layers.len() > self.max_layers
            || upload.layers.capacity() > self.max_layers
            || upload.manifest.len() > self.max_document_bytes
            || upload.configuration.len() > self.max_document_bytes
        {
            return Err(exhausted());
        }
        let maximum = component_limit
            .checked_add(self.max_auxiliary_bytes)
            .ok_or_else(exhausted)?;
        let mut bytes = upload
            .manifest
            .capacity()
            .checked_add(upload.configuration.capacity())
            .ok_or_else(exhausted)?;
        for (name, data) in &upload.layers {
            if name.len() > 256 || name.capacity() > 256 {
                return Err(exhausted());
            }
            bytes = bytes
                .checked_add(name.capacity())
                .and_then(|sum| sum.checked_add(data.capacity()))
                .ok_or_else(exhausted)?;
        }
        for entries in [&upload.signatures, &upload.provenance, &upload.sboms] {
            if entries.len() > self.max_evidence_per_kind
                || entries.capacity() > self.max_evidence_per_kind
            {
                return Err(exhausted());
            }
            for entry in entries {
                if entry.manifest.len() > self.max_document_bytes
                    || entry.configuration.len() > self.max_document_bytes
                {
                    return Err(exhausted());
                }
                for data in [&entry.manifest, &entry.configuration, &entry.payload] {
                    bytes = bytes.checked_add(data.capacity()).ok_or_else(exhausted)?;
                }
            }
        }
        if bytes > maximum {
            return Err(exhausted());
        }
        Ok(())
    }

    pub(crate) fn check_binding(self, binding: &AdmissionBinding) -> Result<(), PlatformError> {
        if binding.tenant.0.is_empty()
            || binding.tenant.0.len() > 128
            || binding.tenant.0.capacity() > 128
            || !binding.tenant.0.is_ascii()
            || binding.tenant.0.bytes().any(|b| b.is_ascii_control())
            || binding.receipt.is_empty()
            || binding.receipt.capacity() > self.max_receipt_bytes
            || binding
                .release
                .0
                .parse::<latent_core::ArtifactBlobDigest>()
                .is_err()
        {
            return Err(exhausted());
        }
        Ok(())
    }
}
pub(super) fn exhausted() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::ResourceExhausted,
        message: "admission-storage-limit".to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

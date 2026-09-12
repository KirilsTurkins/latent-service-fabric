use latent_core::PlatformError;

use super::SbomEvidenceRef;

const MAX_PAYLOAD: usize = 1024 * 1024;
const MAX_MANIFEST: usize = 4096;
const MAX_REFERRERS: usize = 8;
const MAX_TOTAL: usize = MAX_REFERRERS * (MAX_PAYLOAD + MAX_MANIFEST + 2);

#[derive(Debug, Clone, Copy)]
pub struct SbomEvidenceLimits {
    pub max_referrers: usize,
    pub max_manifest_bytes: usize,
    pub max_payload_bytes: usize,
    pub max_total_bytes: usize,
}

impl Default for SbomEvidenceLimits {
    fn default() -> Self {
        Self {
            max_referrers: MAX_REFERRERS,
            max_manifest_bytes: MAX_MANIFEST,
            max_payload_bytes: MAX_PAYLOAD,
            max_total_bytes: MAX_TOTAL,
        }
    }
}

impl SbomEvidenceLimits {
    pub(crate) fn validate(self) -> Result<(), PlatformError> {
        for (value, maximum) in [
            (self.max_referrers, MAX_REFERRERS),
            (self.max_manifest_bytes, MAX_MANIFEST),
            (self.max_payload_bytes, MAX_PAYLOAD),
            (self.max_total_bytes, MAX_TOTAL),
        ] {
            if value == 0 || value > maximum {
                return Err(crate::invalid("invalid-sbom-evidence-limits"));
            }
        }
        Ok(())
    }

    pub(crate) fn check_one(self, evidence: SbomEvidenceRef<'_>) -> Result<(), PlatformError> {
        self.validate()?;
        if evidence.manifest.len() > self.max_manifest_bytes
            || evidence.payload.len() > self.max_payload_bytes
            || evidence.config.len() > 2
        {
            return Err(crate::exceeded("sbom-evidence-byte-limit"));
        }
        let total = evidence.manifest.len() + evidence.payload.len() + evidence.config.len();
        if total > self.max_total_bytes {
            return Err(crate::exceeded("sbom-evidence-total-limit"));
        }
        Ok(())
    }

    pub(crate) fn check_all(self, evidence: &[SbomEvidenceRef<'_>]) -> Result<(), PlatformError> {
        self.validate()?;
        if evidence.len() > self.max_referrers {
            return Err(crate::exceeded("sbom-evidence-count-limit"));
        }
        let mut total = 0_usize;
        let mut invalid_size = false;
        let mut invalid_total = false;
        for entry in evidence {
            invalid_size |= entry.manifest.len() > self.max_manifest_bytes
                || entry.payload.len() > self.max_payload_bytes
                || entry.config.len() > 2;
            for size in [
                entry.manifest.len(),
                entry.payload.len(),
                entry.config.len(),
            ] {
                if let Some(next) = total.checked_add(size) {
                    total = next;
                } else {
                    invalid_total = true;
                }
            }
        }
        if invalid_size {
            return Err(crate::exceeded("sbom-evidence-byte-limit"));
        }
        if invalid_total || total > self.max_total_bytes {
            return Err(crate::exceeded("sbom-evidence-total-limit"));
        }
        Ok(())
    }
}

use crate::{SignatureFailure, SignatureResult};

/// Per-document/per-owner bounds. Callers additionally bound concurrent work and
/// the number of retained evidence/proof objects; this owner has no worker queue.
#[derive(Debug, Clone, Copy)]
pub struct ProvenanceLimits {
    pub max_envelope_bytes: usize,
    pub max_payload_bytes: usize,
    pub max_materials: usize,
    pub max_policy_bytes: usize,
    pub max_keys: usize,
    pub max_requirements: usize,
    pub max_revoked_keys: usize,
    pub max_revoked_builders: usize,
}
impl Default for ProvenanceLimits {
    fn default() -> Self {
        Self {
            max_envelope_bytes: 49_152,
            max_payload_bytes: 32_768,
            max_materials: 64,
            max_policy_bytes: 65_536,
            max_keys: 64,
            max_requirements: 64,
            max_revoked_keys: 256,
            max_revoked_builders: 64,
        }
    }
}
impl ProvenanceLimits {
    pub(crate) fn validate(self) -> SignatureResult<()> {
        for (value, maximum) in [
            (self.max_envelope_bytes, 49_152),
            (self.max_payload_bytes, 32_768),
            (self.max_materials, 64),
            (self.max_policy_bytes, 65_536),
            (self.max_keys, 256),
            (self.max_requirements, 256),
            (self.max_revoked_keys, 256),
            (self.max_revoked_builders, 256),
        ] {
            if value == 0 || value > maximum {
                return Err(SignatureFailure::InvalidLimits.into());
            }
        }
        Ok(())
    }
}

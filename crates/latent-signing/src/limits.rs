use crate::{SignatureFailure, SignatureResult};

/// Bounded per-operation and per-verifier ownership; values may lower the hard
/// profile ceilings. There is no internal verification cache or worker queue.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SignatureLimits {
    pub max_envelope_bytes: usize,
    pub max_payload_bytes: usize,
    pub max_policy_bytes: usize,
    pub max_revocation_bytes: usize,
    pub max_keys: usize,
    pub max_revoked_keys: usize,
    pub max_revoked_publishers: usize,
}

impl Default for SignatureLimits {
    fn default() -> Self {
        Self {
            max_envelope_bytes: 4096,
            max_payload_bytes: 2048,
            max_policy_bytes: 65_536,
            max_revocation_bytes: 65_536,
            max_keys: 64,
            max_revoked_keys: 256,
            max_revoked_publishers: 64,
        }
    }
}

impl SignatureLimits {
    pub fn validate(self) -> SignatureResult<()> {
        for (actual, maximum) in [
            (self.max_envelope_bytes, 4096),
            (self.max_payload_bytes, 2048),
            (self.max_policy_bytes, 65_536),
            (self.max_revocation_bytes, 65_536),
            (self.max_keys, 256),
            (self.max_revoked_keys, 256),
            (self.max_revoked_publishers, 256),
        ] {
            if actual == 0 || actual > maximum {
                return Err(SignatureFailure::InvalidLimits.into());
            }
        }
        Ok(())
    }
}

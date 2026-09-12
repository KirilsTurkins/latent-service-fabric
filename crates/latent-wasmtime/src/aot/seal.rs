use super::ownership::OutputPermit;
use super::supervisor::CompletedAotJob;
use super::{blob, error, exhausted, invalid, mismatch, AotCompatibilityKey, AotCompilerLimits};
use latent_core::{ArtifactBlobDigest, PlatformError, PlatformErrorCode};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::fmt;
use zeroize::Zeroizing;

const MAX_COMPILER_ID_BYTES: usize = 1024;
const MAX_RECEIPT_BYTES: usize = 8192;

/// Host-owned local authentication key. No secret Clone/equality/export API.
/// Its protected provisioning location must be outside the cache and sandbox.
pub struct TrustedAotCompilerAuthority {
    compiler_identity: Box<str>,
    seal_key: Zeroizing<[u8; 32]>,
    limits: AotCompilerLimits,
}
impl TrustedAotCompilerAuthority {
    pub fn new(
        compiler_identity: &str,
        seal_key: Zeroizing<[u8; 32]>,
        limits: AotCompilerLimits,
    ) -> Result<Self, PlatformError> {
        let limits = limits.validate()?;
        limits.identity(compiler_identity)?;
        if compiler_identity.len() > MAX_COMPILER_ID_BYTES {
            return Err(exhausted());
        }
        if seal_key.iter().all(|byte| *byte == 0) {
            return Err(invalid());
        }
        Ok(Self {
            compiler_identity: compiler_identity.into(),
            seal_key,
            limits,
        })
    }
    /// Only the supervisor can construct `CompletedAotJob` after its checked
    /// source, isolated child, output protocol and actual cleanup have succeeded.
    pub(crate) fn seal_completed(
        &self,
        completed: CompletedAotJob,
    ) -> Result<TrustedAotOutput, PlatformError> {
        let (compatibility, output, permit) = completed.into_parts();
        let owned = PendingBytes { output, permit };
        if owned.output.is_empty()
            || owned.output.len() > self.limits.maximum_output_bytes
            || owned.output.capacity() > owned.permit.reserved_bytes()
        {
            return Err(exhausted());
        }
        let output_digest = blob(Sha256::digest(&owned.output).into());
        let seal = self.seal_value(&compatibility, &output_digest, owned.output.len());
        let receipt = serde_json::to_vec(&Receipt {
            format_version: 1,
            compatibility: &compatibility,
            output_digest: output_digest.as_str(),
            output_size: owned.output.len() as u64,
            compiler_identity: &self.compiler_identity,
            seal: seal.as_bytes(),
        })
        .map_err(|_| invalid())?;
        if receipt.len() > MAX_RECEIPT_BYTES {
            return Err(exhausted());
        }
        let PendingBytes { output, permit } = owned;
        Ok(TrustedAotOutput {
            output: output.into_boxed_slice(),
            compatibility,
            output_digest,
            compiler_identity: self.compiler_identity.clone(),
            seal,
            receipt: receipt.into_boxed_slice(),
            _permit: permit,
        })
    }
    /// Checks exact local compilation provenance; never grants release eligibility
    /// or authorizes a native load without the loader's current catalog checks.
    pub fn verify(
        &self,
        output: &TrustedAotOutput,
        expected: &AotCompatibilityKey,
    ) -> Result<(), PlatformError> {
        if output.compatibility != *expected || output.compiler_identity != self.compiler_identity {
            return Err(mismatch());
        }
        if output.output.is_empty() || output.output.len() > self.limits.maximum_output_bytes {
            return Err(exhausted());
        }
        let actual = blob(Sha256::digest(&output.output).into());
        if actual != output.output_digest {
            return Err(error(
                PlatformErrorCode::CorruptArtifact,
                "aot-output-digest-mismatch",
            ));
        }
        // blake3::Hash equality is constant-time. Never compare raw MAC arrays.
        if self.seal_value(expected, &actual, output.output.len()) != output.seal {
            return Err(mismatch());
        }
        Ok(())
    }
    fn seal_value(
        &self,
        compatibility: &AotCompatibilityKey,
        output_digest: &ArtifactBlobDigest,
        output_size: usize,
    ) -> blake3::Hash {
        let mut hasher = blake3::Hasher::new_keyed(&self.seal_key);
        hasher.update(b"lsf-aot-output-seal-v2\0");
        for bytes in [
            compatibility.digest().as_str().as_bytes(),
            output_digest.as_str().as_bytes(),
            &(output_size as u64).to_le_bytes(),
            self.compiler_identity.as_bytes(),
        ] {
            hasher.update(&(bytes.len() as u64).to_le_bytes());
            hasher.update(bytes);
        }
        hasher.finalize()
    }
}
impl fmt::Debug for TrustedAotCompilerAuthority {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("TrustedAotCompilerAuthority")
            .field("compiler_identity", &self.compiler_identity)
            .field("seal_key", &"[redacted]")
            .field("limits", &self.limits)
            .finish()
    }
}

// Declaration order refunds capacity only after the actual owned bytes drop,
// including every validation/receipt-encoding error before final output adoption.
struct PendingBytes {
    output: Vec<u8>,
    permit: OutputPermit,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Receipt<'a> {
    format_version: u32,
    compatibility: &'a AotCompatibilityKey,
    output_digest: &'a str,
    output_size: u64,
    compiler_identity: &'a str,
    seal: &'a [u8; 32],
}

/// Immutable native bytes with exact provenance and a retained capacity owner.
/// It is neither cloneable nor constructible/deserializable by public callers.
pub struct TrustedAotOutput {
    output: Box<[u8]>,
    compatibility: AotCompatibilityKey,
    output_digest: ArtifactBlobDigest,
    compiler_identity: Box<str>,
    seal: blake3::Hash,
    receipt: Box<[u8]>,
    _permit: OutputPermit,
}
impl TrustedAotOutput {
    #[must_use]
    pub fn compatibility(&self) -> &AotCompatibilityKey {
        &self.compatibility
    }
    #[must_use]
    pub fn output(&self) -> &[u8] {
        &self.output
    }
    #[must_use]
    pub fn output_digest(&self) -> &ArtifactBlobDigest {
        &self.output_digest
    }
    #[must_use]
    pub fn compiler_identity(&self) -> &str {
        &self.compiler_identity
    }
    /// Bounded exact receipt for future local persistent-cache storage. A receipt
    /// alone is untrusted data; only the configured private key can authenticate it.
    #[must_use]
    pub fn receipt(&self) -> &[u8] {
        &self.receipt
    }
}
impl fmt::Debug for TrustedAotOutput {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("TrustedAotOutput")
            .field("compatibility", &self.compatibility)
            .field("output_digest", &self.output_digest)
            .field("output_bytes", &self.output.len())
            .field("compiler_identity", &self.compiler_identity)
            .finish_non_exhaustive()
    }
}

#[cfg(test)]
mod tests;

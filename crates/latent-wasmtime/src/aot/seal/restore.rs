//! Private receipt authentication is separate from authenticated byte ownership.

mod json;
mod model;

use super::{TrustedAotCompilerAuthority, TrustedAotOutput, MAX_RECEIPT_BYTES};
use crate::aot::supervisor::AotPreparedInput;
use crate::aot::{blob, error, exhausted, mismatch, AotCompatibilityKey};
use latent_artifacts::RawArtifactBytes;
use latent_core::{ArtifactBlobDigest, PlatformError, PlatformErrorCode};
use sha2::{Digest, Sha256};

/// Owns only authenticated compact claims, and borrows no receipt read buffer.
/// The claimed raw-cache object is not accessed until this token exists.
pub(crate) struct AuthenticatedAotReceipt<'a> {
    input: &'a AotPreparedInput,
    verified: VerifiedReceipt,
}

struct VerifiedReceipt {
    output_digest: ArtifactBlobDigest,
    output_size: usize,
}

impl<'a> AuthenticatedAotReceipt<'a> {
    pub(crate) fn output_digest(&self) -> &ArtifactBlobDigest {
        &self.verified.output_digest
    }
    pub(crate) fn output_size(&self) -> usize {
        self.verified.output_size
    }

    pub(crate) fn authenticate_bytes(
        self,
        bytes: &'a RawArtifactBytes,
    ) -> Result<AuthenticatedNative<'a>, PlatformError> {
        self.input.check()?;
        self.verified.check_bytes(bytes.as_bytes())?;
        self.input.check()?;
        Ok(AuthenticatedNative {
            input: self.input,
            owner: NativeOwner::Cached(bytes),
        })
    }
}

impl VerifiedReceipt {
    fn check_bytes(&self, bytes: &[u8]) -> Result<(), PlatformError> {
        if bytes.len() != self.output_size
            || blob(Sha256::digest(bytes).into()) != self.output_digest
        {
            return Err(error(
                PlatformErrorCode::CorruptArtifact,
                "aot-output-digest-mismatch",
            ));
        }
        Ok(())
    }
}

/// No safe arbitrary-slice constructor, Clone or Deserialize. The loader borrows
/// the exact immutable owner whose real byte permit remains alive throughout.
pub(crate) struct AuthenticatedNative<'a> {
    input: &'a AotPreparedInput,
    owner: NativeOwner<'a>,
}
enum NativeOwner<'a> {
    Produced(&'a TrustedAotOutput),
    Cached(&'a RawArtifactBytes),
}
impl AuthenticatedNative<'_> {
    pub(crate) fn bytes(&self) -> &[u8] {
        match &self.owner {
            NativeOwner::Produced(output) => output.output(),
            NativeOwner::Cached(bytes) => bytes.as_bytes(),
        }
    }
    pub(crate) fn belongs_to(&self, input: &AotPreparedInput) -> bool {
        std::ptr::eq(self.input, input)
    }
}

impl TrustedAotCompilerAuthority {
    pub(crate) fn authenticate_receipt<'a>(
        &self,
        input: &'a AotPreparedInput,
        receipt: &[u8],
    ) -> Result<AuthenticatedAotReceipt<'a>, PlatformError> {
        input.check()?;
        let verified = self.verify_receipt(input.key(), receipt, input.maximum_output_bytes())?;
        input.check()?;
        Ok(AuthenticatedAotReceipt { input, verified })
    }

    pub(crate) fn authenticate_output<'a>(
        &self,
        input: &'a AotPreparedInput,
        output: &'a TrustedAotOutput,
    ) -> Result<AuthenticatedNative<'a>, PlatformError> {
        input.check()?;
        if output.output().len() > input.maximum_output_bytes() {
            return Err(exhausted());
        }
        self.verify(output, input.key())?;
        input.check()?;
        Ok(AuthenticatedNative {
            input,
            owner: NativeOwner::Produced(output),
        })
    }

    fn verify_receipt(
        &self,
        expected: &AotCompatibilityKey,
        receipt: &[u8],
        maximum_output_bytes: usize,
    ) -> Result<VerifiedReceipt, PlatformError> {
        if receipt.len() > MAX_RECEIPT_BYTES {
            return Err(invalid_receipt());
        }
        json::preflight(receipt)?;
        let receipt: model::Receipt =
            serde_json::from_slice(receipt).map_err(|_| invalid_receipt())?;
        if receipt.format_version != 1 {
            return Err(invalid_receipt());
        }
        if receipt.compiler_identity != self.compiler_identity.as_ref()
            || !receipt.compatibility.matches(expected)
        {
            return Err(mismatch());
        }
        let output_size = usize::try_from(receipt.output_size).map_err(|_| invalid_receipt())?;
        if output_size == 0 {
            return Err(invalid_receipt());
        }
        if output_size > self.limits.maximum_output_bytes || output_size > maximum_output_bytes {
            return Err(invalid_receipt());
        }
        let output_digest: ArtifactBlobDigest = receipt
            .output_digest
            .parse()
            .map_err(|_| invalid_receipt())?;
        // Hash equality is constant time. Authenticate the expected fresh key,
        // not a key supplied by this replaceable receipt, before exposing claims.
        let mac = blake3::Hash::from(receipt.seal);
        if self.seal_value(expected, &output_digest, output_size) != mac {
            return Err(mismatch());
        }
        Ok(VerifiedReceipt {
            output_digest,
            output_size,
        })
    }
}

fn invalid_receipt() -> PlatformError {
    error(PlatformErrorCode::CorruptArtifact, "aot-receipt-invalid")
}

#[cfg(test)]
mod tests;

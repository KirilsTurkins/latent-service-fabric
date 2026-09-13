//! The single strict Ed25519 profile used by signing and publisher verification.

use curve25519_dalek::scalar::Scalar;
use ed25519::Signature;
use ed25519_dalek::VerifyingKey;

use crate::{SignatureFailure, SignatureResult};

/// Accept canonical, non-small-order public keys using upstream point validation.
/// This profile does not claim complete torsion-free subgroup validation.
pub(crate) fn validate_public_key(bytes: &[u8; 32]) -> SignatureResult<VerifyingKey> {
    let key = VerifyingKey::from_bytes(bytes).map_err(|_| SignatureFailure::InvalidKey)?;
    if key.is_weak() || key.to_edwards().compress().as_bytes() != bytes {
        return Err(SignatureFailure::InvalidKey.into());
    }
    Ok(key)
}

/// Verify pure Ed25519 over the supplied exact message, including strict encoding.
pub(crate) fn verify_signature(
    public_key: &[u8; 32],
    message: &[u8],
    signature: &[u8; 64],
) -> SignatureResult<()> {
    let key = validate_public_key(public_key)?;
    let signature = Signature::from_bytes(signature);
    // Cargo features are additive: another consumer could enable Dalek's
    // `legacy_compatibility`, weakening its internal scalar parser. The upstream
    // canonical constructor remains strict regardless of that feature.
    if !bool::from(Scalar::from_canonical_bytes(*signature.s_bytes()).is_some()) {
        return Err(SignatureFailure::InvalidSignature.into());
    }
    // Dalek rejects small-order R and compares its canonical reconstructed R to
    // the received encoding, so an additional handwritten R check is unnecessary.
    key.verify_strict(message, &signature)
        .map_err(|_| SignatureFailure::InvalidSignature.into())
}

#[cfg(test)]
mod tests;

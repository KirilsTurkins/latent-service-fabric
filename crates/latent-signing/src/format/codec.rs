use super::{
    decode_claims, SignatureLimits, SignatureResult, UnverifiedSignature, SIGNATURE_PAYLOAD_TYPE,
};
use latent_core::ArtifactBlobDigest;

pub(super) fn inspect(
    envelope: &[u8],
    limits: SignatureLimits,
) -> SignatureResult<UnverifiedSignature> {
    limits.validate()?;
    let raw = crate::dsse::inspect(
        envelope,
        SIGNATURE_PAYLOAD_TYPE,
        limits.max_envelope_bytes,
        limits.max_payload_bytes,
    )?;
    let claims = decode_claims(&raw.payload, limits)?;
    Ok(UnverifiedSignature {
        claims,
        payload: raw.payload,
        signature: raw.signature,
        key_hint: raw.key_hint,
    })
}
pub(crate) fn encode_signature(
    payload: &[u8],
    signature: [u8; 64],
    key_hint: &ArtifactBlobDigest,
    limits: SignatureLimits,
) -> SignatureResult<Vec<u8>> {
    limits.validate()?;
    drop(decode_claims(payload, limits)?);
    crate::dsse::encode(
        SIGNATURE_PAYLOAD_TYPE,
        payload,
        signature,
        key_hint,
        limits.max_envelope_bytes,
        limits.max_payload_bytes,
    )
}
pub(crate) fn pae(payload_type: &str, payload: &[u8]) -> SignatureResult<Vec<u8>> {
    crate::dsse::pae(payload_type, payload, 2048)
}

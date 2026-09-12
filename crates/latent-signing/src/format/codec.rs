use super::{
    decode_claims, encode_json, preflight, SignatureFailure, SignatureLimits, SignatureResult,
    UnverifiedSignature, SIGNATURE_PAYLOAD_TYPE,
};
use base64::{engine::general_purpose::STANDARD, Engine};
use latent_core::ArtifactBlobDigest;
use serde::{Deserialize, Serialize};

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Envelope {
    payload_type: String,
    payload: String,
    signatures: Vec<Signature>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Signature {
    keyid: String,
    sig: String,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct EncodedEnvelope<'a> {
    payload_type: &'a str,
    payload: String,
    signatures: [EncodedSignature<'a>; 1],
}
#[derive(Serialize)]
struct EncodedSignature<'a> {
    keyid: &'a str,
    sig: String,
}

pub(super) fn inspect(
    envelope: &[u8],
    limits: SignatureLimits,
) -> SignatureResult<UnverifiedSignature> {
    limits.validate()?;
    preflight(envelope, limits.max_envelope_bytes)?;
    let envelope: Envelope =
        serde_json::from_slice(envelope).map_err(|_| SignatureFailure::MalformedEnvelope)?;
    if envelope.payload_type != SIGNATURE_PAYLOAD_TYPE {
        return Err(SignatureFailure::UnsupportedProfile.into());
    }
    let [signature]: [Signature; 1] = envelope
        .signatures
        .try_into()
        .map_err(|_| SignatureFailure::MalformedEnvelope)?;
    let key_hint = signature
        .keyid
        .parse()
        .map_err(|_| SignatureFailure::MalformedEnvelope)?;
    let signature = decode_base64(&signature.sig, 64)?
        .try_into()
        .map_err(|_| SignatureFailure::MalformedEnvelope)?;
    let payload = decode_base64(&envelope.payload, limits.max_payload_bytes)?;
    let claims = decode_claims(&payload, limits)?;
    Ok(UnverifiedSignature {
        claims,
        payload: payload.into_boxed_slice(),
        signature,
        key_hint,
    })
}

pub(crate) fn encode_signature(
    payload: &[u8],
    signature: [u8; 64],
    key_hint: &ArtifactBlobDigest,
    limits: SignatureLimits,
) -> SignatureResult<Vec<u8>> {
    limits.validate()?;
    // Reject malformed/oversized typed inputs before base64 creates owned strings.
    drop(decode_claims(payload, limits)?);
    let encoded_size =
        base64::encoded_len(payload.len(), true).ok_or(SignatureFailure::ResourceLimit)?;
    let overhead = br#"{"payloadType":"","payload":"","signatures":[{"keyid":"","sig":""}]}"#.len()
        + SIGNATURE_PAYLOAD_TYPE.len()
        + key_hint.as_str().len()
        + 88; // Exactly 64 signature bytes in padded standard base64.
    if encoded_size + overhead > limits.max_envelope_bytes {
        return Err(SignatureFailure::ResourceLimit.into());
    }
    encode_json(
        &EncodedEnvelope {
            payload_type: SIGNATURE_PAYLOAD_TYPE,
            payload: STANDARD.encode(payload),
            signatures: [EncodedSignature {
                keyid: key_hint.as_str(),
                sig: STANDARD.encode(signature),
            }],
        },
        limits.max_envelope_bytes,
    )
}

/// DSSE PAE uses UTF-8 byte counts and does not normalize the payload. This
/// crate-private primitive is bounded even when called with another test type.
pub(crate) fn pae(payload_type: &str, payload: &[u8]) -> SignatureResult<Vec<u8>> {
    if payload_type.is_empty() || payload_type.len() > 128 || payload.len() > 2048 {
        return Err(SignatureFailure::ResourceLimit.into());
    }
    let prefix = format!(
        "DSSEv1 {} {payload_type} {} ",
        payload_type.len(),
        payload.len()
    );
    let mut bytes = Vec::new();
    bytes
        .try_reserve_exact(prefix.len() + payload.len())
        .map_err(|_| SignatureFailure::ResourceLimit)?;
    bytes.extend_from_slice(prefix.as_bytes());
    bytes.extend_from_slice(payload);
    Ok(bytes)
}

fn decode_base64(value: &str, maximum: usize) -> SignatureResult<Vec<u8>> {
    if !value.len().is_multiple_of(4) {
        return Err(SignatureFailure::MalformedEnvelope.into());
    }
    let padding = value.bytes().rev().take_while(|byte| *byte == b'=').count();
    if padding > 2 {
        return Err(SignatureFailure::MalformedEnvelope.into());
    }
    let size = (value.len() / 4 * 3)
        .checked_sub(padding)
        .ok_or(SignatureFailure::MalformedEnvelope)?;
    if size > maximum {
        return Err(SignatureFailure::ResourceLimit.into());
    }
    let mut decoded = Vec::new();
    decoded
        .try_reserve_exact(size)
        .map_err(|_| SignatureFailure::ResourceLimit)?;
    decoded.resize(size, 0);
    // STANDARD requires canonical padding and rejects nonzero discarded bits.
    let actual = STANDARD
        .decode_slice(value, &mut decoded)
        .map_err(|_| SignatureFailure::MalformedEnvelope)?;
    if actual != size {
        return Err(SignatureFailure::MalformedEnvelope.into());
    }
    Ok(decoded)
}

//! Raw DSSE mechanics with explicit purpose and finite limits, without authority.
use crate::{provenance::json, SignatureFailure, SignatureResult};
use base64::{engine::general_purpose::STANDARD, Engine};
use latent_core::ArtifactBlobDigest;
use serde::{Deserialize, Serialize};

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Envelope {
    payload_type: String,
    payload: String,
    signatures: [Signature; 1],
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Signature {
    keyid: String,
    sig: String,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Output<'a> {
    payload_type: &'a str,
    payload: String,
    signatures: [SignatureOutput<'a>; 1],
}
#[derive(Serialize)]
struct SignatureOutput<'a> {
    keyid: &'a str,
    sig: String,
}
pub(crate) struct RawEnvelope {
    pub(crate) payload: Box<[u8]>,
    pub(crate) signature: [u8; 64],
    pub(crate) key_hint: ArtifactBlobDigest,
}

pub(crate) fn inspect(
    bytes: &[u8],
    purpose: &str,
    envelope_max: usize,
    payload_max: usize,
) -> SignatureResult<RawEnvelope> {
    bounds(purpose, envelope_max, payload_max)?;
    json::preflight(bytes, envelope_max, 1, envelope_max).map_err(|error| {
        if error.reason() == SignatureFailure::MalformedProvenance {
            SignatureFailure::MalformedEnvelope.into()
        } else {
            error
        }
    })?;
    let envelope: Envelope =
        serde_json::from_slice(bytes).map_err(|_| SignatureFailure::MalformedEnvelope)?;
    if envelope.payload_type != purpose {
        return Err(SignatureFailure::UnsupportedProfile.into());
    }
    let [signature] = envelope.signatures;
    let key_hint = signature
        .keyid
        .parse()
        .map_err(|_| SignatureFailure::MalformedEnvelope)?;
    let signature = decode_base64(&signature.sig, 64)?
        .try_into()
        .map_err(|_| SignatureFailure::MalformedEnvelope)?;
    let payload = decode_base64(&envelope.payload, payload_max)?.into_boxed_slice();
    Ok(RawEnvelope {
        payload,
        signature,
        key_hint,
    })
}
pub(crate) fn encode(
    purpose: &str,
    payload: &[u8],
    signature: [u8; 64],
    key: &ArtifactBlobDigest,
    envelope_max: usize,
    payload_max: usize,
) -> SignatureResult<Vec<u8>> {
    bounds(purpose, envelope_max, payload_max)?;
    if payload.len() > payload_max {
        return Err(SignatureFailure::ResourceLimit.into());
    }
    let encoded_size =
        base64::encoded_len(payload.len(), true).ok_or(SignatureFailure::ResourceLimit)?;
    let overhead = br#"{"payloadType":"","payload":"","signatures":[{"keyid":"","sig":""}]}"#.len()
        + purpose.len()
        + key.as_str().len()
        + 88;
    if encoded_size + overhead > envelope_max {
        return Err(SignatureFailure::ResourceLimit.into());
    }
    json::encode(
        &Output {
            payload_type: purpose,
            payload: STANDARD.encode(payload),
            signatures: [SignatureOutput {
                keyid: key.as_str(),
                sig: STANDARD.encode(signature),
            }],
        },
        envelope_max,
    )
}
fn bounds(purpose: &str, envelope_max: usize, payload_max: usize) -> SignatureResult<()> {
    if purpose.is_empty()
        || purpose.len() > 128
        || envelope_max == 0
        || envelope_max > 49_152
        || payload_max == 0
        || payload_max > 32_768
    {
        return Err(SignatureFailure::InvalidLimits.into());
    }
    Ok(())
}
pub(crate) fn pae(purpose: &str, payload: &[u8], maximum: usize) -> SignatureResult<Vec<u8>> {
    if purpose.is_empty()
        || purpose.len() > 128
        || maximum == 0
        || maximum > 32_768
        || payload.len() > maximum
    {
        return Err(SignatureFailure::ResourceLimit.into());
    }
    let prefix = format!("DSSEv1 {} {purpose} {} ", purpose.len(), payload.len());
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
    let padding = value.bytes().rev().take_while(|b| *b == b'=').count();
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
    let actual = STANDARD
        .decode_slice(value, &mut decoded)
        .map_err(|_| SignatureFailure::MalformedEnvelope)?;
    if actual != size {
        return Err(SignatureFailure::MalformedEnvelope.into());
    }
    Ok(decoded)
}

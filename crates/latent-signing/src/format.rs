//! Closed LSF signature profile using DSSE pre-authentication encoding.

mod codec;
mod json;
#[cfg(test)]
mod tests;

pub(crate) use codec::{encode_signature, pae};
pub(crate) use json::{encode_json, map_package_error, preflight};

use crate::{SignatureFailure, SignatureLimits, SignatureResult, MAX_SIGNATURE_LIFETIME_SECONDS};
use latent_artifacts::package::{PackageLimits, PackageSubject, OCI_MANIFEST_MEDIA_TYPE};
use latent_core::{ArtifactBlobDigest, PublisherId};
use serde::{Deserialize, Serialize};
use std::fmt;

pub const SIGNATURE_PAYLOAD_TYPE: &str = "application/vnd.latent.package-signature.v1+json";

/// Signed validity interval `[issued_at, expires_at)`, in Unix seconds.
/// Syntax inspection does not establish whether this interval is current.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SignatureValidity {
    pub issued_at: u64,
    pub expires_at: u64,
}

#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct SignatureClaims {
    pub(crate) format_version: u32,
    #[serde(with = "publisher_id")]
    pub(crate) publisher_id: PublisherId,
    pub(crate) subject: PackageSubject,
    pub(crate) issued_at: u64,
    pub(crate) expires_at: u64,
}

/// Bounded syntax inspection only. No publisher identity or signature authority
/// has been established; only the verifier can produce a trusted proof.
pub struct UnverifiedSignature {
    pub(crate) claims: SignatureClaims,
    pub(crate) payload: Box<[u8]>,
    pub(crate) signature: [u8; 64],
    pub(crate) key_hint: ArtifactBlobDigest,
}

impl UnverifiedSignature {
    #[must_use]
    pub fn publisher_id(&self) -> &PublisherId {
        &self.claims.publisher_id
    }
    #[must_use]
    pub fn subject(&self) -> &PackageSubject {
        &self.claims.subject
    }
    #[must_use]
    pub fn validity(&self) -> SignatureValidity {
        SignatureValidity {
            issued_at: self.claims.issued_at,
            expires_at: self.claims.expires_at,
        }
    }
    /// The original decoded claims bytes, without JSON normalization.
    #[must_use]
    pub fn payload_bytes(&self) -> &[u8] {
        &self.payload
    }
    /// An unauthenticated key-selection hint, never a publisher trust anchor.
    #[must_use]
    pub fn key_hint(&self) -> &ArtifactBlobDigest {
        &self.key_hint
    }
}

impl fmt::Debug for UnverifiedSignature {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("UnverifiedSignature")
            .field("payload_bytes", &self.payload.len())
            .finish_non_exhaustive()
    }
}

pub fn inspect_signature(
    envelope: &[u8],
    limits: SignatureLimits,
) -> SignatureResult<UnverifiedSignature> {
    codec::inspect(envelope, limits)
}

pub(crate) fn encode_claims(
    claims: &SignatureClaims,
    limits: SignatureLimits,
) -> SignatureResult<Vec<u8>> {
    limits.validate()?;
    validate_claims(claims)?;
    encode_json(claims, limits.max_payload_bytes)
}

pub(crate) fn decode_claims(
    payload: &[u8],
    limits: SignatureLimits,
) -> SignatureResult<SignatureClaims> {
    limits.validate()?;
    preflight(payload, limits.max_payload_bytes)?;
    let claims: SignatureClaims =
        serde_json::from_slice(payload).map_err(|_| SignatureFailure::MalformedEnvelope)?;
    validate_claims(&claims)?;
    Ok(claims)
}

fn validate_claims(claims: &SignatureClaims) -> SignatureResult<()> {
    if claims.format_version != 1 {
        return Err(SignatureFailure::UnsupportedProfile.into());
    }
    validate_publisher_id(&claims.publisher_id.0)?;
    validate_subject(&claims.subject)?;
    validate_validity(SignatureValidity {
        issued_at: claims.issued_at,
        expires_at: claims.expires_at,
    })
}

pub(crate) fn validate_publisher_id(value: &str) -> SignatureResult<()> {
    if value.len() > 128 {
        return Err(SignatureFailure::ResourceLimit.into());
    }
    if value.is_empty()
        || !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._:/@-".contains(&b))
    {
        return Err(SignatureFailure::MalformedEnvelope.into());
    }
    Ok(())
}

pub(crate) fn validate_subject(subject: &PackageSubject) -> SignatureResult<()> {
    if subject.media_type != OCI_MANIFEST_MEDIA_TYPE
        || subject.size == 0
        || subject.size > PackageLimits::default().max_document_bytes as u64
    {
        return Err(SignatureFailure::InvalidSubject.into());
    }
    Ok(())
}

pub(crate) fn validate_validity(validity: SignatureValidity) -> SignatureResult<()> {
    if !validity
        .expires_at
        .checked_sub(validity.issued_at)
        .is_some_and(|duration| duration > 0 && duration <= MAX_SIGNATURE_LIFETIME_SECONDS)
    {
        return Err(SignatureFailure::InvalidValidity.into());
    }
    Ok(())
}

mod publisher_id {
    use latent_core::PublisherId;
    use serde::Deserialize;
    pub(super) fn serialize<S: serde::Serializer>(
        id: &PublisherId,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&id.0)
    }
    pub(super) fn deserialize<'de, D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> Result<PublisherId, D::Error> {
        String::deserialize(deserializer).map(PublisherId)
    }
}

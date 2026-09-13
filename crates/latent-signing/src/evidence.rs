#[cfg(test)]
mod tests;

use crate::{
    format::{encode_json, map_package_error, preflight},
    inspect_signature, PackageSigningSubject, SignatureFailure, SignatureLimits, SignatureResult,
    UnverifiedSignature,
};
use latent_artifacts::package::{
    artifact_blob_digest, decode_referrer, package_digest, ArtifactDescriptor, EvidenceKind,
    PackageLimits, ReferrerManifest, EMPTY_CONFIG_MEDIA_TYPE, LAYER_PATH_ANNOTATION,
    LAYER_ROLE_ANNOTATION, OCI_MANIFEST_MEDIA_TYPE,
};
use latent_core::{ArtifactBlobDigest, PackageDigest};
use std::{collections::BTreeMap, fmt};

/// Detached signature bytes with a checked subject/content association.
/// Construction and attachment do not establish cryptographic publisher trust.
pub struct SignatureEvidence {
    manifest: Box<[u8]>,
    payload: Box<[u8]>,
    digest: PackageDigest,
}

/// Borrowed, untrusted evidence supplied to the verifier. All byte slices are
/// independently bounded and checked before any association becomes trusted.
#[derive(Clone, Copy)]
pub struct SignatureEvidenceRef<'a> {
    pub manifest: &'a [u8],
    pub config: &'a [u8],
    pub payload: &'a [u8],
}

impl SignatureEvidence {
    pub fn from_envelope(
        subject: &PackageSigningSubject,
        envelope: &[u8],
        limits: SignatureLimits,
    ) -> SignatureResult<Self> {
        let inspected = inspect_signature(envelope, limits)?;
        if inspected.subject() != subject.subject() {
            return Err(SignatureFailure::SubjectMismatch.into());
        }
        let manifest = ReferrerManifest {
            schema_version: 2,
            media_type: OCI_MANIFEST_MEDIA_TYPE.to_owned(),
            artifact_type: EvidenceKind::Signature.artifact_type().to_owned(),
            config: ArtifactDescriptor {
                media_type: EMPTY_CONFIG_MEDIA_TYPE.to_owned(),
                digest: artifact_blob_digest(b"{}"),
                size: 2,
                annotations: None,
            },
            layers: vec![ArtifactDescriptor {
                media_type: EvidenceKind::Signature.payload_media_type().to_owned(),
                digest: artifact_blob_digest(envelope),
                size: envelope.len() as u64,
                annotations: Some(BTreeMap::from([
                    (
                        LAYER_PATH_ANNOTATION.to_owned(),
                        "evidence/signature.json".to_owned(),
                    ),
                    (LAYER_ROLE_ANNOTATION.to_owned(), "evidence".to_owned()),
                ])),
            }],
            subject: subject.subject().clone(),
            annotations: BTreeMap::new(),
        };
        // Subject size has the package's 256 KiB bound, independent of this
        // small referrer's 4 KiB serialized-document ceiling. All owned fields
        // above are constants or previously checked bounded identities.
        let manifest = encode_json(&manifest, limits.max_envelope_bytes)?;
        decode_referrer(&manifest, PackageLimits::default())
            .map_err(|error| map_package_error(&error, SignatureFailure::MalformedEnvelope))?;
        Ok(Self {
            digest: package_digest(&manifest),
            manifest: manifest.into_boxed_slice(),
            payload: envelope.into(),
        })
    }

    #[must_use]
    pub fn manifest_bytes(&self) -> &[u8] {
        &self.manifest
    }
    #[must_use]
    pub const fn config_bytes(&self) -> &[u8] {
        b"{}"
    }
    #[must_use]
    pub fn payload_bytes(&self) -> &[u8] {
        &self.payload
    }
    /// Identity of this exact detached referrer, distinct from its subject.
    #[must_use]
    pub fn digest(&self) -> &PackageDigest {
        &self.digest
    }
    #[must_use]
    pub fn as_ref(&self) -> SignatureEvidenceRef<'_> {
        SignatureEvidenceRef {
            manifest: &self.manifest,
            config: b"{}",
            payload: &self.payload,
        }
    }
}

impl fmt::Debug for SignatureEvidence {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("SignatureEvidence")
            .field("digest", &self.digest)
            .field("payload_bytes", &self.payload.len())
            .finish_non_exhaustive()
    }
}

pub(crate) struct InspectedSignatureEvidence {
    pub(crate) referrer_digest: PackageDigest,
    pub(crate) payload_digest: ArtifactBlobDigest,
    pub(crate) signature: UnverifiedSignature,
}

pub(crate) fn inspect_evidence(
    expected: &PackageSigningSubject,
    evidence: SignatureEvidenceRef<'_>,
    limits: SignatureLimits,
) -> SignatureResult<InspectedSignatureEvidence> {
    limits.validate()?;
    if evidence.manifest.len() > limits.max_envelope_bytes
        || evidence.payload.len() > limits.max_envelope_bytes
        || evidence.config.len() > 2
    {
        return Err(SignatureFailure::ResourceLimit.into());
    }
    if evidence.config != b"{}" {
        return Err(SignatureFailure::IntegrityMismatch.into());
    }
    preflight(evidence.manifest, limits.max_envelope_bytes)?;
    let manifest = decode_referrer(evidence.manifest, PackageLimits::default())
        .map_err(|error| map_package_error(&error, SignatureFailure::MalformedEnvelope))?;
    if manifest.artifact_type != EvidenceKind::Signature.artifact_type() {
        return Err(SignatureFailure::UnsupportedProfile.into());
    }
    if &manifest.subject != expected.subject() {
        return Err(SignatureFailure::SubjectMismatch.into());
    }
    let payload_digest = artifact_blob_digest(evidence.payload);
    let layer = &manifest.layers[0]; // Existing referrer codec enforces exactly one.
    if layer.digest != payload_digest || layer.size != evidence.payload.len() as u64 {
        return Err(SignatureFailure::IntegrityMismatch.into());
    }
    let signature = inspect_signature(evidence.payload, limits)?;
    if signature.subject() != expected.subject() {
        return Err(SignatureFailure::SubjectMismatch.into());
    }
    Ok(InspectedSignatureEvidence {
        referrer_digest: package_digest(evidence.manifest),
        payload_digest,
        signature,
    })
}

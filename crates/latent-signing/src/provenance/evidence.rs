use super::{codec::inspect_provenance, ProvenanceLimits, UnverifiedProvenance};
use crate::{
    format::{encode_json, map_package_error, preflight},
    PackageSigningSubject, SignatureFailure, SignatureResult,
};
use latent_artifacts::package::{
    artifact_blob_digest, decode_referrer, package_digest, ArtifactDescriptor, EvidenceKind,
    PackageKind, PackageLimits, ReferrerManifest, EMPTY_CONFIG_MEDIA_TYPE, LAYER_PATH_ANNOTATION,
    LAYER_ROLE_ANNOTATION, OCI_MANIFEST_MEDIA_TYPE,
};
use latent_core::{ArtifactBlobDigest, PackageDigest};
use std::{collections::BTreeMap, fmt};

pub struct ProvenanceEvidence {
    manifest: Box<[u8]>,
    payload: Box<[u8]>,
    digest: PackageDigest,
}
#[derive(Clone, Copy)]
pub struct ProvenanceEvidenceRef<'a> {
    pub manifest: &'a [u8],
    pub config: &'a [u8],
    pub payload: &'a [u8],
}
impl ProvenanceEvidence {
    /// Checks syntax/content association, without authenticating a builder.
    pub fn from_envelope(
        subject: &PackageSigningSubject,
        envelope: &[u8],
        limits: ProvenanceLimits,
    ) -> SignatureResult<Self> {
        let inspected = inspect_provenance(envelope, limits)?;
        validate_expected(subject, &inspected)?;
        let manifest = ReferrerManifest {
            schema_version: 2,
            media_type: OCI_MANIFEST_MEDIA_TYPE.to_owned(),
            artifact_type: EvidenceKind::Provenance.artifact_type().to_owned(),
            config: ArtifactDescriptor {
                media_type: EMPTY_CONFIG_MEDIA_TYPE.to_owned(),
                digest: artifact_blob_digest(b"{}"),
                size: 2,
                annotations: None,
            },
            layers: vec![ArtifactDescriptor {
                media_type: EvidenceKind::Provenance.payload_media_type().to_owned(),
                digest: artifact_blob_digest(envelope),
                size: envelope.len() as u64,
                annotations: Some(BTreeMap::from([
                    (
                        LAYER_PATH_ANNOTATION.to_owned(),
                        "evidence/provenance.json".to_owned(),
                    ),
                    (LAYER_ROLE_ANNOTATION.to_owned(), "evidence".to_owned()),
                ])),
            }],
            subject: subject.subject().clone(),
            annotations: BTreeMap::new(),
        };
        let manifest = encode_json(&manifest, 4096)?;
        decode_referrer(&manifest, PackageLimits::default())
            .map_err(|error| map_package_error(&error, SignatureFailure::MalformedProvenance))?;
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
    #[must_use]
    pub fn digest(&self) -> &PackageDigest {
        &self.digest
    }
    #[must_use]
    pub fn as_ref(&self) -> ProvenanceEvidenceRef<'_> {
        ProvenanceEvidenceRef {
            manifest: &self.manifest,
            config: b"{}",
            payload: &self.payload,
        }
    }
}
impl fmt::Debug for ProvenanceEvidence {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ProvenanceEvidence")
            .field("digest", &self.digest)
            .field("payload_bytes", &self.payload.len())
            .finish_non_exhaustive()
    }
}
pub(crate) struct InspectedProvenanceEvidence {
    pub(crate) referrer_digest: PackageDigest,
    pub(crate) payload_digest: ArtifactBlobDigest,
    pub(crate) provenance: UnverifiedProvenance,
}
pub(crate) fn inspect_evidence(
    expected: &PackageSigningSubject,
    evidence: ProvenanceEvidenceRef<'_>,
    limits: ProvenanceLimits,
) -> SignatureResult<InspectedProvenanceEvidence> {
    limits.validate()?;
    if evidence.manifest.len() > 4096
        || evidence.payload.len() > limits.max_envelope_bytes
        || evidence.config.len() > 2
    {
        return Err(SignatureFailure::ResourceLimit.into());
    }
    if evidence.config != b"{}" {
        return Err(SignatureFailure::IntegrityMismatch.into());
    }
    preflight(evidence.manifest, 4096)?;
    let manifest = decode_referrer(evidence.manifest, PackageLimits::default())
        .map_err(|error| map_package_error(&error, SignatureFailure::MalformedProvenance))?;
    if manifest.artifact_type != EvidenceKind::Provenance.artifact_type() {
        return Err(SignatureFailure::UnsupportedProfile.into());
    }
    if &manifest.subject != expected.subject() {
        return Err(SignatureFailure::SubjectMismatch.into());
    }
    let payload_digest = artifact_blob_digest(evidence.payload);
    let layer = &manifest.layers[0];
    if layer.digest != payload_digest || layer.size != evidence.payload.len() as u64 {
        return Err(SignatureFailure::IntegrityMismatch.into());
    }
    let provenance = inspect_provenance(evidence.payload, limits)?;
    validate_expected(expected, &provenance)?;
    Ok(InspectedProvenanceEvidence {
        referrer_digest: package_digest(evidence.manifest),
        payload_digest,
        provenance,
    })
}
fn validate_expected(
    expected: &PackageSigningSubject,
    provenance: &UnverifiedProvenance,
) -> SignatureResult<()> {
    if provenance.subject() != expected.subject() {
        return Err(SignatureFailure::SubjectMismatch.into());
    }
    validate_output(expected, provenance.observation())
}
pub(crate) fn validate_output(
    expected: &PackageSigningSubject,
    observation: &super::BuildObservation,
) -> SignatureResult<()> {
    if expected.kind() != PackageKind::Capsule {
        return Err(SignatureFailure::UnsupportedProfile.into());
    }
    if expected.component_digest().map(ArtifactBlobDigest::as_str)
        != Some(observation.component_digest.as_str())
        || expected.component_size() != Some(observation.component_size)
    {
        return Err(SignatureFailure::SubjectMismatch.into());
    }
    Ok(())
}

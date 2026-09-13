use super::{
    codec::decode_statement,
    evidence::validate_output,
    json,
    model::{Predicate, Sha256, Statement, Subject},
    validate_observation, BuildObservation, ProvenanceEvidence, ProvenanceLimits,
    PROVENANCE_PAYLOAD_TYPE, PROVENANCE_PREDICATE_TYPE, STATEMENT_TYPE,
};
use crate::{
    dsse,
    format::{validate_publisher_id, validate_validity},
    keys::import_key,
    PackageSigningSubject, SignatureFailure, SignatureResult, SignatureValidity,
};
use ed25519_dalek::{Signer, SigningKey};
use latent_artifacts::package::artifact_blob_digest;
use latent_core::ArtifactBlobDigest;
use std::fmt;
use zeroize::Zeroizing;

/// Host builder attestation signer. The approved builder is responsible for the
/// truth of its observations. A signed assertion does not prove sandboxing,
/// hermeticity, repository ownership or the absence of a malicious builder.
pub struct LocalBuilderSigner {
    key: SigningKey,
    builder_id: String,
    fingerprint: ArtifactBlobDigest,
}
impl LocalBuilderSigner {
    pub fn from_pkcs8(
        pkcs8: Zeroizing<Vec<u8>>,
        builder_id: String,
        approved_public_key: [u8; 32],
    ) -> SignatureResult<Self> {
        validate_publisher_id(&builder_id)?;
        let key = import_key(pkcs8, &approved_public_key)?;
        Ok(Self {
            key,
            builder_id: builder_id.into_boxed_str().into_string(),
            fingerprint: artifact_blob_digest(&approved_public_key),
        })
    }
    #[must_use]
    pub fn builder_id(&self) -> &str {
        &self.builder_id
    }
    #[must_use]
    pub fn key_fingerprint(&self) -> &ArtifactBlobDigest {
        &self.fingerprint
    }
    pub fn sign_build(
        &self,
        subject: &PackageSigningSubject,
        observation: &BuildObservation,
        validity: SignatureValidity,
        limits: ProvenanceLimits,
    ) -> SignatureResult<ProvenanceEvidence> {
        limits.validate()?;
        validate_observation(observation, limits)?;
        validate_output(subject, observation)?;
        validate_validity(validity)?;
        if validity.issued_at < observation.finished_at {
            return Err(SignatureFailure::InvalidValidity.into());
        }
        let statement = Statement {
            kind: STATEMENT_TYPE.to_owned(),
            subject: [Subject {
                name: "lsf-package".to_owned(),
                digest: Sha256 {
                    sha256: subject.subject().digest.as_str()[7..].to_owned(),
                },
            }],
            predicate_type: PROVENANCE_PREDICATE_TYPE.to_owned(),
            predicate: Predicate {
                format_version: 1,
                package_subject: subject.subject().clone(),
                builder_id: self.builder_id.clone(),
                issued_at: validity.issued_at,
                expires_at: validity.expires_at,
                observation: observation.clone(),
            },
        };
        let payload = json::encode(&statement, limits.max_payload_bytes)?;
        drop(decode_statement(&payload, limits)?);
        let signature = self
            .key
            .sign(&dsse::pae(
                PROVENANCE_PAYLOAD_TYPE,
                &payload,
                limits.max_payload_bytes,
            )?)
            .to_bytes();
        let envelope = dsse::encode(
            PROVENANCE_PAYLOAD_TYPE,
            &payload,
            signature,
            &self.fingerprint,
            limits.max_envelope_bytes,
            limits.max_payload_bytes,
        )?;
        ProvenanceEvidence::from_envelope(subject, &envelope, limits)
    }
}
impl fmt::Debug for LocalBuilderSigner {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("LocalBuilderSigner { private_key: [REDACTED] }")
    }
}

use super::{
    json, model::Statement, validate_observation, BuildObservation, ProvenanceLimits,
    PROVENANCE_PAYLOAD_TYPE, PROVENANCE_PREDICATE_TYPE, STATEMENT_TYPE,
};
use crate::{
    dsse,
    format::{validate_publisher_id, validate_subject, validate_validity},
    SignatureFailure, SignatureResult, SignatureValidity,
};
use latent_artifacts::package::PackageSubject;
use latent_core::ArtifactBlobDigest;
use std::fmt;

/// Inspected syntax and associations, without authenticated builder authority.
pub struct UnverifiedProvenance {
    pub(crate) statement: Statement,
    pub(crate) payload: Box<[u8]>,
    pub(crate) signature: [u8; 64],
    pub(crate) key_hint: ArtifactBlobDigest,
}
impl UnverifiedProvenance {
    #[must_use]
    pub fn subject(&self) -> &PackageSubject {
        &self.statement.predicate.package_subject
    }
    #[must_use]
    pub fn builder_id(&self) -> &str {
        &self.statement.predicate.builder_id
    }
    #[must_use]
    pub fn observation(&self) -> &BuildObservation {
        &self.statement.predicate.observation
    }
    #[must_use]
    pub fn payload_bytes(&self) -> &[u8] {
        &self.payload
    }
    #[must_use]
    pub fn key_hint(&self) -> &ArtifactBlobDigest {
        &self.key_hint
    }
    #[must_use]
    pub fn validity(&self) -> SignatureValidity {
        SignatureValidity {
            issued_at: self.statement.predicate.issued_at,
            expires_at: self.statement.predicate.expires_at,
        }
    }
}
impl fmt::Debug for UnverifiedProvenance {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("UnverifiedProvenance")
            .field("payload_bytes", &self.payload.len())
            .finish_non_exhaustive()
    }
}
pub fn inspect_provenance(
    envelope: &[u8],
    limits: ProvenanceLimits,
) -> SignatureResult<UnverifiedProvenance> {
    limits.validate()?;
    let raw = dsse::inspect(
        envelope,
        PROVENANCE_PAYLOAD_TYPE,
        limits.max_envelope_bytes,
        limits.max_payload_bytes,
    )?;
    let statement = decode_statement(&raw.payload, limits)?;
    Ok(UnverifiedProvenance {
        statement,
        payload: raw.payload,
        signature: raw.signature,
        key_hint: raw.key_hint,
    })
}
pub(crate) fn decode_statement(
    bytes: &[u8],
    limits: ProvenanceLimits,
) -> SignatureResult<Statement> {
    limits.validate()?;
    let statement: Statement = json::decode(bytes, limits.max_payload_bytes, limits.max_materials)?;
    if statement.kind != STATEMENT_TYPE
        || statement.predicate_type != PROVENANCE_PREDICATE_TYPE
        || statement.predicate.format_version != 1
    {
        return Err(SignatureFailure::UnsupportedProfile.into());
    }
    let predicate = &statement.predicate;
    validate_subject(&predicate.package_subject)?;
    validate_publisher_id(&predicate.builder_id)?;
    validate_validity(SignatureValidity {
        issued_at: predicate.issued_at,
        expires_at: predicate.expires_at,
    })?;
    validate_observation(&predicate.observation, limits)?;
    if predicate.issued_at < predicate.observation.finished_at {
        return Err(SignatureFailure::InvalidValidity.into());
    }
    if statement.subject[0].name != "lsf-package"
        || statement.subject[0].digest.sha256 != predicate.package_subject.digest.as_str()[7..]
    {
        return Err(SignatureFailure::SubjectMismatch.into());
    }
    Ok(statement)
}

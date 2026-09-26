//! Explicit componentless web-output provenance. Supplied-file assembly and
//! observed Angular compilation are independently approved build profiles.

mod angular;
mod model;
mod validate;

pub use model::{AngularBuildRecipe, WebAssemblyRecipe, WebBuildObservation, WebBuildRecipe};
pub(crate) use validate::validate_observation;

use crate::{
    provenance::{
        codec, json,
        model::{Predicate, Sha256, Statement, Subject},
        STATEMENT_TYPE,
    },
    PackageSigningSubject, ProvenanceLimits, SignatureFailure, SignatureResult, SignatureValidity,
    UnverifiedProvenance,
};

pub const WEB_ASSEMBLY_BUILD_TYPE: &str = "https://latent.dev/build/web-package-assembly/v1";
pub const ANGULAR_BUILD_TYPE: &str = "https://latent.dev/build/angular-component/v1";
pub const WEB_PROVENANCE_PREDICATE_TYPE: &str = "https://latent.dev/web-provenance/v1";

pub type UnverifiedWebProvenance = UnverifiedProvenance<WebBuildObservation>;

/// Inspect bounded syntax and output claims, without authenticating a builder.
pub fn inspect_web_provenance(
    envelope: &[u8],
    limits: ProvenanceLimits,
) -> SignatureResult<UnverifiedWebProvenance> {
    codec::inspect_as(
        envelope,
        limits,
        WEB_PROVENANCE_PREDICATE_TYPE,
        checked_finish,
    )
}

fn checked_finish(value: &WebBuildObservation, limits: ProvenanceLimits) -> SignatureResult<u64> {
    validate_observation(value, limits)?;
    Ok(value.finished_at)
}

pub(crate) fn validate_output(
    subject: &PackageSigningSubject,
    observation: &WebBuildObservation,
) -> SignatureResult<()> {
    let outputs = subject
        .web_outputs()
        .ok_or(SignatureFailure::UnsupportedProfile)?;
    if outputs.digest().as_str() != observation.outputs_digest
        || outputs.count() != observation.outputs_count
        || outputs.bytes() != observation.outputs_bytes
    {
        return Err(SignatureFailure::SubjectMismatch.into());
    }
    if let WebBuildRecipe::Angular(recipe) = &observation.parameters {
        let Some((digest, size)) = subject.renderer() else {
            return Err(SignatureFailure::SubjectMismatch.into());
        };
        if digest.as_str() != recipe.renderer_digest || size != recipe.renderer_size {
            return Err(SignatureFailure::SubjectMismatch.into());
        }
    }
    Ok(())
}

pub(crate) fn statement_bytes(
    subject: &PackageSigningSubject,
    builder_id: &str,
    observation: &WebBuildObservation,
    validity: SignatureValidity,
    limits: ProvenanceLimits,
) -> SignatureResult<Vec<u8>> {
    validate_observation(observation, limits)?;
    validate_output(subject, observation)?;
    crate::format::validate_validity(validity)?;
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
        predicate_type: WEB_PROVENANCE_PREDICATE_TYPE.to_owned(),
        predicate: Predicate {
            format_version: 1,
            package_subject: subject.subject().clone(),
            builder_id: builder_id.to_owned(),
            issued_at: validity.issued_at,
            expires_at: validity.expires_at,
            observation: observation.clone(),
        },
    };
    let payload = json::encode(&statement, limits.max_payload_bytes)?;
    drop(codec::decode_as(
        &payload,
        limits,
        WEB_PROVENANCE_PREDICATE_TYPE,
        checked_finish,
    )?);
    Ok(payload)
}

/// Decode bounded supplied observations. Only an independently authenticated,
/// currently approved builder can make them eligible for admission policy.
pub fn decode_web_build_observation(
    bytes: &[u8],
    limits: ProvenanceLimits,
) -> SignatureResult<WebBuildObservation> {
    limits.validate()?;
    let observation = json::decode(bytes, limits.max_payload_bytes, limits.max_materials)?;
    validate_observation(&observation, limits)?;
    Ok(observation)
}

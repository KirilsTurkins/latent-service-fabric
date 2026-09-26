use super::{VerifiedBuildProvenance, VerifiedWebBuildProvenance};
use crate::{
    builder_policy::{contains, requirements},
    crypto::verify_signature,
    dsse::pae,
    provenance::{evidence::InspectedProvenanceEvidence, PROVENANCE_PAYLOAD_TYPE},
    BuildSource, BuilderTrust, ProvenanceLimits, SignatureFailure, SignatureResult,
    UnverifiedProvenance, WebBuildObservation,
};

pub(super) fn authenticate(
    trust: &BuilderTrust,
    evidence: InspectedProvenanceEvidence,
    limits: ProvenanceLimits,
    now: u64,
) -> SignatureResult<VerifiedBuildProvenance> {
    let inspected = evidence.provenance;
    let observation = inspected.observation();
    let valid_until = authenticate_claims(
        trust,
        &inspected,
        ObservationPolicy {
            build_type: &observation.build_type,
            source: &observation.source,
            reproducibility: &observation.reproducibility,
        },
        limits,
        now,
    )?;
    let claims = inspected.statement.predicate;
    let component_digest = claims
        .observation
        .component_digest
        .parse()
        .map_err(|_| SignatureFailure::Internal)?;
    let source = claims.observation.source;
    Ok(VerifiedBuildProvenance {
        subject: claims.package_subject,
        component_digest,
        builder_id: claims.builder_id,
        key_fingerprint: inspected.key_hint,
        evidence_digest: evidence.referrer_digest,
        payload_digest: evidence.payload_digest,
        source_repository: source.repository,
        source_revision: source.revision,
        source_snapshot_digest: source
            .snapshot_digest
            .parse()
            .map_err(|_| SignatureFailure::Internal)?,
        state: trust.state_id().clone(),
        verified_at: now,
        valid_until,
    })
}

pub(super) fn authenticate_web(
    trust: &BuilderTrust,
    evidence: InspectedProvenanceEvidence<WebBuildObservation>,
    limits: ProvenanceLimits,
    now: u64,
) -> SignatureResult<VerifiedWebBuildProvenance> {
    let inspected = evidence.provenance;
    let observation = inspected.observation();
    let valid_until = authenticate_claims(
        trust,
        &inspected,
        ObservationPolicy {
            build_type: &observation.build_type,
            source: &observation.source,
            reproducibility: &observation.reproducibility,
        },
        limits,
        now,
    )?;
    let claims = inspected.statement.predicate;
    let observation = claims.observation;
    Ok(VerifiedWebBuildProvenance {
        subject: claims.package_subject,
        outputs_digest: observation
            .outputs_digest
            .parse()
            .map_err(|_| SignatureFailure::Internal)?,
        outputs_count: observation.outputs_count,
        outputs_bytes: observation.outputs_bytes,
        builder_id: claims.builder_id,
        key_fingerprint: inspected.key_hint,
        evidence_digest: evidence.referrer_digest,
        payload_digest: evidence.payload_digest,
        source_repository: observation.source.repository,
        source_revision: observation.source.revision,
        source_snapshot_digest: observation
            .source
            .snapshot_digest
            .parse()
            .map_err(|_| SignatureFailure::Internal)?,
        state: trust.state_id().clone(),
        verified_at: now,
        valid_until,
    })
}

#[derive(Clone, Copy)]
struct ObservationPolicy<'a> {
    build_type: &'a str,
    source: &'a BuildSource,
    reproducibility: &'a str,
}

/// Shared cryptographic, trust, source and time fence for both output models.
/// Output association has already been checked by the respective typed decoder.
fn authenticate_claims<T>(
    trust: &BuilderTrust,
    inspected: &UnverifiedProvenance<T>,
    observation: ObservationPolicy<'_>,
    limits: ProvenanceLimits,
    now: u64,
) -> SignatureResult<u64> {
    let key = trust
        .policy
        .keys
        .get(&inspected.key_hint)
        .ok_or(SignatureFailure::UnapprovedKey)?;
    verify_signature(
        &key.public_key,
        &pae(
            PROVENANCE_PAYLOAD_TYPE,
            &inspected.payload,
            limits.max_payload_bytes,
        )?,
        &inspected.signature,
    )?;
    let claims = &inspected.statement.predicate;
    if claims.builder_id != key.builder {
        return Err(SignatureFailure::UntrustedBuilder.into());
    }
    if !contains(key.valid_from, key.valid_until, claims.issued_at)
        || !contains(key.valid_from, key.valid_until, now)
    {
        return Err(SignatureFailure::KeyExpired.into());
    }
    if trust.revocations.keys.contains(&inspected.key_hint)
        || trust.revocations.builders.contains(&key.builder)
    {
        return Err(SignatureFailure::Revoked.into());
    }
    if !contains(claims.issued_at, claims.expires_at, now) {
        return Err(SignatureFailure::SignatureExpired.into());
    }
    let lifetime = claims
        .expires_at
        .checked_sub(claims.issued_at)
        .ok_or(SignatureFailure::InvalidValidity)?;
    if lifetime == 0 || lifetime > trust.policy.config.max_signature_lifetime_seconds {
        return Err(SignatureFailure::InvalidValidity.into());
    }
    requirements::authorize_source(
        &trust.policy.config.requirements,
        &key.builder,
        observation.build_type,
        observation.source,
        observation.reproducibility,
    )?;
    let proof_expiry = now
        .checked_add(trust.policy.config.max_proof_age_seconds)
        .ok_or(SignatureFailure::InvalidValidity)?;
    let valid_until = [
        claims.expires_at,
        key.valid_until,
        trust.policy.config.valid_until,
        trust.revocations.config.valid_until,
        proof_expiry,
    ]
    .into_iter()
    .min()
    .expect("fixed nonempty expiry list");
    Ok(valid_until)
}

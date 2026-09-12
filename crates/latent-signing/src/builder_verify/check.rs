use super::VerifiedBuildProvenance;
use crate::{
    builder_policy::{contains, requirements},
    crypto::verify_signature,
    dsse::pae,
    provenance::{evidence::InspectedProvenanceEvidence, PROVENANCE_PAYLOAD_TYPE},
    BuilderTrust, ProvenanceLimits, SignatureFailure, SignatureResult,
};

pub(super) fn authenticate(
    trust: &BuilderTrust,
    evidence: InspectedProvenanceEvidence,
    limits: ProvenanceLimits,
    now: u64,
) -> SignatureResult<VerifiedBuildProvenance> {
    let inspected = evidence.provenance;
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
    let claims = inspected.statement.predicate;
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
    requirements::authorize(
        &trust.policy.config.requirements,
        &key.builder,
        &claims.observation,
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
    let component_digest = claims
        .observation
        .component_digest
        .parse()
        .map_err(|_| SignatureFailure::Internal)?;
    let source = claims.observation.source;
    Ok(VerifiedBuildProvenance {
        subject: claims.package_subject,
        component_digest,
        builder_id: key.builder.clone(),
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

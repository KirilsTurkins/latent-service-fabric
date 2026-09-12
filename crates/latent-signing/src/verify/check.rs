use super::VerifiedPackageSignature;
use crate::{
    crypto::verify_signature,
    evidence::InspectedSignatureEvidence,
    format::{pae, SIGNATURE_PAYLOAD_TYPE},
    policy::contains,
    PublisherTrust, SignatureFailure, SignatureResult,
};

pub(super) fn authenticate(
    trust: &PublisherTrust,
    evidence: InspectedSignatureEvidence,
    now: u64,
) -> SignatureResult<VerifiedPackageSignature> {
    let inspected = evidence.signature;
    let key = trust
        .policy
        .keys
        .get(&inspected.key_hint)
        .ok_or(SignatureFailure::UnapprovedKey)?;
    verify_signature(
        &key.public_key,
        &pae(SIGNATURE_PAYLOAD_TYPE, &inspected.payload)?,
        &inspected.signature,
    )?;
    let claims = inspected.claims;
    if claims.publisher_id != key.publisher {
        return Err(SignatureFailure::UntrustedPublisher.into());
    }
    if !contains(key.valid_from, key.valid_until, claims.issued_at)
        || !contains(key.valid_from, key.valid_until, now)
    {
        return Err(SignatureFailure::KeyExpired.into());
    }
    if trust.revocations.keys.contains(&inspected.key_hint)
        || trust.revocations.publishers.contains(&key.publisher.0)
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
    Ok(VerifiedPackageSignature {
        subject: claims.subject,
        publisher: key.publisher.clone(),
        key_fingerprint: inspected.key_hint,
        evidence_digest: evidence.referrer_digest,
        payload_digest: evidence.payload_digest,
        state: trust.state_id().clone(),
        verified_at: now,
        valid_until,
    })
}

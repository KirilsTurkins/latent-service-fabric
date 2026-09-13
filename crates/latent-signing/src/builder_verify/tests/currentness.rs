use super::support::*;
use crate::*;
use serde_json::json;

#[test]
fn changing_source_policy_invalidates_prior_proof_and_compare_exchange_guards_updates() {
    let (signer, public, _) = signer(BUILDER);
    let evidence = signed(&signer, &observation());
    let mut value = policy_value(&public);
    let owner = verifier(&value);
    let initial = owner.state_id().unwrap();
    let proof = owner
        .verify_package(&subject(), evidence.as_ref(), NOW)
        .unwrap();
    value["generation"] = 2.into();
    value["requirements"][0]["sourceRevision"] = "a".repeat(40).into();
    let next = owner
        .replace_trust(&initial, trust(&value, |_| {}), NOW + 1)
        .unwrap();
    assert_ne!(initial.policy_digest(), next.policy_digest());
    assert_eq!(
        owner.check_current(&proof, NOW + 1).unwrap_err().reason(),
        SignatureFailure::StaleProof
    );
    assert_eq!(
        owner
            .replace_trust(&initial, trust(&value, |_| {}), NOW + 1)
            .unwrap_err()
            .reason(),
        SignatureFailure::TrustConflict
    );
    owner
        .verify_package(&subject(), evidence.as_ref(), NOW + 1)
        .unwrap();
    assert_eq!(
        owner
            .replace_trust(&next, trust(&policy_value(&public), |_| {}), NOW + 1)
            .unwrap_err()
            .reason(),
        SignatureFailure::TrustConflict
    );
}

#[test]
fn same_generation_conflicts_and_identical_updates_never_renew_proof() {
    let (signer, public, _) = signer(BUILDER);
    let evidence = signed(&signer, &observation());
    let value = policy_value(&public);
    let owner = verifier(&value);
    let initial = owner.state_id().unwrap();
    let proof = owner
        .verify_package(&subject(), evidence.as_ref(), NOW)
        .unwrap();
    let mut changed = value.clone();
    changed["requirements"][0]["requireReproducible"] = true.into();
    assert_eq!(
        owner
            .replace_trust(&initial, trust(&changed, |_| {}), NOW + 1)
            .unwrap_err()
            .reason(),
        SignatureFailure::TrustConflict
    );
    assert_eq!(
        owner
            .replace_trust(&initial, trust(&value, |_| {}), NOW + 2)
            .unwrap(),
        initial
    );
    assert_eq!(proof.valid_until(), NOW + 60);
    assert_eq!(
        owner.check_current(&proof, NOW + 60).unwrap_err().reason(),
        SignatureFailure::StaleProof
    );
}

#[test]
fn revocation_updates_invalidate_proof_and_expired_refresh_cannot_extend_trust() {
    let (signer, public, _) = signer(BUILDER);
    let evidence = signed(&signer, &observation());
    let value = policy_value(&public);
    let owner = verifier(&value);
    let initial = owner.state_id().unwrap();
    let proof = owner
        .verify_package(&subject(), evidence.as_ref(), NOW)
        .unwrap();
    let revoked = trust(&value, |snapshot| {
        snapshot["generation"] = 2.into();
        snapshot["revokedBuilders"] = json!([BUILDER]);
    });
    let current = owner.replace_trust(&initial, revoked, NOW + 1).unwrap();
    assert_eq!(current.policy_digest(), initial.policy_digest());
    assert_ne!(current.revocation_digest(), initial.revocation_digest());
    assert_eq!(
        owner.check_current(&proof, NOW + 1).unwrap_err().reason(),
        SignatureFailure::StaleProof
    );
    assert_eq!(
        owner
            .verify_package(&subject(), evidence.as_ref(), NOW + 1)
            .unwrap_err()
            .reason(),
        SignatureFailure::Revoked
    );
    let expired = trust(&value, |snapshot| {
        snapshot["generation"] = 3.into();
        snapshot["validUntil"] = NOW.into();
    });
    assert_eq!(
        owner
            .replace_trust(&current, expired, NOW + 2)
            .unwrap_err()
            .reason(),
        SignatureFailure::TrustExpired
    );
    assert_eq!(owner.state_id().unwrap(), current);
    assert_eq!(owner.clock_floor(), NOW + 2);
    assert_eq!(
        owner.check_current(&proof, NOW + 1).unwrap_err().reason(),
        SignatureFailure::ClockRegression
    );
}

#[test]
fn shorter_revocation_expiry_caps_proof_and_clock_rollback_cannot_revive_it() {
    let (signer, public, _) = signer(BUILDER);
    let evidence = signed(&signer, &observation());
    let bounded = trust(&policy_value(&public), |snapshot| {
        snapshot["validUntil"] = (NOW + 5).into();
    });
    let owner = BuilderVerifier::new(bounded, ProvenanceLimits::default(), NOW).unwrap();
    let proof = owner
        .verify_package(&subject(), evidence.as_ref(), NOW)
        .unwrap();
    assert_eq!(proof.valid_until(), NOW + 5);
    assert_eq!(
        owner.check_current(&proof, NOW + 5).unwrap_err().reason(),
        SignatureFailure::TrustExpired
    );
    assert_eq!(
        owner.check_current(&proof, NOW + 4).unwrap_err().reason(),
        SignatureFailure::ClockRegression
    );
}

#[test]
fn owner_adoption_and_replacement_enforce_lowered_requirement_limits() {
    let (_, public, _) = signer(BUILDER);
    let mut value = policy_value(&public);
    let mut other = value["requirements"][0].clone();
    other["requireReproducible"] = true.into();
    value["requirements"].as_array_mut().unwrap().push(other);
    let limits = ProvenanceLimits {
        max_requirements: 1,
        ..ProvenanceLimits::default()
    };
    assert_eq!(
        BuilderVerifier::new(trust(&value, |_| {}), limits, NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::ResourceLimit
    );
    let owner = BuilderVerifier::new(trust(&policy_value(&public), |_| {}), limits, NOW).unwrap();
    let current = owner.state_id().unwrap();
    value["generation"] = 2.into();
    assert_eq!(
        owner
            .replace_trust(&current, trust(&value, |_| {}), NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::ResourceLimit
    );
    assert_eq!(owner.state_id().unwrap(), current);
}

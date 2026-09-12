use super::support::*;
use crate::*;
use serde_json::{json, Value};

#[test]
fn exact_authenticated_builder_and_source_are_returned_without_publisher_authority() {
    let (signer, public, fingerprint) = signer(BUILDER);
    let observation = observation();
    let evidence = signed(&signer, &observation);
    let owner = verifier(&policy_value(&public));
    let proof = owner
        .verify_package(&subject(), evidence.as_ref(), NOW)
        .unwrap();
    assert_eq!(proof.subject(), subject().subject());
    assert_eq!(
        proof.component_digest().as_str(),
        observation.component_digest
    );
    assert_eq!(proof.builder_id(), BUILDER);
    assert_eq!(proof.key_fingerprint().as_str(), fingerprint);
    assert_eq!(proof.source_repository(), observation.source.repository);
    assert_eq!(proof.source_revision(), observation.source.revision);
    assert_eq!(
        proof.source_snapshot_digest().as_str(),
        observation.source.snapshot_digest
    );
    assert_eq!(proof.verified_at(), NOW);
    assert_eq!(proof.valid_until(), NOW + 60);
    assert_eq!(proof.state_id(), &owner.state_id().unwrap());
    owner.check_current(&proof, NOW + 59).unwrap();
    assert_eq!(
        owner.check_current(&proof, NOW + 60).unwrap_err().reason(),
        SignatureFailure::StaleProof
    );
}

#[test]
fn whitelisted_key_cannot_assert_another_builder_and_empty_authorities_deny() {
    let (signer, public, _) = signer("different-builder");
    let evidence = signed(&signer, &observation());
    assert_eq!(
        verifier(&policy_value(&public))
            .verify_package(&subject(), evidence.as_ref(), NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::UntrustedBuilder
    );
    let (signer, public, _) = self::signer(BUILDER);
    let evidence = signed(&signer, &observation());
    for (field, reason) in [
        ("keys", SignatureFailure::UnapprovedKey),
        ("requirements", SignatureFailure::UntrustedBuilder),
    ] {
        let mut policy = policy_value(&public);
        policy[field] = json!([]);
        assert_eq!(
            verifier(&policy)
                .verify_package(&subject(), evidence.as_ref(), NOW)
                .unwrap_err()
                .reason(),
            reason
        );
    }
}

#[test]
fn source_constraints_are_exact_and_multiple_requirements_are_disjunctive() {
    let (signer, public, _) = signer(BUILDER);
    let observation = observation();
    let evidence = signed(&signer, &observation);
    for (field, wrong) in [
        (
            "sourceRepository",
            Value::from("https://EXAMPLE.com/source"),
        ),
        ("sourceRevision", Value::from("b".repeat(40))),
        (
            "sourceSnapshotDigest",
            Value::from(format!("sha256:{}", "a".repeat(64))),
        ),
        ("requireReproducible", Value::from(true)),
    ] {
        let mut policy = policy_value(&public);
        let valid = policy["requirements"][0].clone();
        policy["requirements"][0][field] = wrong;
        assert_eq!(
            verifier(&policy)
                .verify_package(&subject(), evidence.as_ref(), NOW)
                .unwrap_err()
                .reason(),
            SignatureFailure::SourceDisallowed
        );
        policy["requirements"].as_array_mut().unwrap().push(valid);
        verifier(&policy)
            .verify_package(&subject(), evidence.as_ref(), NOW)
            .unwrap();
    }
    let mut observed_twice = observation;
    observed_twice.reproducibility = "two-build-byte-equality".into();
    let evidence = signed(&signer, &observed_twice);
    let mut policy = policy_value(&public);
    policy["requirements"][0]["requireReproducible"] = true.into();
    policy["requirements"][0]["sourceRevision"] = observed_twice.source.revision.into();
    policy["requirements"][0]["sourceSnapshotDigest"] =
        observed_twice.source.snapshot_digest.into();
    verifier(&policy)
        .verify_package(&subject(), evidence.as_ref(), NOW)
        .unwrap();
}

#[test]
fn key_and_builder_revocations_override_valid_signatures() {
    let (signer, public, fingerprint) = signer(BUILDER);
    let evidence = signed(&signer, &observation());
    for (field, value) in [
        ("revokedKeys", fingerprint.as_str()),
        ("revokedBuilders", BUILDER),
    ] {
        let trust = trust(&policy_value(&public), |snapshot| {
            snapshot[field] = json!([value]);
        });
        let owner = BuilderVerifier::new(trust, ProvenanceLimits::default(), NOW).unwrap();
        assert_eq!(
            owner
                .verify_package(&subject(), evidence.as_ref(), NOW)
                .unwrap_err()
                .reason(),
            SignatureFailure::Revoked
        );
    }
}

#[test]
fn expiry_and_shorter_policy_lifetime_fail_closed() {
    let (signer, public, _) = signer(BUILDER);
    let evidence = signed(&signer, &observation());
    let mut value = policy_value(&public);
    value["keys"][0]["validUntil"] = 1050.into();
    assert_eq!(
        verifier(&value)
            .verify_package(&subject(), evidence.as_ref(), NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::KeyExpired
    );
    value = policy_value(&public);
    value["maxSignatureLifetimeSeconds"] = 999.into();
    assert_eq!(
        verifier(&value)
            .verify_package(&subject(), evidence.as_ref(), NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::InvalidValidity
    );
    assert_eq!(
        verifier(&policy_value(&public))
            .verify_package(&subject(), evidence.as_ref(), 2000)
            .unwrap_err()
            .reason(),
        SignatureFailure::SignatureExpired
    );
}

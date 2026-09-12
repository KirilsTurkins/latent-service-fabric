use crate::support::{self, browser, evidence, policy_value, trust, trust_values, NOW};
use latent_signing::{PublisherVerifier, SignatureFailure, SignatureLimits};
use serde_json::json;
use std::sync::{Arc, Barrier};

#[test]
fn proof_expiry_is_the_minimum_of_every_independent_authority_bound() {
    for bound in ["key", "policy", "revocation", "proof"] {
        let mut policy = policy_value();
        match bound {
            "key" => policy["keys"][0]["validUntil"] = json!(NOW + 20),
            "policy" => policy["validUntil"] = json!(NOW + 20),
            "proof" => policy["maxProofAgeSeconds"] = json!(20),
            _ => {}
        }
        let trust = trust_values(&policy, |snapshot| {
            if bound == "revocation" {
                snapshot["validUntil"] = json!(NOW + 20);
            }
        });
        let verifier = PublisherVerifier::new(trust, SignatureLimits::default(), NOW).unwrap();
        let proof = verifier
            .verify_package(&browser(), evidence().as_ref(), NOW)
            .unwrap();
        assert_eq!(proof.valid_until(), NOW + 20, "bound: {bound}");
        verifier.check_current(&proof, NOW + 19).unwrap();
        assert!(verifier.check_current(&proof, NOW + 20).is_err());
    }
    let mut policy = policy_value();
    policy["maxProofAgeSeconds"] = json!(3_600);
    let verifier = PublisherVerifier::new(
        trust_values(&policy, |_| {}),
        SignatureLimits::default(),
        NOW,
    )
    .unwrap();
    let proof = verifier
        .verify_package(&browser(), evidence().as_ref(), NOW)
        .unwrap();
    assert_eq!(
        proof.valid_until(),
        2_000,
        "signed expiry is an independent ceiling"
    );
}

#[test]
fn rejected_expiry_advances_clock_and_idempotent_updates_do_not_renew_snapshots() {
    let verifier = PublisherVerifier::new(trust(), SignatureLimits::default(), NOW).unwrap();
    let proof = verifier
        .verify_package(&browser(), evidence().as_ref(), NOW)
        .unwrap();
    let original = verifier.state_id().unwrap();
    assert_eq!(
        verifier
            .replace_trust(&original, trust(), 3_000)
            .unwrap_err()
            .reason(),
        SignatureFailure::TrustExpired
    );
    assert_eq!(verifier.clock_floor(), 3_000);
    assert_eq!(
        verifier.check_current(&proof, NOW).unwrap_err().reason(),
        SignatureFailure::ClockRegression
    );
    assert_eq!(verifier.state_id().unwrap(), original);

    let verifier = PublisherVerifier::new(trust(), SignatureLimits::default(), NOW).unwrap();
    assert_eq!(
        verifier
            .verify_package(&browser(), evidence().as_ref(), 2_000)
            .err()
            .unwrap()
            .reason(),
        SignatureFailure::SignatureExpired
    );
    assert_eq!(verifier.clock_floor(), 2_000);
    assert_eq!(
        verifier
            .verify_package(&browser(), evidence().as_ref(), NOW)
            .err()
            .unwrap()
            .reason(),
        SignatureFailure::ClockRegression
    );
}

#[test]
fn identical_state_cannot_adopt_a_proof_before_its_verification_time() {
    let producing = PublisherVerifier::new(trust(), SignatureLimits::default(), NOW + 10).unwrap();
    let proof = producing
        .verify_package(&browser(), evidence().as_ref(), NOW + 10)
        .unwrap();
    let receiving = PublisherVerifier::new(trust(), SignatureLimits::default(), NOW).unwrap();
    assert_eq!(receiving.state_id().unwrap(), *proof.state_id());
    assert_eq!(
        receiving
            .check_current(&proof, NOW + 9)
            .unwrap_err()
            .reason(),
        SignatureFailure::StaleProof
    );
    receiving.check_current(&proof, NOW + 10).unwrap();
}

#[test]
fn revocation_and_policy_rotation_invalidate_proofs_and_prevent_rollback() {
    let verifier = PublisherVerifier::new(trust(), SignatureLimits::default(), NOW).unwrap();
    let proof = verifier
        .verify_package(&browser(), evidence().as_ref(), NOW)
        .unwrap();
    let initial = verifier.state_id().unwrap();
    let next = trust_values(&policy_value(), |snapshot| {
        snapshot["generation"] = json!(2);
    });
    let second = verifier.replace_trust(&initial, next, NOW).unwrap();
    assert_eq!(second.policy_generation(), 1);
    assert_eq!(second.revocation_generation(), 2);
    assert_eq!(
        verifier.check_current(&proof, NOW).unwrap_err().reason(),
        SignatureFailure::StaleProof
    );
    assert_eq!(
        verifier
            .replace_trust(&second, trust(), NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::TrustConflict
    );

    let current_proof = verifier
        .verify_package(&browser(), evidence().as_ref(), NOW)
        .unwrap();
    let mut rotated_policy = policy_value();
    rotated_policy["generation"] = json!(2);
    rotated_policy["maxProofAgeSeconds"] = json!(30);
    let invalid_rotation = trust_values(&rotated_policy, |snapshot| {
        snapshot["generation"] = json!(2);
    });
    assert_eq!(
        verifier
            .replace_trust(&second, invalid_rotation, NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::TrustConflict
    );
    let rotation = trust_values(&rotated_policy, |snapshot| {
        snapshot["generation"] = json!(3);
    });
    let third = verifier.replace_trust(&second, rotation, NOW).unwrap();
    assert_eq!(third.policy_generation(), 2);
    assert_eq!(third.revocation_generation(), 3);
    assert_eq!(
        verifier
            .check_current(&current_proof, NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::StaleProof
    );
}

#[test]
fn same_generation_content_changes_are_not_idempotent() {
    let verifier = PublisherVerifier::new(trust(), SignatureLimits::default(), NOW).unwrap();
    let expected = verifier.state_id().unwrap();
    let changed = trust_values(&policy_value(), |snapshot| {
        snapshot["validUntil"] = json!(2_900);
    });
    assert_eq!(
        verifier
            .replace_trust(&expected, changed, NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::TrustConflict
    );
    let mut policy = policy_value();
    policy["maxProofAgeSeconds"] = json!(30);
    let changed = trust_values(&policy, |snapshot| snapshot["generation"] = json!(2));
    assert_eq!(
        verifier
            .replace_trust(&expected, changed, NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::TrustConflict
    );
    assert_eq!(
        verifier.replace_trust(&expected, trust(), NOW).unwrap(),
        expected
    );
}

#[test]
fn owner_limits_apply_to_preconstructed_initial_and_replacement_snapshots() {
    let (_, public_key) = support::signer("second-publisher");
    let mut expanded = policy_value();
    expanded["keys"]
        .as_array_mut()
        .unwrap()
        .push(support::key(&public_key, "second-publisher"));
    let owner = SignatureLimits {
        max_keys: 1,
        ..SignatureLimits::default()
    };
    assert_eq!(
        PublisherVerifier::new(trust_values(&expanded, |_| {}), owner, NOW)
            .err()
            .unwrap()
            .reason(),
        SignatureFailure::ResourceLimit
    );
    let verifier = PublisherVerifier::new(trust(), owner, NOW).unwrap();
    let expected = verifier.state_id().unwrap();
    expanded["generation"] = json!(2);
    let next = trust_values(&expanded, |snapshot| snapshot["generation"] = json!(2));
    assert_eq!(
        verifier
            .replace_trust(&expected, next, NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::ResourceLimit
    );
    assert_eq!(verifier.state_id().unwrap(), expected);

    let owner = SignatureLimits {
        max_revoked_publishers: 1,
        ..SignatureLimits::default()
    };
    let oversized = trust_values(&policy_value(), |snapshot| {
        snapshot["revokedPublishers"] = json!(["a", "b"]);
    });
    assert_eq!(
        PublisherVerifier::new(oversized, owner, NOW)
            .err()
            .unwrap()
            .reason(),
        SignatureFailure::ResourceLimit
    );
}

#[test]
fn concurrent_expected_state_updates_have_at_most_one_winner() {
    let verifier =
        Arc::new(PublisherVerifier::new(trust(), SignatureLimits::default(), NOW).unwrap());
    let expected = verifier.state_id().unwrap();
    let barrier = Arc::new(Barrier::new(2));
    let workers: Vec<_> = (0..2)
        .map(|index| {
            let verifier = Arc::clone(&verifier);
            let expected = expected.clone();
            let barrier = Arc::clone(&barrier);
            std::thread::spawn(move || {
                let next = trust_values(&policy_value(), |snapshot| {
                    snapshot["generation"] = json!(2);
                    snapshot["revokedPublishers"] = json!([format!("unrelated-{index}")]);
                });
                barrier.wait();
                verifier.replace_trust(&expected, next, NOW)
            })
        })
        .collect();
    let results: Vec<_> = workers
        .into_iter()
        .map(|worker| worker.join().unwrap())
        .collect();
    assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
    let failure = results
        .iter()
        .find_map(|result| result.as_ref().err())
        .unwrap();
    assert!(matches!(
        failure.reason(),
        SignatureFailure::TrustConflict | SignatureFailure::ResourceLimit
    ));
    assert_eq!(verifier.state_id().unwrap().revocation_generation(), 2);
}

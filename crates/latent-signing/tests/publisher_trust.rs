#[path = "publisher_trust/currentness.rs"]
mod currentness;
mod support;

use base64::{engine::general_purpose::STANDARD, Engine};
use latent_artifacts::package::{
    artifact_blob_digest, decode_config, decode_manifest, encode_config, encode_manifest,
    PackageLimits,
};
use latent_signing::{
    inspect_signature, PackageSigningSubject, PublisherPolicy, PublisherVerifier,
    SignatureEvidence, SignatureFailure, SignatureLimits,
};
use serde_json::{json, Value};
use support::{browser, evidence, policy_value, trust, trust_values, NOW};

#[test]
fn externally_produced_openssl_signature_verifies_exact_claim_bytes() {
    let limits = SignatureLimits::default();
    let inspected = inspect_signature(support::ENVELOPE, limits).unwrap();
    assert_eq!(inspected.payload_bytes(), support::CLAIMS);
    assert_eq!(inspected.publisher_id().0, support::PUBLISHER);
    let expected = browser();
    let evidence = evidence();
    let verifier = PublisherVerifier::new(trust(), limits, NOW).unwrap();
    let proof = verifier
        .verify_package(&expected, evidence.as_ref(), NOW)
        .unwrap();
    assert_eq!(proof.subject(), expected.subject());
    assert_eq!(proof.publisher().0, support::PUBLISHER);
    assert_eq!(proof.key_fingerprint(), inspected.key_hint());
    assert_eq!(proof.evidence_digest(), evidence.digest());
    assert_eq!(
        proof.payload_digest(),
        &artifact_blob_digest(evidence.payload_bytes())
    );
    assert_eq!(proof.state_id(), &verifier.state_id().unwrap());
    assert_eq!(proof.verified_at(), NOW);
    assert_eq!(proof.valid_until(), NOW + 60);
    verifier.check_current(&proof, NOW + 59).unwrap();
    assert_eq!(
        verifier
            .check_current(&proof, NOW + 60)
            .unwrap_err()
            .reason(),
        SignatureFailure::StaleProof
    );
}

#[test]
fn syntactically_valid_claim_rewrite_does_not_reuse_a_signature() {
    let expected = browser();
    let mut envelope: Value = serde_json::from_slice(support::ENVELOPE).unwrap();
    let mut claims: Value = serde_json::from_slice(support::CLAIMS).unwrap();
    claims["expiresAt"] = json!(2_001);
    envelope["payload"] = json!(STANDARD.encode(serde_json::to_vec(&claims).unwrap()));
    let altered = SignatureEvidence::from_envelope(
        &expected,
        &serde_json::to_vec(&envelope).unwrap(),
        SignatureLimits::default(),
    )
    .unwrap();
    let verifier = PublisherVerifier::new(trust(), SignatureLimits::default(), NOW).unwrap();
    assert_eq!(
        verifier
            .verify_package(&expected, altered.as_ref(), NOW)
            .err()
            .unwrap()
            .reason(),
        SignatureFailure::InvalidSignature
    );
}

#[test]
fn package_metadata_change_with_same_component_is_a_different_signed_subject() {
    let limits = PackageLimits::default();
    let original_manifest =
        include_bytes!("../../../examples/package-format/capsule/manifest.json");
    let original_config = include_bytes!("../../../examples/package-format/capsule/config.json");
    let original =
        PackageSigningSubject::from_package(original_manifest, original_config, limits).unwrap();
    let mut config = decode_config(original_config, limits).unwrap();
    let component = config.component_digest.clone();
    config
        .annotations
        .insert("test.package-metadata".into(), "changed".into());
    let changed_config = encode_config(&config, limits).unwrap();
    let mut manifest = decode_manifest(original_manifest, limits).unwrap();
    manifest.config.digest = artifact_blob_digest(&changed_config);
    manifest.config.size = changed_config.len() as u64;
    let changed_manifest = encode_manifest(&manifest, limits).unwrap();
    let changed =
        PackageSigningSubject::from_package(&changed_manifest, &changed_config, limits).unwrap();
    assert_eq!(
        decode_config(&changed_config, limits)
            .unwrap()
            .component_digest,
        component
    );
    assert_ne!(original.subject().digest, changed.subject().digest);
    let (signer, public_key) = support::signer("package-publisher");
    let evidence = support::signed(&signer, &original);
    let mut policy = policy_value();
    policy["keys"] = json!([support::key(&public_key, "package-publisher")]);
    let verifier = PublisherVerifier::new(
        trust_values(&policy, |_| {}),
        SignatureLimits::default(),
        NOW,
    )
    .unwrap();
    verifier
        .verify_package(&original, evidence.as_ref(), NOW)
        .unwrap();
    assert_eq!(
        verifier
            .verify_package(&changed, evidence.as_ref(), NOW)
            .err()
            .unwrap()
            .reason(),
        SignatureFailure::SubjectMismatch
    );
}

#[test]
fn hints_and_signed_publisher_claims_never_supply_an_approved_identity() {
    let expected = browser();
    let (unapproved_signer, _) = support::signer(support::PUBLISHER);
    let unapproved = support::signed(&unapproved_signer, &expected);
    let verifier = PublisherVerifier::new(trust(), SignatureLimits::default(), NOW).unwrap();
    assert_eq!(
        verifier
            .verify_package(&expected, unapproved.as_ref(), NOW)
            .err()
            .unwrap()
            .reason(),
        SignatureFailure::UnapprovedKey
    );

    let (wrong_publisher, public_key) = support::signer("self-asserted-publisher");
    let mut policy = policy_value();
    policy["keys"] = json!([support::key(&public_key, "approved-publisher")]);
    let verifier = PublisherVerifier::new(
        trust_values(&policy, |_| {}),
        SignatureLimits::default(),
        NOW,
    )
    .unwrap();
    let evidence = support::signed(&wrong_publisher, &expected);
    assert_eq!(
        verifier
            .verify_package(&expected, evidence.as_ref(), NOW)
            .err()
            .unwrap()
            .reason(),
        SignatureFailure::UntrustedPublisher
    );
}

#[test]
fn revoked_keys_and_publishers_invalidate_matching_evidence() {
    let inspected = inspect_signature(support::ENVELOPE, SignatureLimits::default()).unwrap();
    for (field, entry) in [
        ("revokedKeys", inspected.key_hint().as_str()),
        ("revokedPublishers", support::PUBLISHER),
    ] {
        let trust = trust_values(&policy_value(), |snapshot| snapshot[field] = json!([entry]));
        let verifier = PublisherVerifier::new(trust, SignatureLimits::default(), NOW).unwrap();
        assert_eq!(
            verifier
                .verify_package(&browser(), evidence().as_ref(), NOW)
                .err()
                .unwrap()
                .reason(),
            SignatureFailure::Revoked
        );
    }
}

#[test]
fn empty_policy_explicitly_denies_every_publisher() {
    let mut policy = policy_value();
    policy["keys"] = json!([]);
    let verifier = PublisherVerifier::new(
        trust_values(&policy, |_| {}),
        SignatureLimits::default(),
        NOW,
    )
    .unwrap();
    assert_eq!(
        verifier
            .verify_package(&browser(), evidence().as_ref(), NOW)
            .err()
            .unwrap()
            .reason(),
        SignatureFailure::UnapprovedKey
    );
}

#[test]
fn independent_key_order_does_not_change_canonical_policy_identity() {
    let (_, public_key) = support::signer("second-publisher");
    let mut value = policy_value();
    value["keys"]
        .as_array_mut()
        .unwrap()
        .push(support::key(&public_key, "second-publisher"));
    let forward = support::policy(&value);
    value["keys"].as_array_mut().unwrap().reverse();
    let backward = support::policy(&value);
    assert_eq!(forward.digest(), backward.digest());
    assert_eq!(forward.canonical_bytes(), backward.canonical_bytes());
    value["keys"]
        .as_array_mut()
        .unwrap()
        .push(support::key(&public_key, "conflicting-publisher"));
    assert!(PublisherPolicy::from_json(
        &serde_json::to_vec(&value).unwrap(),
        SignatureLimits::default()
    )
    .is_err());
}

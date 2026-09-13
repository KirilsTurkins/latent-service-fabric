//! Real publisher proof after exact-byte OCI attach/discover/pull.
use super::{fixtures::Fixture, reference};
use base64::{engine::general_purpose::STANDARD, Engine};
use latent_artifacts::package::{decode_referrer, EvidenceKind, PackageLimits};
use latent_core::PublisherId;
use latent_oci::{HttpOciRegistry, OciManifestBytes, OciPushRequest, OciRegistry};
use latent_signing::{
    generate_signing_key, LocalSigner, PackageSigningSubject, PublisherPolicy, PublisherTrust,
    PublisherVerifier, RevocationSnapshot, SignatureEvidenceRef, SignatureLimits,
    SignatureValidity,
};
use serde_json::json;

pub async fn roundtrip(client: &HttpOciRegistry, origin: &str, capsule: &Fixture) {
    let package_limits = PackageLimits::default();
    let limits = SignatureLimits::default();
    let subject =
        PackageSigningSubject::from_package(&capsule.manifest, &capsule.config, package_limits)
            .unwrap();
    let generated = generate_signing_key().unwrap();
    let public_key = *generated.public_key();
    let signer = LocalSigner::from_pkcs8(
        generated.into_pkcs8(),
        PublisherId("registry-test-publisher".into()),
        public_key,
    )
    .unwrap();
    let evidence = signer
        .sign_package(
            &subject,
            SignatureValidity {
                issued_at: 1_000,
                expires_at: 2_000,
            },
            limits,
        )
        .unwrap();
    let parsed = decode_referrer(evidence.manifest_bytes(), package_limits).unwrap();
    let request = OciPushRequest::new_referrer(
        reference(origin, "signed-capsule-evidence"),
        OciManifestBytes::new(
            evidence.manifest_bytes().to_vec(),
            limits.max_envelope_bytes,
        )
        .unwrap(),
        evidence.config_bytes().to_vec(),
        vec![(parsed.layers[0].clone(), evidence.payload_bytes().to_vec())],
        package_limits,
    )
    .unwrap();
    assert_eq!(client.push(request).await.unwrap(), *evidence.digest());
    let found = client
        .list_referrers(
            &reference(origin, subject.subject().digest.as_str()),
            Some(EvidenceKind::Signature.artifact_type()),
        )
        .await
        .unwrap();
    assert!(found
        .iter()
        .any(|descriptor| descriptor.digest == evidence.digest().as_str()));
    let pulled = client
        .pull_package(&reference(origin, evidence.digest().as_str()))
        .await
        .unwrap();
    let received = pulled.request();
    assert_eq!(received.manifest().as_bytes(), evidence.manifest_bytes());
    assert_eq!(received.config_bytes(), evidence.config_bytes());
    let (_, payload) = received.layers().next().unwrap();
    assert_eq!(payload, evidence.payload_bytes());

    // Registry credentials and referrer association never become trust anchors.
    // This independently approved, ephemeral test policy supplies that authority.
    let policy = PublisherPolicy::from_json(&serde_json::to_vec(&json!({
        "formatVersion": 1, "scope": "registry-test", "generation": 1,
        "validFrom": 900, "validUntil": 3_000,
        "maxSignatureLifetimeSeconds": 2_000, "maxProofAgeSeconds": 60,
        "keys": [{"publisherId": "registry-test-publisher", "publicKey": STANDARD.encode(public_key),
            "validFrom": 900, "validUntil": 3_000}],
    })).unwrap(), limits).unwrap();
    let revocations = RevocationSnapshot::from_json(
        &serde_json::to_vec(&json!({
            "formatVersion": 1, "scope": "registry-test", "generation": 1,
            "policyDigest": policy.digest().as_str(), "validFrom": 900, "validUntil": 3_000,
            "revokedKeys": [], "revokedPublishers": [],
        }))
        .unwrap(),
        limits,
    )
    .unwrap();
    let verifier = PublisherVerifier::new(
        PublisherTrust::new(policy, revocations).unwrap(),
        limits,
        1_100,
    )
    .unwrap();
    let proof = verifier
        .verify_package(
            &subject,
            SignatureEvidenceRef {
                manifest: received.manifest().as_bytes(),
                config: received.config_bytes(),
                payload,
            },
            1_100,
        )
        .unwrap();
    assert_eq!(proof.subject(), subject.subject());
    assert_eq!(proof.evidence_digest(), evidence.digest());
    assert_eq!(proof.publisher().0, "registry-test-publisher");
    verifier.check_current(&proof, 1_101).unwrap();
}

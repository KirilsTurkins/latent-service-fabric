//! Inventory metadata is part of the package signed by its approved publisher.
use std::collections::BTreeMap;

use base64::{engine::general_purpose::STANDARD, Engine};
use latent_artifacts::package::{artifact_blob_digest, LayerRole, PackageKind};
use latent_core::PublisherId;
use latent_packaging::{
    build_package_with_sbom, decode_sbom_inventory, LayerInput, PackageBundle, PackageInput,
    PackagingLimits,
};
use latent_signing::{
    generate_signing_key, LocalSigner, PackageSigningSubject, PublisherPolicy, PublisherTrust,
    PublisherVerifier, RevocationSnapshot, SignatureFailure, SignatureLimits, SignatureValidity,
};
use serde_json::json;

fn package(license: &str) -> PackageBundle {
    let bytes = b"<p>same output bytes</p>";
    let limits = PackagingLimits::default();
    let inventory = decode_sbom_inventory(
        &serde_json::to_vec(&json!({
            "formatVersion": 1, "packageKind": "browser-assets",
            "packageName": "signed-inventory", "packageVersion": "1.0.0",
            "dependencyCompleteness": "declared-inputs-incomplete",
            "entries": [{
                "kind": "asset", "name": "index.html", "licenseExpression": license,
                "digest": artifact_blob_digest(bytes).as_str(), "digestScope": "output-bytes",
                "size": bytes.len(), "path": "index.html", "origin": "package-input"
            }]
        }))
        .unwrap(),
        limits.sbom,
    )
    .unwrap();
    build_package_with_sbom(
        PackageInput {
            kind: PackageKind::BrowserAssets,
            name: "signed-inventory".into(),
            version: "1.0.0".into(),
            entrypoint: "index.html".into(),
            annotations: BTreeMap::new(),
            layers: vec![LayerInput {
                path: "index.html".into(),
                role: LayerRole::Asset,
                media_type: "text/html".into(),
                bytes: bytes.to_vec(),
            }],
        },
        inventory,
        limits,
    )
    .unwrap()
}

fn verifier(public: [u8; 32]) -> PublisherVerifier {
    let limits = SignatureLimits::default();
    let policy = PublisherPolicy::from_json(
        &serde_json::to_vec(&json!({
            "formatVersion":1, "scope":"sbom-signature-test", "generation":1,
            "validFrom":900, "validUntil":3000,
            "maxSignatureLifetimeSeconds":2000, "maxProofAgeSeconds":60,
            "keys":[{"publisherId":"sbom-test-publisher", "publicKey":STANDARD.encode(public),
                "validFrom":900, "validUntil":3000}]
        }))
        .unwrap(),
        limits,
    )
    .unwrap();
    let revocations = RevocationSnapshot::from_json(
        &serde_json::to_vec(&json!({
            "formatVersion":1, "scope":"sbom-signature-test", "generation":1,
            "policyDigest":policy.digest().as_str(), "validFrom":900, "validUntil":3000,
            "revokedKeys":[], "revokedPublishers":[]
        }))
        .unwrap(),
        limits,
    )
    .unwrap();
    PublisherVerifier::new(
        PublisherTrust::new(policy, revocations).unwrap(),
        limits,
        1100,
    )
    .unwrap()
}

#[test]
fn changing_only_embedded_license_metadata_invalidates_existing_publisher_evidence() {
    let original = package("MIT");
    let changed = package("Apache-2.0");
    assert_eq!(original.blob("index.html"), changed.blob("index.html"));
    assert_ne!(original.layout().digest(), changed.layout().digest());
    let package_limits = PackagingLimits::default().package;
    let subject = PackageSigningSubject::from_package(
        original.manifest_bytes(),
        original.config_bytes(),
        package_limits,
    )
    .unwrap();
    let altered = PackageSigningSubject::from_package(
        changed.manifest_bytes(),
        changed.config_bytes(),
        package_limits,
    )
    .unwrap();
    let generated = generate_signing_key().unwrap();
    let public = *generated.public_key();
    let signer = LocalSigner::from_pkcs8(
        generated.into_pkcs8(),
        PublisherId("sbom-test-publisher".into()),
        public,
    )
    .unwrap();
    let evidence = signer
        .sign_package(
            &subject,
            SignatureValidity {
                issued_at: 1000,
                expires_at: 2000,
            },
            SignatureLimits::default(),
        )
        .unwrap();
    let verifier = verifier(public);
    let proof = verifier
        .verify_package(&subject, evidence.as_ref(), 1100)
        .unwrap();
    verifier.check_current(&proof, 1100).unwrap();
    assert_eq!(
        verifier
            .verify_package(&altered, evidence.as_ref(), 1100)
            .unwrap_err()
            .reason(),
        SignatureFailure::SubjectMismatch
    );
}

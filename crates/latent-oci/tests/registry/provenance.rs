//! One actual observed component -> package -> signed builder evidence -> OCI
//! round trip. No compiler, invocation or persistent private key in this process.
use super::reference;
use base64::{engine::general_purpose::STANDARD, Engine};
use latent_artifacts::package::{decode_manifest, decode_referrer, EvidenceKind, PackageLimits};
use latent_oci::{HttpOciRegistry, OciManifestBytes, OciPushRequest, OciRegistry};
use latent_packaging::{build_package, decode_package_source, read_package_input, PackagingLimits};
use latent_signing::{
    decode_build_observation, generate_signing_key, BuildObservation, BuilderPolicy,
    BuilderRevocationSnapshot, BuilderTrust, BuilderVerifier, LocalBuilderSigner,
    PackageSigningSubject, ProvenanceEvidenceRef, ProvenanceLimits, SignatureValidity,
    PROVENANCE_BUILD_TYPE,
};
use serde_json::json;
use std::{
    io::Read,
    path::Path,
    time::{SystemTime, UNIX_EPOCH},
};

fn read(path: &Path, maximum: usize) -> Vec<u8> {
    let mut bytes = Vec::new();
    std::fs::File::open(path)
        .unwrap()
        .take(maximum as u64 + 1)
        .read_to_end(&mut bytes)
        .unwrap();
    assert!(bytes.len() <= maximum);
    bytes
}
async fn publish_package(
    client: &HttpOciRegistry,
    origin: &str,
) -> (PackageSigningSubject, BuildObservation) {
    let root = std::env::var("LSF_OCI_PROVENANCE_INPUT")
        .expect("pass --provenance-input to owned registry runner");
    let root = Path::new(&root);
    let package_limits = PackagingLimits::default();
    let limits = ProvenanceLimits::default();
    let observation = decode_build_observation(
        &read(&root.join("observation.json"), limits.max_payload_bytes),
        limits,
    )
    .unwrap();
    let source = decode_package_source(
        &read(
            &root.join("package-source.json"),
            package_limits.package.max_document_bytes,
        ),
        package_limits,
    )
    .unwrap();
    let package = build_package(
        read_package_input(root, &source, package_limits).unwrap(),
        package_limits,
    )
    .unwrap();
    let subject = PackageSigningSubject::from_package(
        package.manifest_bytes(),
        package.config_bytes(),
        package_limits.package,
    )
    .unwrap();
    assert_eq!(
        subject.component_digest().unwrap().as_str(),
        observation.component_digest
    );
    assert_eq!(subject.component_size(), Some(observation.component_size));
    assert!(
        package.surface().is_some(),
        "real generated component must pass semantic package validation"
    );
    let manifest = decode_manifest(package.manifest_bytes(), package_limits.package).unwrap();
    let layers = manifest
        .layers
        .into_iter()
        .zip(package.layers().iter().map(|blob| blob.bytes().to_vec()))
        .collect();
    let request = OciPushRequest::new(
        reference(origin, "observed-echo"),
        OciManifestBytes::new(
            package.manifest_bytes().to_vec(),
            package_limits.package.max_document_bytes,
        )
        .unwrap(),
        package.config_bytes().to_vec(),
        layers,
        package_limits.package,
    )
    .unwrap();
    assert_eq!(
        client.push(request).await.unwrap(),
        subject.subject().digest
    );
    let pulled_package = client
        .pull_package(&reference(origin, subject.subject().digest.as_str()))
        .await
        .unwrap();
    let received_subject = PackageSigningSubject::from_package(
        pulled_package.request().manifest().as_bytes(),
        pulled_package.request().config_bytes(),
        package_limits.package,
    )
    .unwrap();
    assert_eq!(received_subject, subject);
    drop(pulled_package);
    (received_subject, observation)
}

pub async fn roundtrip(client: &HttpOciRegistry, origin: &str) {
    let (subject, observation) = publish_package(client, origin).await;
    let limits = ProvenanceLimits::default();

    // Provisioned only after the build process has exited. This explicit test
    // builder/key policy is independent of registry credentials and DTO flags.
    let generated = generate_signing_key().unwrap();
    let public = *generated.public_key();
    let signer = LocalBuilderSigner::from_pkcs8(
        generated.into_pkcs8(),
        "observed-test-builder".into(),
        public,
    )
    .unwrap();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs();
    let evidence = signer
        .sign_build(
            &subject,
            &observation,
            SignatureValidity {
                issued_at: now,
                expires_at: now + 3600,
            },
            limits,
        )
        .unwrap();
    let descriptor = decode_referrer(evidence.manifest_bytes(), PackageLimits::default())
        .unwrap()
        .layers
        .remove(0);
    let request = OciPushRequest::new_referrer(
        reference(origin, "observed-echo-provenance"),
        OciManifestBytes::new(evidence.manifest_bytes().to_vec(), 4096).unwrap(),
        evidence.config_bytes().to_vec(),
        vec![(descriptor, evidence.payload_bytes().to_vec())],
        PackageLimits::default(),
    )
    .unwrap();
    assert_eq!(client.push(request).await.unwrap(), *evidence.digest());
    let discovered = client
        .list_referrers(
            &reference(origin, subject.subject().digest.as_str()),
            Some(EvidenceKind::Provenance.artifact_type()),
        )
        .await
        .unwrap();
    assert!(discovered
        .iter()
        .any(|item| item.digest == evidence.digest().as_str()));
    let pulled = client
        .pull_package(&reference(origin, evidence.digest().as_str()))
        .await
        .unwrap();
    let received = pulled.request();
    assert_eq!(received.manifest().as_bytes(), evidence.manifest_bytes());
    let (_, payload) = received.layers().next().unwrap();
    assert_eq!(payload, evidence.payload_bytes());
    let verifier = verifier(public, &observation, now);
    let proof = verifier
        .verify_package(
            &subject,
            ProvenanceEvidenceRef {
                manifest: received.manifest().as_bytes(),
                config: received.config_bytes(),
                payload,
            },
            now,
        )
        .unwrap();
    assert_eq!(proof.subject(), subject.subject());
    assert_eq!(proof.evidence_digest(), evidence.digest());
    assert_eq!(
        proof.component_digest(),
        subject.component_digest().unwrap()
    );
    assert_eq!(
        proof.source_snapshot_digest().as_str(),
        observation.source.snapshot_digest
    );
    assert_eq!(proof.source_revision(), observation.source.revision);
    verifier.check_current(&proof, now + 1).unwrap();
}

fn verifier(public: [u8; 32], observation: &BuildObservation, now: u64) -> BuilderVerifier {
    let limits = ProvenanceLimits::default();
    assert_eq!(
        observation.source.repository,
        "https://github.com/KirilsTurkins/latent-service-fabric"
    );
    let policy = BuilderPolicy::from_json(&serde_json::to_vec(&json!({
        "formatVersion":1,"scope":"observed-build-test","generation":1,
        "validFrom":now-1,"validUntil":now+7200,"maxSignatureLifetimeSeconds":3600,"maxProofAgeSeconds":60,
        "keys":[{"builderId":"observed-test-builder","publicKey":STANDARD.encode(public),"validFrom":now-1,"validUntil":now+7200}],
        "requirements":[{"builderId":"observed-test-builder","buildType":PROVENANCE_BUILD_TYPE,
            "sourceRepository":"https://github.com/KirilsTurkins/latent-service-fabric",
            "sourceRevision":observation.source.revision,"sourceSnapshotDigest":observation.source.snapshot_digest,
            "requireReproducible":false}],
    })).unwrap(), limits).unwrap();
    let revocations = BuilderRevocationSnapshot::from_json(&serde_json::to_vec(&json!({
        "formatVersion":1,"scope":"observed-build-test","generation":1,"policyDigest":policy.digest().as_str(),
        "validFrom":now-1,"validUntil":now+7200,"revokedKeys":[],"revokedBuilders":[],
    })).unwrap(), limits).unwrap();
    BuilderVerifier::new(BuilderTrust::new(policy, revocations).unwrap(), limits, now).unwrap()
}

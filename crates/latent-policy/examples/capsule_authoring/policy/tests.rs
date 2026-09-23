//! Real publisher/builder proofs for the isolated demonstration's exact window.
use super::*;
use latent_artifacts::package::PackageLimits;
use latent_core::PublisherId;
use latent_signing::*;
use serde_json::Value;

const NOW: u64 = 10_000;

struct Fixture {
    subject: PackageSigningSubject,
    signature: SignatureEvidence,
    provenance: ProvenanceEvidence,
    policy: Value,
}

impl Fixture {
    fn new() -> Self {
        let subject = PackageSigningSubject::from_package(
            include_bytes!(concat!(
                env!("CARGO_MANIFEST_DIR"),
                "/../../examples/package-format/capsule/manifest.json"
            )),
            include_bytes!(concat!(
                env!("CARGO_MANIFEST_DIR"),
                "/../../examples/package-format/capsule/config.json"
            )),
            PackageLimits::default(),
        )
        .unwrap();
        let digest = format!("sha256:{}", "b".repeat(64));
        let observation = BuildObservation {
            format_version: 1,
            build_type: GO_CAPSULE_BUILD_TYPE.into(),
            source: BuildSource {
                repository: "https://example.com/source".into(),
                revision: "b".repeat(64),
                snapshot_digest: digest.clone(),
                repository_trust: "operator-asserted".into(),
                capture: "explicit-input-files".into(),
            },
            component_digest: subject.component_digest().unwrap().to_string(),
            component_size: subject.component_size().unwrap(),
            materials: [
                "build-recipe",
                "componentize-go",
                "contracts-tool",
                "dependency-lock",
                "go",
                "package-inputs",
                "packager",
                "source-snapshot",
                "toolchain-config",
                "wasm-tools",
            ]
            .into_iter()
            .map(|name| BuildMaterial {
                name: name.into(),
                digest: digest.clone(),
                size: 1,
            })
            .collect(),
            parameters: BuildRecipe::GoCapsule(GoCapsuleBuildParameters {
                go_package: "demo".into(),
                compiler: "componentize-go".into(),
                target: "wasm32-wasip1".into(),
                runtime: "go-component-async-v1".into(),
                locked: true,
                ambient_wasi: false,
            }),
            started_at: NOW - 10,
            finished_at: NOW - 1,
            reproducibility: "not-checked".into(),
            hermetic: false,
            dependency_completeness: "declared-inputs-incomplete".into(),
        };
        let publisher_key = generate_signing_key().unwrap();
        let publisher_public = *publisher_key.public_key();
        let publisher = LocalSigner::from_pkcs8(
            publisher_key.into_pkcs8(),
            PublisherId(PUBLISHER.into()),
            publisher_public,
        )
        .unwrap();
        let builder_key = generate_signing_key().unwrap();
        let builder_public = *builder_key.public_key();
        let builder = LocalBuilderSigner::from_pkcs8(
            builder_key.into_pkcs8(),
            BUILDER.into(),
            builder_public,
        )
        .unwrap();
        let (_, document) =
            create(NOW, &publisher_public, &builder_public, &[&observation]).unwrap();
        let validity = SignatureValidity {
            issued_at: NOW,
            expires_at: NOW + DEMO_VALIDITY_SECONDS,
        };
        Self {
            signature: publisher
                .sign_package(&subject, validity, SignatureLimits::default())
                .unwrap(),
            provenance: builder
                .sign_build(
                    &subject,
                    &observation,
                    validity,
                    ProvenanceLimits::default(),
                )
                .unwrap(),
            subject,
            policy: serde_json::from_slice(&document).unwrap(),
        }
    }
}

fn verifiers(mut document: Value) -> (PublisherVerifier, BuilderVerifier) {
    let publisher = PublisherPolicy::from_json(
        &serde_json::to_vec(&document["publisher"]).unwrap(),
        SignatureLimits::default(),
    )
    .unwrap();
    let builder = BuilderPolicy::from_json(
        &serde_json::to_vec(&document["builder"]).unwrap(),
        ProvenanceLimits::default(),
    )
    .unwrap();
    document["publisherRevocations"]["policyDigest"] = json!(publisher.digest().as_str());
    document["builderRevocations"]["policyDigest"] = json!(builder.digest().as_str());
    let publisher_revocations = RevocationSnapshot::from_json(
        &serde_json::to_vec(&document["publisherRevocations"]).unwrap(),
        SignatureLimits::default(),
    )
    .unwrap();
    let builder_revocations = BuilderRevocationSnapshot::from_json(
        &serde_json::to_vec(&document["builderRevocations"]).unwrap(),
        ProvenanceLimits::default(),
    )
    .unwrap();
    (
        PublisherVerifier::new(
            PublisherTrust::new(publisher, publisher_revocations).unwrap(),
            SignatureLimits::default(),
            NOW,
        )
        .unwrap(),
        BuilderVerifier::new(
            BuilderTrust::new(builder, builder_revocations).unwrap(),
            ProvenanceLimits::default(),
            NOW,
        )
        .unwrap(),
    )
}

#[test]
fn demo_proofs_cover_documented_window_but_never_extend_signature_expiry() {
    let fixture = Fixture::new();
    assert_eq!(DEMO_VALIDITY_SECONDS, 1800);
    for role in ["publisher", "builder"] {
        assert_eq!(
            fixture.policy[role]["maxProofAgeSeconds"],
            DEMO_VALIDITY_SECONDS
        );
    }
    let (publisher, builder) = verifiers(fixture.policy);
    let signature = publisher
        .verify_package(&fixture.subject, fixture.signature.as_ref(), NOW)
        .unwrap();
    let provenance = builder
        .verify_package(&fixture.subject, fixture.provenance.as_ref(), NOW)
        .unwrap();
    assert_eq!(signature.valid_until(), NOW + 1800);
    assert_eq!(provenance.valid_until(), NOW + 1800);
    for at in [NOW + 61, NOW + 900, NOW + 1799] {
        publisher.check_current(&signature, at).unwrap();
        builder.check_current(&provenance, at).unwrap();
    }
    assert_eq!(
        publisher
            .check_current(&signature, NOW + 1800)
            .unwrap_err()
            .reason(),
        SignatureFailure::StaleProof
    );
    assert_eq!(
        builder
            .check_current(&provenance, NOW + 1800)
            .unwrap_err()
            .reason(),
        SignatureFailure::StaleProof
    );
    // Even explicit cryptographic re-verification cannot extend expired signatures.
    assert_eq!(
        publisher
            .verify_package(&fixture.subject, fixture.signature.as_ref(), NOW + 1800)
            .unwrap_err()
            .reason(),
        SignatureFailure::SignatureExpired
    );
    assert_eq!(
        builder
            .verify_package(&fixture.subject, fixture.provenance.as_ref(), NOW + 1800)
            .unwrap_err()
            .reason(),
        SignatureFailure::SignatureExpired
    );
}

#[test]
fn demo_publisher_and_builder_proof_age_ceilings_remain_independent() {
    let fixture = Fixture::new();
    for role in ["publisher", "builder"] {
        let mut policy = fixture.policy.clone();
        policy[role]["maxProofAgeSeconds"] = json!(60);
        let (publisher, builder) = verifiers(policy);
        let signature = publisher
            .verify_package(&fixture.subject, fixture.signature.as_ref(), NOW)
            .unwrap();
        let provenance = builder
            .verify_package(&fixture.subject, fixture.provenance.as_ref(), NOW)
            .unwrap();
        let publisher_result = publisher.check_current(&signature, NOW + 61);
        let builder_result = builder.check_current(&provenance, NOW + 61);
        if role == "publisher" {
            assert_eq!(
                publisher_result.unwrap_err().reason(),
                SignatureFailure::StaleProof
            );
            builder_result.unwrap();
        } else {
            publisher_result.unwrap();
            assert_eq!(
                builder_result.unwrap_err().reason(),
                SignatureFailure::StaleProof
            );
        }
    }
}

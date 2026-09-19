use super::support::{self, *};
use crate::*;
use base64::{engine::general_purpose::STANDARD, Engine};
use latent_artifacts::package::PackageLimits;
use serde_json::{json, Value};

mod angular;

fn subject(ssr: bool) -> PackageSigningSubject {
    // Existing format fixtures isolate builder authentication; they deliberately
    // do not claim executable web-profile or catalog admission conformance.
    let (manifest, config): (&[u8], &[u8]) = if ssr {
        (
            include_bytes!("../../../../../examples/package-format/ssr-package/manifest.json"),
            include_bytes!("../../../../../examples/package-format/ssr-package/config.json"),
        )
    } else {
        (
            include_bytes!("../../../../../examples/package-format/browser-assets/manifest.json"),
            include_bytes!("../../../../../examples/package-format/browser-assets/config.json"),
        )
    };
    PackageSigningSubject::from_package(manifest, config, PackageLimits::default()).unwrap()
}

fn observation(subject: &PackageSigningSubject) -> WebBuildObservation {
    let outputs = subject.web_outputs().unwrap();
    let digest = format!("sha256:{}", "b".repeat(64));
    WebBuildObservation {
        format_version: 1,
        build_type: WEB_ASSEMBLY_BUILD_TYPE.into(),
        source: BuildSource {
            repository: "https://example.com/source".into(),
            revision: "b".repeat(64),
            snapshot_digest: digest.clone(),
            repository_trust: "operator-asserted".into(),
            capture: "explicit-input-files".into(),
        },
        outputs_digest: outputs.digest().to_string(),
        outputs_count: outputs.count(),
        outputs_bytes: outputs.bytes(),
        materials: [
            "source-snapshot",
            "build-recipe",
            "toolchain-config",
            "package-assembler",
        ]
        .into_iter()
        .map(|name| BuildMaterial {
            name: name.into(),
            digest: digest.clone(),
            size: 1,
        })
        .collect(),
        parameters: WebAssemblyRecipe {
            assembler: "lsf-web-package-assembly".into(),
            recipe_version: 1,
            input_mode: "explicit-supplied-files".into(),
        }
        .into(),
        started_at: 900,
        finished_at: 1000,
        reproducibility: "not-checked".into(),
        hermetic: false,
        dependency_completeness: "declared-inputs-incomplete".into(),
    }
}

fn signed(signer: &LocalBuilderSigner, subject: &PackageSigningSubject) -> ProvenanceEvidence {
    signer
        .sign_web_build(
            subject,
            &observation(subject),
            SignatureValidity {
                issued_at: 1000,
                expires_at: 2000,
            },
            ProvenanceLimits::default(),
        )
        .unwrap()
}

fn policy(public: &str) -> Value {
    let mut value = policy_value(public);
    value["requirements"][0]["buildType"] = WEB_ASSEMBLY_BUILD_TYPE.into();
    value
}

#[test]
fn web_outputs_are_authenticated_without_inventing_a_component_or_admission() {
    let (signer, public, fingerprint) = signer(BUILDER);
    for ssr in [false, true] {
        let subject = subject(ssr);
        assert!(subject.component_digest().is_none());
        let evidence = signed(&signer, &subject);
        let owner = verifier(&policy(&public));
        let proof = owner
            .verify_web_package(&subject, evidence.as_ref(), NOW)
            .unwrap();
        let outputs = subject.web_outputs().unwrap();
        assert_eq!(proof.subject(), subject.subject());
        assert_eq!(proof.outputs_digest(), outputs.digest());
        assert_eq!(
            (proof.outputs_count(), proof.outputs_bytes()),
            (outputs.count(), outputs.bytes())
        );
        assert_eq!(proof.builder_id(), BUILDER);
        assert_eq!(proof.key_fingerprint().as_str(), fingerprint);
        assert_eq!(
            proof.source_snapshot_digest().as_str(),
            observation(&subject).source.snapshot_digest
        );
        assert_eq!(proof.evidence_digest(), evidence.digest());
        owner.check_web_current(&proof, NOW + 59).unwrap();
        assert_eq!(
            owner
                .check_web_current(&proof, NOW + 60)
                .unwrap_err()
                .reason(),
            SignatureFailure::StaleProof
        );
        assert!(owner
            .verify_package(&subject, evidence.as_ref(), NOW + 60)
            .is_err());
    }
}

#[test]
fn web_assembly_requires_explicit_builder_and_source_policy() {
    let (signer, public, _) = signer(BUILDER);
    let subject = subject(false);
    let evidence = signed(&signer, &subject);
    assert_eq!(
        verifier(&policy_value(&public))
            .verify_web_package(&subject, evidence.as_ref(), NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::PredicateDisallowed
    );
    for (field, wrong) in [
        ("sourceRepository", json!("https://example.com/different")),
        ("sourceRevision", json!("c".repeat(64))),
        (
            "sourceSnapshotDigest",
            json!(format!("sha256:{}", "c".repeat(64))),
        ),
        ("requireReproducible", json!(true)),
    ] {
        let mut policy = policy(&public);
        policy["requirements"][0][field] = wrong;
        assert_eq!(
            verifier(&policy)
                .verify_web_package(&subject, evidence.as_ref(), NOW)
                .unwrap_err()
                .reason(),
            SignatureFailure::SourceDisallowed
        );
    }
    let (wrong, _, _) = self::signer("different-builder");
    let wrong = signed(&wrong, &subject);
    assert_eq!(
        verifier(&policy(&public))
            .verify_web_package(&subject, wrong.as_ref(), NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::UnapprovedKey
    );
}

#[test]
fn web_evidence_and_output_identities_cannot_be_cross_paired_with_capsules_or_other_packages() {
    let (signer, public, _) = signer(BUILDER);
    let browser = subject(false);
    let ssr = subject(true);
    let evidence = signed(&signer, &browser);
    let owner = verifier(&policy(&public));
    for different in [ssr, support::subject()] {
        assert_eq!(
            owner
                .verify_web_package(&different, evidence.as_ref(), NOW)
                .unwrap_err()
                .reason(),
            SignatureFailure::SubjectMismatch
        );
    }
    for index in 0..3 {
        let mut observed = observation(&browser);
        match index {
            0 => observed.outputs_digest = format!("sha256:{}", "c".repeat(64)),
            1 => observed.outputs_count += 1,
            _ => observed.outputs_bytes += 1,
        }
        assert_eq!(
            signer
                .sign_web_build(
                    &browser,
                    &observed,
                    SignatureValidity {
                        issued_at: 1000,
                        expires_at: 2000
                    },
                    ProvenanceLimits::default()
                )
                .unwrap_err()
                .reason(),
            SignatureFailure::SubjectMismatch
        );
    }
    let old = support::signed(&signer, &support::observation());
    assert!(inspect_web_provenance(old.payload_bytes(), ProvenanceLimits::default()).is_err());
    assert!(inspect_provenance(evidence.payload_bytes(), ProvenanceLimits::default()).is_err());
}

#[test]
fn web_payload_tampering_needs_a_new_signature_even_with_valid_referrer_hashes() {
    let (signer, public, _) = signer(BUILDER);
    let subject = subject(false);
    let evidence = signed(&signer, &subject);
    let mut envelope: Value = serde_json::from_slice(evidence.payload_bytes()).unwrap();
    let mut payload: Value = serde_json::from_slice(
        &STANDARD
            .decode(envelope["payload"].as_str().unwrap())
            .unwrap(),
    )
    .unwrap();
    payload["predicate"]["observation"]["source"]["repository"] =
        "https://example.com/altered".into();
    envelope["payload"] = STANDARD
        .encode(serde_json::to_vec(&payload).unwrap())
        .into();
    let tampered = ProvenanceEvidence::from_web_envelope(
        &subject,
        &serde_json::to_vec(&envelope).unwrap(),
        ProvenanceLimits::default(),
    )
    .unwrap();
    assert_eq!(
        verifier(&policy(&public))
            .verify_web_package(&subject, tampered.as_ref(), NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::InvalidSignature
    );
    let wrong_referrer = ProvenanceEvidenceRef {
        payload: tampered.payload_bytes(),
        ..evidence.as_ref()
    };
    assert_eq!(
        verifier(&policy(&public))
            .verify_web_package(&subject, wrong_referrer, NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::IntegrityMismatch
    );
}

#[test]
fn web_revocation_expiry_trust_replacement_and_clock_floor_are_fail_closed() {
    let (signer, public, fingerprint) = signer(BUILDER);
    let subject = subject(false);
    let evidence = signed(&signer, &subject);
    for (field, revoked) in [
        ("revokedKeys", fingerprint.as_str()),
        ("revokedBuilders", BUILDER),
    ] {
        let trust = trust(&policy(&public), |value| value[field] = json!([revoked]));
        let owner = BuilderVerifier::new(trust, ProvenanceLimits::default(), NOW).unwrap();
        assert_eq!(
            owner
                .verify_web_package(&subject, evidence.as_ref(), NOW)
                .unwrap_err()
                .reason(),
            SignatureFailure::Revoked
        );
    }
    let owner = verifier(&policy(&public));
    let proof = owner
        .verify_web_package(&subject, evidence.as_ref(), NOW)
        .unwrap();
    let mut next = policy(&public);
    next["generation"] = 2.into();
    owner
        .replace_trust(proof.state_id(), trust(&next, |_| {}), NOW)
        .unwrap();
    assert_eq!(
        owner.check_web_current(&proof, NOW).unwrap_err().reason(),
        SignatureFailure::StaleProof
    );
    assert_eq!(
        owner
            .verify_web_package(&subject, evidence.as_ref(), 2000)
            .unwrap_err()
            .reason(),
        SignatureFailure::SignatureExpired
    );
    assert_eq!(
        owner
            .verify_web_package(&subject, evidence.as_ref(), NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::ClockRegression
    );
    assert_eq!(owner.clock_floor(), 2000);
}

#[test]
fn web_observations_reject_unbounded_materials_duplicates_and_fake_compiler_claims() {
    let subject = subject(false);
    let original = observation(&subject);
    let bytes = serde_json::to_string(&original).unwrap();
    for bad in [
        bytes.replacen('{', "{\"formatVersion\":1,", 1),
        bytes.replace("\"hermetic\":false", "\"hermetic\":true"),
        bytes.replace("explicit-supplied-files", "angular-compiler"),
        bytes.replace("\"outputsCount\":2", "\"outputsCount\":-1"),
    ] {
        assert!(decode_web_build_observation(bad.as_bytes(), ProvenanceLimits::default()).is_err());
    }
    let (signer, _, _) = signer(BUILDER);
    let mut excessive = original;
    excessive.materials.reserve_exact(65);
    assert_eq!(
        signer
            .sign_web_build(
                &subject,
                &excessive,
                SignatureValidity {
                    issued_at: 1000,
                    expires_at: 2000
                },
                ProvenanceLimits::default()
            )
            .unwrap_err()
            .reason(),
        SignatureFailure::ResourceLimit
    );
    let mut missing = observation(&subject);
    missing
        .materials
        .retain(|value| value.name != "package-assembler");
    assert!(decode_web_build_observation(
        &serde_json::to_vec(&missing).unwrap(),
        ProvenanceLimits::default()
    )
    .is_err());
}

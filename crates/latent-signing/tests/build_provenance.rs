#[path = "build_provenance/inputs.rs"]
mod inputs;
#[path = "build_provenance/support.rs"]
mod support;

use base64::{engine::general_purpose::STANDARD, Engine};
use latent_core::PublisherId;
use latent_signing::*;
use serde_json::Value;
use support::*;

fn changed_statement(evidence: &ProvenanceEvidence, update: impl FnOnce(&mut Value)) -> Vec<u8> {
    let mut envelope: Value = serde_json::from_slice(evidence.payload_bytes()).unwrap();
    let payload = STANDARD
        .decode(envelope["payload"].as_str().unwrap())
        .unwrap();
    let mut statement = serde_json::from_slice(&payload).unwrap();
    update(&mut statement);
    envelope["payload"] = STANDARD
        .encode(serde_json::to_vec(&statement).unwrap())
        .into();
    serde_json::to_vec(&envelope).unwrap()
}

#[test]
fn same_key_publisher_signature_cannot_authorize_build_provenance() {
    let generated = generate_signing_key().unwrap();
    let public = *generated.public_key();
    let pkcs8 = generated.into_pkcs8();
    let builder = LocalBuilderSigner::from_pkcs8(pkcs8.clone(), BUILDER.into(), public).unwrap();
    let publisher = LocalSigner::from_pkcs8(pkcs8, PublisherId(BUILDER.into()), public).unwrap();
    let provenance = signed(&builder, &observation());
    let package_signature = publisher
        .sign_package(
            &subject(),
            SignatureValidity {
                issued_at: 1000,
                expires_at: 2000,
            },
            SignatureLimits::default(),
        )
        .unwrap();
    assert_eq!(
        inspect_provenance(
            package_signature.payload_bytes(),
            ProvenanceLimits::default()
        )
        .unwrap_err()
        .reason(),
        SignatureFailure::UnsupportedProfile
    );
    assert_eq!(
        SignatureEvidence::from_envelope(
            &subject(),
            provenance.payload_bytes(),
            SignatureLimits::default()
        )
        .unwrap_err()
        .reason(),
        SignatureFailure::UnsupportedProfile
    );
    let publisher_envelope: Value =
        serde_json::from_slice(package_signature.payload_bytes()).unwrap();
    let mut forged: Value = serde_json::from_slice(provenance.payload_bytes()).unwrap();
    forged["signatures"] = publisher_envelope["signatures"].clone();
    let forged = ProvenanceEvidence::from_envelope(
        &subject(),
        &serde_json::to_vec(&forged).unwrap(),
        ProvenanceLimits::default(),
    )
    .unwrap();
    assert_eq!(
        verifier(&policy_value(&STANDARD.encode(public)))
            .verify_package(&subject(), forged.as_ref(), NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::InvalidSignature
    );
}

#[test]
fn changing_signed_source_or_observation_requires_a_new_signature() {
    let (signer, public, _) = signer(BUILDER);
    let evidence = signed(&signer, &observation());
    for change in 0..4 {
        let payload = changed_statement(&evidence, |statement| {
            let observation = &mut statement["predicate"]["observation"];
            match change {
                0 => observation["source"]["repository"] = "https://example.com/other".into(),
                1 => observation["source"]["revision"] = "b".repeat(40).into(),
                2 => observation["reproducibility"] = "two-build-byte-equality".into(),
                _ => {
                    observation["materials"][0]["digest"] =
                        format!("sha256:{}", "c".repeat(64)).into();
                }
            }
        });
        // Recompute the detached referrer's content association. Format and hash
        // checks pass, while the approved builder's signature still rejects it.
        let forged =
            ProvenanceEvidence::from_envelope(&subject(), &payload, ProvenanceLimits::default())
                .unwrap();
        assert_eq!(
            verifier(&policy_value(&public))
                .verify_package(&subject(), forged.as_ref(), NOW)
                .unwrap_err()
                .reason(),
            SignatureFailure::InvalidSignature
        );
    }
}

#[test]
fn package_and_component_substitution_fail_before_authority_is_returned() {
    let (signer, public, _) = signer(BUILDER);
    let evidence = signed(&signer, &observation());
    let mut manifest =
        include_bytes!("../../../examples/package-format/capsule/manifest.json").to_vec();
    manifest.push(b' ');
    let other = PackageSigningSubject::from_package(
        &manifest,
        include_bytes!("../../../examples/package-format/capsule/config.json"),
        latent_artifacts::package::PackageLimits::default(),
    )
    .unwrap();
    assert_ne!(subject().subject().digest, other.subject().digest);
    assert_eq!(
        verifier(&policy_value(&public))
            .verify_package(&other, evidence.as_ref(), NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::SubjectMismatch
    );
    for field in ["componentDigest", "componentSize"] {
        let payload = changed_statement(&evidence, |statement| {
            statement["predicate"]["observation"][field] = if field == "componentDigest" {
                format!("sha256:{}", "f".repeat(64)).into()
            } else {
                (subject().component_size().unwrap() + 1).into()
            };
        });
        assert_eq!(
            ProvenanceEvidence::from_envelope(&subject(), &payload, ProvenanceLimits::default())
                .unwrap_err()
                .reason(),
            SignatureFailure::SubjectMismatch
        );
    }
}

#[test]
fn detached_evidence_cannot_substitute_layer_bytes_or_configuration() {
    let (signer, public, _) = signer(BUILDER);
    let evidence = signed(&signer, &observation());
    let mut corrupt = evidence.payload_bytes().to_vec();
    corrupt.push(b' ');
    let borrowed = ProvenanceEvidenceRef {
        manifest: evidence.manifest_bytes(),
        config: b"{}",
        payload: &corrupt,
    };
    assert_eq!(
        verifier(&policy_value(&public))
            .verify_package(&subject(), borrowed, NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::IntegrityMismatch
    );
    let borrowed = ProvenanceEvidenceRef {
        config: b"[]",
        ..evidence.as_ref()
    };
    assert_eq!(
        verifier(&policy_value(&public))
            .verify_package(&subject(), borrowed, NOW)
            .unwrap_err()
            .reason(),
        SignatureFailure::IntegrityMismatch
    );
}

#[test]
fn unsupported_predicates_and_claimed_hermeticity_are_rejected() {
    let (signer, _, _) = signer(BUILDER);
    let evidence = signed(&signer, &observation());
    let payload = changed_statement(&evidence, |statement| {
        statement["predicateType"] = "https://slsa.dev/provenance/v1".into();
    });
    assert_eq!(
        inspect_provenance(&payload, ProvenanceLimits::default())
            .unwrap_err()
            .reason(),
        SignatureFailure::UnsupportedProfile
    );
    let mut observation = observation();
    observation.hermetic = true;
    assert_eq!(
        signer
            .sign_build(
                &subject(),
                &observation,
                SignatureValidity {
                    issued_at: 1000,
                    expires_at: 2000
                },
                ProvenanceLimits::default()
            )
            .unwrap_err()
            .reason(),
        SignatureFailure::MalformedProvenance
    );
}

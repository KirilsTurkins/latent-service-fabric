use super::*;
use crate::{
    format::{encode_claims, encode_signature, SignatureClaims},
    SignatureValidity,
};
use latent_artifacts::package::{decode_manifest, encode_manifest, encode_referrer};
use latent_core::PublisherId;

const MANIFEST: &[u8] =
    include_bytes!("../../../../examples/package-format/browser-assets/manifest.json");
const CONFIG: &[u8] =
    include_bytes!("../../../../examples/package-format/browser-assets/config.json");

fn subject() -> PackageSigningSubject {
    PackageSigningSubject::from_package(MANIFEST, CONFIG, PackageLimits::default()).unwrap()
}

fn envelope(subject: &PackageSigningSubject) -> Vec<u8> {
    let limits = SignatureLimits::default();
    let payload = encode_claims(
        &SignatureClaims {
            format_version: 1,
            publisher_id: PublisherId("fixture:publisher".to_owned()),
            subject: subject.subject().clone(),
            issued_at: 100,
            expires_at: 200,
        },
        limits,
    )
    .unwrap();
    // A syntactically valid all-zero signature deliberately proves that these
    // association helpers do not grant cryptographic authority.
    encode_signature(
        &payload,
        [0; 64],
        &artifact_blob_digest(b"untrusted hint"),
        limits,
    )
    .unwrap()
}

#[test]
fn detached_association_is_deterministic_and_explicitly_unverified() {
    let subject = subject();
    let payload = envelope(&subject);
    let limits = SignatureLimits::default();
    let evidence = SignatureEvidence::from_envelope(&subject, &payload, limits).unwrap();
    let duplicate = SignatureEvidence::from_envelope(&subject, &payload, limits).unwrap();
    assert_eq!(evidence.manifest_bytes(), duplicate.manifest_bytes());
    assert_eq!(
        evidence.digest(),
        &package_digest(evidence.manifest_bytes())
    );
    assert_ne!(evidence.digest(), &subject.subject().digest);
    assert_eq!(evidence.config_bytes(), b"{}");
    let inspected = inspect_evidence(&subject, evidence.as_ref(), limits).unwrap();
    assert_eq!(inspected.referrer_digest, *evidence.digest());
    assert_eq!(inspected.payload_digest, artifact_blob_digest(&payload));
    assert_eq!(inspected.signature.signature, [0; 64]);
    assert_eq!(
        inspected.signature.validity(),
        SignatureValidity {
            issued_at: 100,
            expires_at: 200
        }
    );
}

#[test]
fn outer_inner_and_content_associations_cannot_be_substituted() {
    let subject = subject();
    let limits = SignatureLimits::default();
    let evidence = SignatureEvidence::from_envelope(&subject, &envelope(&subject), limits).unwrap();
    let mut changed_manifest = decode_manifest(MANIFEST, PackageLimits::default()).unwrap();
    changed_manifest
        .annotations
        .insert("description".to_owned(), "changed metadata".to_owned());
    let changed_manifest = encode_manifest(&changed_manifest, PackageLimits::default()).unwrap();
    let changed =
        PackageSigningSubject::from_package(&changed_manifest, CONFIG, PackageLimits::default())
            .unwrap();
    assert_eq!(
        inspect_evidence(&changed, evidence.as_ref(), limits)
            .err()
            .unwrap()
            .reason(),
        SignatureFailure::SubjectMismatch
    );
    assert_eq!(
        SignatureEvidence::from_envelope(&changed, evidence.payload_bytes(), limits)
            .unwrap_err()
            .reason(),
        SignatureFailure::SubjectMismatch
    );

    let mut referrer =
        decode_referrer(evidence.manifest_bytes(), PackageLimits::default()).unwrap();
    referrer.subject = changed.subject().clone();
    let outer = encode_referrer(&referrer, PackageLimits::default()).unwrap();
    assert_eq!(
        inspect_evidence(
            &changed,
            SignatureEvidenceRef {
                manifest: &outer,
                ..evidence.as_ref()
            },
            limits
        )
        .err()
        .unwrap()
        .reason(),
        SignatureFailure::SubjectMismatch
    );

    for borrowed in [
        SignatureEvidenceRef {
            config: b"[]",
            ..evidence.as_ref()
        },
        SignatureEvidenceRef {
            payload: b"{}",
            ..evidence.as_ref()
        },
    ] {
        assert_eq!(
            inspect_evidence(&subject, borrowed, limits)
                .err()
                .unwrap()
                .reason(),
            SignatureFailure::IntegrityMismatch
        );
    }
}

#[test]
fn large_package_subject_does_not_expand_small_evidence_document_bound() {
    let mut manifest = decode_manifest(MANIFEST, PackageLimits::default()).unwrap();
    manifest
        .annotations
        .insert("first".into(), "a".repeat(2048));
    manifest
        .annotations
        .insert("second".into(), "b".repeat(2048));
    let manifest = encode_manifest(&manifest, PackageLimits::default()).unwrap();
    assert!(manifest.len() > 4096);
    let subject =
        PackageSigningSubject::from_package(&manifest, CONFIG, PackageLimits::default()).unwrap();
    let limits = SignatureLimits::default();
    let evidence = SignatureEvidence::from_envelope(&subject, &envelope(&subject), limits).unwrap();
    assert!(evidence.manifest_bytes().len() < 4096);
    inspect_evidence(&subject, evidence.as_ref(), limits).unwrap();
}

#[test]
fn existing_format_valid_paths_and_annotations_carry_no_extra_authority() {
    let subject = subject();
    let limits = SignatureLimits::default();
    let evidence = SignatureEvidence::from_envelope(&subject, &envelope(&subject), limits).unwrap();
    let mut referrer =
        decode_referrer(evidence.manifest_bytes(), PackageLimits::default()).unwrap();
    referrer.layers[0]
        .annotations
        .as_mut()
        .unwrap()
        .insert(LAYER_PATH_ANNOTATION.into(), "other/signature.json".into());
    for index in 0..32 {
        referrer
            .annotations
            .insert(format!("note{index}"), "untrusted".into());
    }
    let manifest = encode_referrer(&referrer, PackageLimits::default()).unwrap();
    let inspected = inspect_evidence(
        &subject,
        SignatureEvidenceRef {
            manifest: &manifest,
            ..evidence.as_ref()
        },
        limits,
    )
    .unwrap();
    assert_eq!(inspected.signature.subject(), subject.subject());
    assert_ne!(inspected.referrer_digest, *evidence.digest());
}

#[test]
fn borrowed_evidence_and_owned_emission_obey_lowered_resource_limits() {
    let subject = subject();
    let payload = envelope(&subject);
    let limits = SignatureLimits::default();
    let evidence = SignatureEvidence::from_envelope(&subject, &payload, limits).unwrap();
    let maximum = evidence.manifest_bytes().len().max(payload.len());
    let exact = SignatureLimits {
        max_envelope_bytes: maximum,
        ..limits
    };
    SignatureEvidence::from_envelope(&subject, &payload, exact).unwrap();
    inspect_evidence(&subject, evidence.as_ref(), exact).unwrap();
    let lower = SignatureLimits {
        max_envelope_bytes: maximum - 1,
        ..limits
    };
    assert_eq!(
        SignatureEvidence::from_envelope(&subject, &payload, lower)
            .unwrap_err()
            .reason(),
        SignatureFailure::ResourceLimit
    );
    assert_eq!(
        inspect_evidence(&subject, evidence.as_ref(), lower)
            .err()
            .unwrap()
            .reason(),
        SignatureFailure::ResourceLimit
    );
    assert_eq!(
        inspect_evidence(
            &subject,
            SignatureEvidenceRef {
                config: b"{} ",
                ..evidence.as_ref()
            },
            limits
        )
        .err()
        .unwrap()
        .reason(),
        SignatureFailure::ResourceLimit
    );
}

#[test]
fn package_subject_requires_exact_manifest_and_config_identity() {
    let direct = subject();
    let mut spaced = b" ".to_vec();
    spaced.extend_from_slice(MANIFEST);
    let other =
        PackageSigningSubject::from_package(&spaced, CONFIG, PackageLimits::default()).unwrap();
    assert_ne!(direct.subject().digest, other.subject().digest);
    assert_eq!(other.subject().digest, package_digest(&spaced));
    let mut config = CONFIG.to_vec();
    config.push(b' ');
    assert_eq!(
        PackageSigningSubject::from_package(MANIFEST, &config, PackageLimits::default())
            .unwrap_err()
            .reason(),
        SignatureFailure::IntegrityMismatch
    );
}

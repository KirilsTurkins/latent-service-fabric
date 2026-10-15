use base64::{engine::general_purpose::STANDARD, Engine};
use latent_artifacts::package::{artifact_blob_digest, package_digest, PackageLimits};
use latent_artifacts::{
    AdmissionAuthority, AdmissionBinding, AdmissionEvidence, PackageAdmissionUpload,
};
use latent_core::{PlatformError, PlatformErrorCode, TenantId};
use latent_manifest::{ManifestValidationProfile, RuntimeCompatibilityProfile};
use latent_packaging::PackagingLimits;
use latent_signing::{
    PackageSigningSubject, ProvenanceEvidence, ProvenanceLimits, SignatureEvidence, SignatureLimits,
};
use std::sync::{atomic::Ordering, Arc};

use super::super::receipt::Receipt;
use super::{Fixture, SupplyChainAuthority, NOW};

fn owner(fixture: &Fixture, root: &std::path::Path) -> SupplyChainAuthority {
    SupplyChainAuthority::open(root, fixture.approved(), fixture.clock.clone(), 5).unwrap()
}

fn binding(authority: &SupplyChainAuthority, fixture: &Fixture) -> AdmissionBinding {
    authority
        .verify(&TenantId("tests".into()), fixture.upload())
        .unwrap()
        .grant
        .binding()
        .clone()
}

fn assert_error(error: &PlatformError, code: PlatformErrorCode, message: &str) {
    assert_eq!(error.code, code);
    assert_eq!(error.message, message);
}

fn forged_signature(
    binding: &AdmissionBinding,
    mut upload: PackageAdmissionUpload,
    builder: bool,
) -> (AdmissionBinding, PackageAdmissionUpload) {
    let subject = PackageSigningSubject::from_package(
        &upload.manifest,
        &upload.configuration,
        PackageLimits::default(),
    )
    .unwrap();
    let evidence = if builder {
        &mut upload.provenance[0]
    } else {
        &mut upload.signatures[0]
    };
    let mut envelope: serde_json::Value = serde_json::from_slice(&evidence.payload).unwrap();
    let signature = &mut envelope["signatures"][0]["sig"];
    let mut bytes = STANDARD.decode(signature.as_str().unwrap()).unwrap();
    bytes[0] ^= 1;
    *signature = STANDARD.encode(bytes).into();
    let payload = serde_json::to_vec(&envelope).unwrap();
    *evidence = if builder {
        let checked =
            ProvenanceEvidence::from_envelope(&subject, &payload, ProvenanceLimits::default())
                .unwrap();
        AdmissionEvidence {
            manifest: checked.manifest_bytes().to_vec(),
            configuration: checked.config_bytes().to_vec(),
            payload: checked.payload_bytes().to_vec(),
        }
    } else {
        let checked =
            SignatureEvidence::from_envelope(&subject, &payload, SignatureLimits::default())
                .unwrap();
        AdmissionEvidence {
            manifest: checked.manifest_bytes().to_vec(),
            configuration: checked.config_bytes().to_vec(),
            payload: checked.payload_bytes().to_vec(),
        }
    };
    // Rebuild every untrusted association so only real cryptography can reject it.
    let mut receipt: Receipt = serde_json::from_slice(&binding.receipt).unwrap();
    if builder {
        receipt.provenance_manifest = package_digest(&evidence.manifest).to_string();
        receipt.provenance_payload = artifact_blob_digest(&evidence.payload).to_string();
    } else {
        receipt.signature_manifest = package_digest(&evidence.manifest).to_string();
        receipt.signature_payload = artifact_blob_digest(&evidence.payload).to_string();
    }
    let mut changed = binding.clone();
    changed.receipt = receipt.encode().unwrap();
    Receipt::validate_history(&changed).unwrap();
    (changed, upload)
}

#[test]
fn retained_recovery_requires_both_fresh_cryptographic_verifications() {
    let fixture = Fixture::new();
    let root = tempfile::tempdir().unwrap();
    let authority = owner(&fixture, root.path());
    let original = binding(&authority, &fixture);
    for builder in [false, true] {
        let (changed, upload) = forged_signature(&original, fixture.upload(), builder);
        let checked = Receipt::validate_retained(&changed, upload).unwrap();
        let error = authority.recover(&changed, checked).err().unwrap();
        assert_error(
            &error,
            PlatformErrorCode::PermissionDenied,
            "signature-invalid",
        );
        assert!(!error.retryable);
        assert!(!authority.inner.verifying.load(Ordering::Acquire));
        let recovered = authority.recover(&original, fixture.upload()).unwrap();
        assert_eq!(recovered.grant.binding(), &original);
        recovered.grant.check_current().unwrap();
    }
}

#[test]
fn retained_recovery_preserves_raw_capacity_cardinality_and_error_precedence() {
    assert_eq!(
        PackagingLimits::default().package.max_layer_bytes,
        64 * 1024 * 1024
    );
    let fixture = Fixture::new();
    let root = tempfile::tempdir().unwrap();
    let authority = owner(&fixture, root.path());
    let original = binding(&authority, &fixture);
    for case in 0..9 {
        let mut upload = fixture.upload();
        let mut previous = original.clone();
        match case {
            0 => upload.layers.reserve(257),
            1 => upload.layers[0].0.reserve(257),
            2 => upload.signatures.reserve(9),
            3 => upload.signatures.clear(),
            4 => upload
                .signatures
                .push(fixture.upload().signatures.remove(0)),
            5 => upload.provenance.clear(),
            6 => upload
                .provenance
                .push(fixture.upload().provenance.remove(0)),
            7 => {
                upload.layers.reserve(257);
                previous.receipt = b"{}".to_vec();
            }
            _ => upload.layers[0].1[0] ^= 1,
        }
        let error = authority.recover(&previous, upload).err().unwrap();
        let (code, message) = if case < 3 {
            (
                PlatformErrorCode::ResourceExhausted,
                "admission-storage-limit",
            )
        } else {
            (
                PlatformErrorCode::CorruptArtifact,
                "admission-receipt-corrupt",
            )
        };
        assert_error(&error, code, message);
        assert!(!error.retryable);
        assert!(error.details.is_empty());
        assert!(!authority.inner.verifying.load(Ordering::Acquire));
    }
    authority
        .recover(&original, fixture.upload())
        .unwrap()
        .grant
        .check_current()
        .unwrap();
}

#[test]
fn retained_recovery_does_not_hide_corruption_behind_expired_or_revoked_history() {
    for expired in [false, true] {
        let mut fixture = Fixture::new();
        let root = tempfile::tempdir().unwrap();
        let authority = owner(&fixture, root.path());
        let original = binding(&authority, &fixture);
        if expired {
            fixture.clock.set(2000);
        } else {
            fixture.policy["generation"] = 2.into();
            fixture.policy["publisherRevocations"]["generation"] = 2.into();
            fixture.policy["publisherRevocations"]["revokedPublishers"] =
                serde_json::json!(["publisher-a"]);
            authority.replace_policy(fixture.approved()).unwrap();
        }
        let mut upload = fixture.upload();
        upload.layers[0].1[0] ^= 1;
        let error = authority.recover(&original, upload).err().unwrap();
        assert_error(
            &error,
            PlatformErrorCode::CorruptArtifact,
            "admission-receipt-corrupt",
        );
        assert!(!authority.inner.verifying.load(Ordering::Acquire));
        let checked = Receipt::validate_retained(&original, fixture.upload()).unwrap();
        let denied = authority.recover(&original, checked).err().unwrap();
        assert_error(
            &denied,
            PlatformErrorCode::PermissionDenied,
            if expired {
                "signature-expired"
            } else {
                "signature-revoked"
            },
        );
        assert!(!authority.inner.verifying.load(Ordering::Acquire));
    }
}

#[test]
fn retained_structural_history_never_replaces_current_policy_clock_or_owner() {
    for case in 0..7 {
        let mut fixture = Fixture::new();
        if case == 4 {
            fixture.policy["validUntil"] = (NOW + 4).into();
        }
        let root = tempfile::tempdir().unwrap();
        let authority = owner(&fixture, root.path());
        let original = binding(&authority, &fixture);
        let checked = Receipt::validate_retained(&original, fixture.upload()).unwrap();
        if case < 4 {
            fixture.policy["generation"] = 2.into();
            match case {
                0 => fixture.policy["tenants"] = serde_json::json!([]),
                1 => {
                    fixture.policy["publisherRevocations"]["generation"] = 2.into();
                    fixture.policy["publisherRevocations"]["revokedPublishers"] =
                        serde_json::json!(["publisher-a"]);
                }
                2 => {
                    fixture.policy["builderRevocations"]["generation"] = 2.into();
                    fixture.policy["builderRevocations"]["revokedBuilders"] =
                        serde_json::json!(["builder-a"]);
                }
                _ => fixture.policy["sbom"]["detached"] = "required".into(),
            }
            authority.replace_policy(fixture.approved()).unwrap();
        } else {
            match case {
                4 => fixture.clock.set(NOW + 6),
                5 => fixture.clock.set(NOW - 1),
                _ => authority.retire(),
            }
        }
        let error = authority.recover(&original, checked).err().unwrap();
        let messages = [
            "admission-tenant-denied",
            "signature-revoked",
            "signature-revoked",
            "required-detached-sbom-missing",
            "admission-policy-expired",
            "admission-clock-regression",
            "admission-owner-retired",
        ];
        assert_error(
            &error,
            if case < 5 {
                PlatformErrorCode::PermissionDenied
            } else {
                PlatformErrorCode::Unavailable
            },
            messages[case],
        );
        assert!(!authority.inner.verifying.load(Ordering::Acquire));
    }
}

#[test]
fn retained_transaction_history_cannot_choose_a_more_permissive_manifest_profile() {
    let fixture = Fixture::transactional();
    let root = tempfile::tempdir().unwrap();
    let profile = ManifestValidationProfile::phase4(
        latent_core::BudgetProfile::Phase4,
        latent_core::PHASE4_HOST_ABI_V1,
        &latent_manifest::phase4_host_abi_digest(),
    )
    .unwrap();
    let selected = SupplyChainAuthority::open_with_runtime_and_manifest_profile(
        root.path(),
        fixture.approved(),
        fixture.clock.clone(),
        5,
        Arc::new(
            RuntimeCompatibilityProfile::new(
                "wasmtime",
                "48.0.3",
                "x86_64-unknown-linux-gnu",
                &["x86_64.sse2"],
                64 * 1024 * 1024,
                100_000_000,
            )
            .unwrap(),
        ),
        profile,
    )
    .unwrap();
    let original = binding(&selected, &fixture);
    selected
        .recover(&original, fixture.upload())
        .unwrap()
        .grant
        .check_current()
        .unwrap();
    selected.retire();
    drop(selected);
    fixture.clock.set(NOW + 5);
    let strict = owner(&fixture, root.path());
    let error = strict.recover(&original, fixture.upload()).err().unwrap();
    assert_error(
        &error,
        PlatformErrorCode::CorruptArtifact,
        "admission-receipt-corrupt",
    );
    assert!(!strict.inner.verifying.load(Ordering::Acquire));
}

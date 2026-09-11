use super::*;
use latent_artifacts::package::{package_digest, EvidenceKind, PackageKind, PackageLimits};

mod fixtures;
use fixtures::{evidence_fixture, fixture, reference};

#[test]
fn raw_identity_preserves_exact_bytes_and_is_not_json_validation() {
    let compact = OciManifestBytes::new(b"{}".to_vec(), 32).unwrap();
    let spaced = OciManifestBytes::new(b"{ }\n".to_vec(), 32).unwrap();
    assert_ne!(compact.digest(), spaced.digest());
    assert_eq!(spaced.as_bytes(), b"{ }\n");
    assert_eq!(spaced.digest(), &package_digest(b"{ }\n"));
    let invalid_json = OciManifestBytes::new(b"not-json-secret".to_vec(), 32).unwrap();
    assert!(!format!("{invalid_json:?}").contains("not-json-secret"));
    assert_eq!(invalid_json.into_bytes(), b"not-json-secret");
}

#[test]
fn raw_identity_enforces_lowered_and_hard_bounds_and_discards_spare_capacity() {
    assert_eq!(
        OciManifestBytes::new(vec![0; 5], 4).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    for invalid in [
        0,
        PackageLimits::default().max_document_bytes + 1,
        usize::MAX,
    ] {
        assert_eq!(
            OciManifestBytes::new(vec![], invalid).unwrap_err().code,
            PlatformErrorCode::InvalidArgument
        );
    }
    let mut spare = Vec::with_capacity(1024);
    spare.extend_from_slice(b"{}");
    let bytes = OciManifestBytes::new(spare, 2).unwrap().into_bytes();
    assert_eq!(bytes.capacity(), 2);
    let ceiling = PackageLimits::default().max_document_bytes;
    assert!(OciManifestBytes::new(vec![0; ceiling], ceiling).is_ok());
    assert!(OciManifestBytes::new(vec![0; ceiling + 1], ceiling).is_err());
}

#[test]
fn package_upload_keeps_raw_manifest_and_binds_every_blob() {
    let limits = PackageLimits::default();
    let (manifest, config, uploads) = fixture(PackageKind::BrowserAssets);
    let mut bytes = manifest.into_bytes();
    bytes.push(b'\n');
    let manifest = OciManifestBytes::new(bytes.clone(), limits.max_document_bytes).unwrap();
    let expected = manifest.digest().clone();
    let upload =
        OciPushRequest::new(reference(), manifest, config.clone(), uploads, limits).unwrap();
    assert_eq!(upload.manifest().as_bytes(), bytes);
    assert_eq!(upload.manifest().digest(), &expected);
    assert_eq!(upload.layout().unwrap().digest(), &expected);
    assert_eq!(upload.config_bytes(), config);
    assert_eq!(upload.layers().next().unwrap().1, b"hello");
    assert_eq!(upload.reference().reference, "candidate");
    assert!(upload.capsule_layout().is_err());
    assert!(upload.referrer().is_none());
}

#[test]
fn package_upload_rejects_config_descriptor_content_and_count_changes() {
    let limits = PackageLimits::default();
    let (manifest, mut config, uploads) = fixture(PackageKind::BrowserAssets);
    config.push(b' ');
    assert!(OciPushRequest::new(reference(), manifest, config, uploads, limits).is_err());
    let (manifest, config, mut uploads) = fixture(PackageKind::BrowserAssets);
    uploads[0].0.media_type = "text/plain".into();
    assert_eq!(
        OciPushRequest::new(reference(), manifest, config, uploads, limits)
            .unwrap_err()
            .code,
        PlatformErrorCode::InvalidArgument
    );
    let (manifest, config, mut uploads) = fixture(PackageKind::BrowserAssets);
    uploads[0].1[0] ^= 1;
    assert_eq!(
        OciPushRequest::new(reference(), manifest, config, uploads, limits)
            .unwrap_err()
            .code,
        PlatformErrorCode::CorruptArtifact
    );
    let (manifest, config, _) = fixture(PackageKind::BrowserAssets);
    assert!(OciPushRequest::new(reference(), manifest, config, vec![], limits).is_err());
    let (manifest, config, mut uploads) = fixture(PackageKind::BrowserAssets);
    uploads.push(uploads[0].clone());
    assert!(OciPushRequest::new(reference(), manifest, config, uploads, limits).is_err());
}

#[test]
fn capsule_gate_rejects_opaque_ssr_without_confusing_wasm_or_packaging_with_admission() {
    let limits = PackageLimits::default();
    for kind in [PackageKind::Capsule, PackageKind::SsrPackage] {
        let (manifest, config, uploads) = fixture(kind);
        let upload = OciPushRequest::new(reference(), manifest, config, uploads, limits).unwrap();
        assert_eq!(
            upload.capsule_layout().is_ok(),
            kind == PackageKind::Capsule
        );
    }
}

#[test]
fn all_detached_evidence_kinds_preserve_subject_and_cannot_map_to_capsules() {
    let limits = PackageLimits::default();
    for kind in [
        EvidenceKind::Signature,
        EvidenceKind::Provenance,
        EvidenceKind::Sbom,
    ] {
        let (manifest, config, uploads) = evidence_fixture(kind);
        let digest = manifest.digest().clone();
        let upload =
            OciPushRequest::new_referrer(reference(), manifest, config, uploads, limits).unwrap();
        assert_eq!(upload.manifest().digest(), &digest);
        assert_eq!(upload.config_bytes(), b"{}");
        assert_eq!(
            upload.referrer().unwrap().subject.digest,
            package_digest(b"subject")
        );
        assert_eq!(upload.layers().next().unwrap().1, b"unverified evidence");
        assert!(upload.layout().is_none());
        assert!(upload.capsule_layout().is_err());
    }
}

#[test]
fn detached_evidence_rejects_mutated_empty_config_and_payload() {
    let limits = PackageLimits::default();
    let (manifest, _, uploads) = evidence_fixture(EvidenceKind::Signature);
    assert!(
        OciPushRequest::new_referrer(reference(), manifest, b"{ }".to_vec(), uploads, limits)
            .is_err()
    );
    let (manifest, config, mut uploads) = evidence_fixture(EvidenceKind::Signature);
    uploads[0].1[0] ^= 1;
    assert_eq!(
        OciPushRequest::new_referrer(reference(), manifest, config, uploads, limits)
            .unwrap_err()
            .code,
        PlatformErrorCode::CorruptArtifact
    );
    let (manifest, config, _) = evidence_fixture(EvidenceKind::Signature);
    assert!(OciPushRequest::new_referrer(reference(), manifest, config, vec![], limits).is_err());
}

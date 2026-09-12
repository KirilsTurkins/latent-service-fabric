//! Existing native-referrer transport carries the package's same exact inventory.
use latent_artifacts::package::{decode_referrer, EvidenceKind, PackageLimits};
use latent_oci::{HttpOciRegistry, OciManifestBytes, OciPushRequest, OciRegistry};
use latent_packaging::{
    attach_package_sbom, evaluate_sboms, PackageBundle, SbomEvidenceLimits, SbomEvidenceRef,
    SbomPolicy, SbomPolicyConfig, SbomPresence, SBOM_PATH,
};

use super::reference;

pub(super) async fn roundtrip(client: &HttpOciRegistry, origin: &str, package: &PackageBundle) {
    let limits = SbomEvidenceLimits::default();
    let evidence = attach_package_sbom(package, limits).unwrap();
    let manifest = decode_referrer(evidence.manifest_bytes(), PackageLimits::default()).unwrap();
    let request = OciPushRequest::new_referrer(
        reference(origin, "observed-echo-sbom"),
        OciManifestBytes::new(
            evidence.manifest_bytes().to_vec(),
            limits.max_manifest_bytes,
        )
        .unwrap(),
        evidence.config_bytes().to_vec(),
        vec![(
            manifest.layers[0].clone(),
            evidence.payload_bytes().to_vec(),
        )],
        PackageLimits::default(),
    )
    .unwrap();
    assert_eq!(client.push(request).await.unwrap(), *evidence.digest());
    let discovered = client
        .list_referrers(
            &reference(origin, package.layout().digest().as_str()),
            Some(EvidenceKind::Sbom.artifact_type()),
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
    let (_, payload) = received.layers().next().unwrap();
    assert_eq!(received.manifest().as_bytes(), evidence.manifest_bytes());
    assert_eq!(payload, package.blob(SBOM_PATH).unwrap());
    let policy = SbomPolicy::new(SbomPolicyConfig {
        format_version: 1,
        embedded: SbomPresence::Required,
        detached: SbomPresence::Required,
        require_source: vec![],
        require_license: vec![],
    })
    .unwrap();
    let result = evaluate_sboms(
        package,
        &[SbomEvidenceRef {
            manifest: received.manifest().as_bytes(),
            config: received.config_bytes(),
            payload,
        }],
        &policy,
        limits,
    )
    .unwrap();
    assert_eq!(result.package_digest(), package.layout().digest());
    assert_eq!(
        result.inventory_digest(),
        Some(package.sbom().unwrap().inventory_digest())
    );
    assert_eq!(result.referrer_digest(), Some(evidence.digest()));
    // The owned returned-package slot must be released before the provenance pull.
    drop(pulled);
}

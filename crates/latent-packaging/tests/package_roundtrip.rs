mod fixtures;
use fixtures::component::Options;
use latent_artifacts::package::{artifact_blob_digest, LayerRole, PackageKind};
use latent_packaging::{
    build_package, inspect_bundle, PackageInput, PackagingLimits, BUILD_INPUTS_PATH,
};

#[test]
fn identical_inputs_have_identical_package_bytes_regardless_of_mapping_order() {
    let input = fixtures::capsule(Options::default());
    let first = build_package(input.clone(), PackagingLimits::default()).unwrap();
    let mut reordered = input.clone();
    reordered.layers.reverse();
    let second = build_package(reordered, PackagingLimits::default()).unwrap();
    assert_eq!(first.layout().digest(), second.layout().digest());
    assert_eq!(first.manifest_bytes(), second.manifest_bytes());
    assert_eq!(first.config_bytes(), second.config_bytes());
    let inspected = inspect_bundle(fixtures::raw(&first), PackagingLimits::default()).unwrap();
    assert_eq!(first.layout().digest(), inspected.layout().digest());
    assert!(inspected.surface().is_some());
    let receipt = first.build_receipt().unwrap();
    assert_eq!(receipt.inputs.len(), input.layers.len());
    for identity in &receipt.inputs {
        let source = input
            .layers
            .iter()
            .find(|layer| layer.path == identity.path)
            .unwrap();
        assert_eq!(
            identity.input_digest,
            artifact_blob_digest(&source.bytes).as_str()
        );
        assert_eq!(identity.input_size, source.bytes.len() as u64);
        let output = first.blob(&identity.path).unwrap();
        assert_eq!(
            identity.output_digest,
            artifact_blob_digest(output).as_str()
        );
        assert_eq!(identity.output_size, output.len() as u64);
    }
}

#[test]
fn changed_inputs_change_identity_and_corrupt_or_missing_blobs_fail_inspection() {
    let input = fixtures::capsule(Options::default());
    let first = build_package(input.clone(), PackagingLimits::default()).unwrap();
    let mut changed = input;
    changed.layers.push(fixtures::layer(
        "client.js",
        LayerRole::Asset,
        "text/javascript",
        b"export const version = 2;".to_vec(),
    ));
    let second = build_package(changed, PackagingLimits::default()).unwrap();
    assert_ne!(first.layout().digest(), second.layout().digest());
    let mut damaged = fixtures::raw(&first);
    damaged.layers[0].1.push(b' ');
    assert!(inspect_bundle(damaged, PackagingLimits::default()).is_err());
    let mut missing = fixtures::raw(&first);
    missing.layers.pop();
    assert!(inspect_bundle(missing, PackagingLimits::default()).is_err());
}

#[test]
fn browser_and_ssr_packages_are_deterministic_non_executable_content() {
    for (kind, role, path, media, bytes) in [
        (
            PackageKind::BrowserAssets,
            LayerRole::Asset,
            "index.html",
            "text/html",
            b"<!doctype html><p>fixture</p>".as_slice(),
        ),
        (
            PackageKind::SsrPackage,
            LayerRole::Renderer,
            "renderer.js",
            "text/javascript",
            b"export const render = () => 'fixture';".as_slice(),
        ),
    ] {
        let input = PackageInput {
            kind,
            name: "web-fixture".into(),
            version: "1.0.0".into(),
            entrypoint: path.into(),
            annotations: std::collections::BTreeMap::default(),
            layers: vec![fixtures::layer(path, role, media, bytes.to_vec())],
        };
        let first = build_package(input.clone(), PackagingLimits::default()).unwrap();
        let second = build_package(input, PackagingLimits::default()).unwrap();
        assert_eq!(first.layout().digest(), second.layout().digest());
        assert!(first.surface().is_none());
        assert!(first.layout().component_release().is_none());
        assert_eq!(first.blob(path), Some(bytes));
    }
}

#[test]
fn reserved_receipts_duplicate_paths_and_declared_limits_are_enforced() {
    let valid = fixtures::capsule(Options::default());
    let mut reserved = valid.clone();
    reserved.layers.push(fixtures::layer(
        BUILD_INPUTS_PATH,
        LayerRole::Asset,
        "application/json",
        b"{}".to_vec(),
    ));
    assert!(build_package(reserved, PackagingLimits::default()).is_err());
    let mut duplicate = valid.clone();
    duplicate.layers.push(duplicate.layers[0].clone());
    assert!(build_package(duplicate, PackagingLimits::default()).is_err());
    let mut limited = PackagingLimits::default();
    limited.package.max_total_layer_bytes = 32;
    assert!(build_package(valid, limited).is_err());
}

use super::*;
use crate::package::{artifact_blob_digest, PackageLayer};

fn lock() -> WitLock {
    WitLock {
        format_version: 1,
        world: "example:fixture/fixture@1.0.0".to_owned(),
        contracts_digest: artifact_blob_digest(b"contracts"),
        packages: vec![WitLockedPackage {
            id: "example:fixture@1.0.0".to_owned(),
            source_path: "wit/example.wit".to_owned(),
            digest: artifact_blob_digest(b"package example:fixture@1.0.0; world fixture {}"),
            dependencies: Vec::new(),
        }],
    }
}

#[test]
fn locked_graph_has_stable_encoding_and_exact_pinned_identity() {
    let value = lock();
    let limits = PackageLimits::default();
    let bytes = encode_wit_lock(&value, limits).unwrap();
    assert_eq!(decode_wit_lock(&bytes, limits).unwrap(), value);
    assert_eq!(encode_wit_lock(&value, limits).unwrap(), bytes);
    assert!(!bytes.ends_with(b"\n"));
    let text = String::from_utf8(bytes).unwrap();
    assert!(text.starts_with("{\"formatVersion\":1,\"world\":\"example:fixture/fixture@1.0.0\","));
    assert!(text.contains("\"sourcePath\":\"wit/example.wit\""));
}

#[test]
fn references_cycles_duplicate_sources_and_unpinned_worlds_are_rejected() {
    let limits = PackageLimits::default();
    let mut missing = lock();
    missing.packages[0]
        .dependencies
        .push("other:package@1.0.0".to_owned());
    assert!(encode_wit_lock(&missing, limits).is_err());
    let mut cycle = lock();
    let own_id = cycle.packages[0].id.clone();
    cycle.packages[0].dependencies.push(own_id);
    assert!(encode_wit_lock(&cycle, limits).is_err());
    let mut duplicate = lock();
    let mut extra = duplicate.packages[0].clone();
    extra.id = "other:package@1.0.0".to_owned();
    duplicate.packages.push(extra);
    assert!(encode_wit_lock(&duplicate, limits).is_err());
    for world in [
        "example:fixture/fixture",
        "other:fixture/fixture@1.0.0",
        "example:fixture/fixture@01.0.0",
    ] {
        let mut value = lock();
        value.world = world.to_owned();
        assert!(encode_wit_lock(&value, limits).is_err());
    }
}

#[test]
fn a_resolved_acyclic_dependency_graph_is_accepted() {
    let limits = PackageLimits::default();
    let mut value = lock();
    let dependency = WitLockedPackage {
        id: "dependency:types@2.0.0".to_owned(),
        source_path: "wit/dependency.wit".to_owned(),
        digest: artifact_blob_digest(b"package dependency:types@2.0.0;"),
        dependencies: Vec::new(),
    };
    value.packages[0].dependencies.push(dependency.id.clone());
    value.packages.insert(0, dependency);
    assert_eq!(
        decode_wit_lock(&encode_wit_lock(&value, limits).unwrap(), limits).unwrap(),
        value
    );
    value.packages.reverse();
    assert!(encode_wit_lock(&value, limits).is_err());
}

#[test]
fn document_nodes_and_lexical_integer_limits_apply_to_locks() {
    let value = lock();
    let bytes = encode_wit_lock(&value, PackageLimits::default()).unwrap();
    let limits = PackageLimits {
        max_document_bytes: 64,
        ..PackageLimits::default()
    };
    assert!(decode_wit_lock(&bytes, limits).is_err());
    assert!(encode_wit_lock(&value, limits).is_err());
    let limits = PackageLimits {
        max_nodes: 3,
        ..PackageLimits::default()
    };
    assert!(decode_wit_lock(&bytes, limits).is_err());
    let text = String::from_utf8(bytes).unwrap();
    for changed in [
        text.replace("\"formatVersion\":1", "\"formatVersion\":1.0"),
        text.replace(
            "\"formatVersion\":1",
            "\"formatVersion\":1,\"formatVersion\":1",
        ),
        text.replace("\"dependencies\":[]", "\"dependencies\":null"),
    ] {
        assert!(decode_wit_lock(changed.as_bytes(), PackageLimits::default()).is_err());
    }
}

fn capsule(value: &WitLock) -> PackageConfig {
    use crate::package::{
        CAPSULE_MANIFEST_MEDIA_TYPE, COMPONENT_MEDIA_TYPE, CONTRACTS_MEDIA_TYPE,
        WIT_LOCK_MEDIA_TYPE,
    };
    let mut layers = vec![
        (
            "capsule.json",
            LayerRole::CapsuleManifest,
            CAPSULE_MANIFEST_MEDIA_TYPE,
            b"manifest".as_slice(),
        ),
        (
            "component.wasm",
            LayerRole::Component,
            COMPONENT_MEDIA_TYPE,
            b"component".as_slice(),
        ),
        (
            "contracts.json",
            LayerRole::Contracts,
            CONTRACTS_MEDIA_TYPE,
            b"contracts".as_slice(),
        ),
        (
            "wit-lock.json",
            LayerRole::WitLock,
            WIT_LOCK_MEDIA_TYPE,
            b"lock".as_slice(),
        ),
        (
            "wit/example.wit",
            LayerRole::Asset,
            "text/plain",
            b"package example:fixture@1.0.0; world fixture {}".as_slice(),
        ),
    ]
    .into_iter()
    .map(|(path, role, media_type, bytes)| PackageLayer {
        path: path.to_owned(),
        role,
        media_type: media_type.to_owned(),
        digest: artifact_blob_digest(bytes),
        size: bytes.len() as u64,
    })
    .collect::<Vec<_>>();
    layers.sort_by(|left, right| left.path.cmp(&right.path));
    let config = PackageConfig {
        format_version: 1,
        kind: PackageKind::Capsule,
        name: "fixture".to_owned(),
        version: "1.0.0".to_owned(),
        entrypoint: "component.wasm".to_owned(),
        component_digest: Some(artifact_blob_digest(b"component")),
        layers,
        annotations: BTreeMap::new(),
    };
    assert_eq!(value.contracts_digest, artifact_blob_digest(b"contracts"));
    config
}

#[test]
fn lock_binds_contracts_and_source_paths_to_the_package_layers() {
    let limits = PackageLimits::default();
    let value = lock();
    let config = capsule(&value);
    validate_wit_lock(&config, &value, limits).unwrap();
    let mut wrong_contracts = value.clone();
    wrong_contracts.contracts_digest = artifact_blob_digest(b"different-contracts");
    assert!(validate_wit_lock(&config, &wrong_contracts, limits).is_err());
    let mut wrong_source = value.clone();
    wrong_source.packages[0].digest = artifact_blob_digest(b"different-source");
    assert!(validate_wit_lock(&config, &wrong_source, limits).is_err());
    let mut missing_source = value;
    missing_source.packages[0].source_path = "wit/missing.wit".to_owned();
    assert!(validate_wit_lock(&config, &missing_source, limits).is_err());
}

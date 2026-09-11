use std::{fs, path::Path};

use latent_artifacts::package::{
    decode_referrer, decode_wit_lock, encode_config, encode_manifest, encode_referrer,
    encode_wit_lock, inspect_package, validate_wit_lock, verify_layer_bytes, PackageLimits,
};
use serde_json::Value;
use sha2::{Digest, Sha256};

fn corpus() -> &'static Path {
    Path::new(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../examples/package-format"
    ))
}

fn read_checked(record: &Value) -> Vec<u8> {
    let path = record["file"].as_str().unwrap();
    let bytes = fs::read(corpus().join(path)).unwrap();
    assert_eq!(
        bytes.len() as u64,
        record["size"].as_u64().unwrap(),
        "{path}"
    );
    assert_eq!(
        format!("sha256:{:x}", Sha256::digest(&bytes)),
        record["digest"].as_str().unwrap(),
        "{path}"
    );
    bytes
}

#[test]
fn independently_recorded_corpus_digests_sizes_and_canonical_bytes_match() {
    let index: Value =
        serde_json::from_slice(&fs::read(corpus().join("golden.json")).unwrap()).unwrap();
    let limits = PackageLimits::default();
    for package in index["packages"].as_array().unwrap() {
        let config = read_checked(&package["config"]);
        let manifest = read_checked(&package["manifest"]);
        let layout = inspect_package(&manifest, &config, limits).unwrap();
        assert_eq!(
            layout.digest().as_str(),
            package["manifest"]["digest"].as_str().unwrap()
        );
        assert_eq!(encode_config(layout.config(), limits).unwrap(), config);
        assert_eq!(
            encode_manifest(layout.manifest(), limits).unwrap(),
            manifest
        );
        assert_eq!(
            layout.config().layers.len(),
            package["blobs"].as_array().unwrap().len()
        );
        for (layer, record) in layout
            .config()
            .layers
            .iter()
            .zip(package["blobs"].as_array().unwrap())
        {
            let bytes = read_checked(record);
            assert_eq!(layer.path, record["path"]);
            assert_eq!(layer.role.as_str(), record["role"]);
            assert_eq!(layer.media_type, record["mediaType"]);
            verify_layer_bytes(layer, &bytes, limits).unwrap();
            if layer.role.as_str() == "wit-lock" {
                let lock = decode_wit_lock(&bytes, limits).unwrap();
                validate_wit_lock(layout.config(), &lock, limits).unwrap();
                assert_eq!(encode_wit_lock(&lock, limits).unwrap(), bytes);
            }
        }
    }
    assert_eq!(read_checked(&index["emptyConfig"]), b"{}");
    for evidence in index["evidence"].as_array().unwrap() {
        let bytes = read_checked(&evidence["manifest"]);
        let referrer = decode_referrer(&bytes, limits).unwrap();
        assert_eq!(encode_referrer(&referrer, limits).unwrap(), bytes);
        let subject = index["packages"]
            .as_array()
            .unwrap()
            .iter()
            .find(|package| package["kind"] == evidence["subjectKind"])
            .unwrap();
        assert_eq!(
            referrer.subject.digest.as_str(),
            subject["manifest"]["digest"].as_str().unwrap()
        );
        assert_eq!(
            referrer.subject.size,
            subject["manifest"]["size"].as_u64().unwrap()
        );
        let payload = read_checked(&evidence["payload"]);
        assert_eq!(
            referrer.layers[0].digest.as_str(),
            format!("sha256:{:x}", Sha256::digest(&payload))
        );
        assert_eq!(referrer.layers[0].size, payload.len() as u64);
    }
}

#[test]
fn changed_metadata_produces_a_new_package_without_changing_component_release() {
    use latent_artifacts::package::artifact_blob_digest;
    let limits = PackageLimits::default();
    let config_bytes = fs::read(corpus().join("capsule/config.json")).unwrap();
    let manifest_bytes = fs::read(corpus().join("capsule/manifest.json")).unwrap();
    let old = inspect_package(&manifest_bytes, &config_bytes, limits).unwrap();
    let mut config = old.config().clone();
    config
        .annotations
        .insert("build".to_owned(), "new-metadata".to_owned());
    let config_bytes = encode_config(&config, limits).unwrap();
    let mut manifest = old.manifest().clone();
    manifest.config.digest = artifact_blob_digest(&config_bytes);
    manifest.config.size = config_bytes.len() as u64;
    let new = inspect_package(
        &encode_manifest(&manifest, limits).unwrap(),
        &config_bytes,
        limits,
    )
    .unwrap();
    assert_ne!(old.digest(), new.digest());
    assert_eq!(old.component_release(), new.component_release());
}

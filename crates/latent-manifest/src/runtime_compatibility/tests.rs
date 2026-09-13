use super::*;
use crate::{JsonManifestCodec, ManifestCodec};

fn capsule() -> CapsuleManifest {
    JsonManifestCodec::default()
        .decode_capsule(include_bytes!(
            "../../../../examples/echo-contract/capsule.json"
        ))
        .unwrap()
}

fn host() -> RuntimeCompatibilityProfile {
    RuntimeCompatibilityProfile::new(
        "wasmtime",
        "47.0.3",
        "x86_64-unknown-linux-gnu",
        &["x86_64.sse2"],
        u64::MAX,
        u64::MAX,
    )
    .unwrap()
}

#[test]
fn omitted_requirements_preserve_canonical_json_and_empty_arrays_normalize() {
    let codec = JsonManifestCodec::default();
    let original = capsule();
    let encoded = codec.encode_capsule(&original).unwrap();
    let mut json: serde_json::Value = serde_json::from_slice(&encoded).unwrap();
    assert_eq!(json["compatibility"].as_object().unwrap().len(), 1);
    json["compatibility"]["targetTriples"] = serde_json::json!([]);
    json["compatibility"]["cpuFeatures"] = serde_json::json!([]);
    assert_eq!(
        codec
            .encode_capsule(
                &codec
                    .decode_capsule(&serde_json::to_vec(&json).unwrap())
                    .unwrap()
            )
            .unwrap(),
        encoded
    );
}

#[test]
fn explicit_requirements_need_profile_and_check_each_independent_dimension() {
    let mut manifest = capsule();
    manifest.runtime_requirements.runtime = Some(RuntimeRequirement {
        engine: "wasmtime".into(),
        minimum_version: "47.0.3".into(),
    });
    assert!(check_runtime_compatibility(&manifest, None).is_err());
    let profile = host();
    check_runtime_compatibility(&manifest, Some(&profile)).unwrap();
    manifest
        .runtime_requirements
        .runtime
        .as_mut()
        .unwrap()
        .minimum_version = "47.0.4".into();
    assert!(profile.check_capsule(&manifest).is_err());
    manifest
        .runtime_requirements
        .runtime
        .as_mut()
        .unwrap()
        .minimum_version = "47.0.3-rc.1".into();
    manifest.runtime_requirements.target_triples = vec!["aarch64-unknown-linux-gnu".into()];
    assert!(profile.check_capsule(&manifest).is_err());
    manifest.runtime_requirements.target_triples[0] = "x86_64-unknown-linux-gnu".into();
    manifest.runtime_requirements.cpu_features = vec!["x86_64.avx2".into()];
    assert!(profile.check_capsule(&manifest).is_err());
    manifest.runtime_requirements.cpu_features[0] = "x86_64.sse2".into();
    profile.check_capsule(&manifest).unwrap();
    manifest.minimum_fabric_version = "0.2.0".into();
    assert!(profile.check_capsule(&manifest).is_err());
}

#[test]
fn requirement_shapes_and_typed_spare_capacities_fail_closed() {
    let codec = JsonManifestCodec::default();
    let original: serde_json::Value =
        serde_json::from_slice(&codec.encode_capsule(&capsule()).unwrap()).unwrap();
    for field in ["runtime", "targetTriples", "cpuFeatures"] {
        let mut value = original.clone();
        value["compatibility"][field] = serde_json::Value::Null;
        assert!(codec
            .decode_capsule(&serde_json::to_vec(&value).unwrap())
            .is_err());
    }
    for runtime in [
        serde_json::json!({"engine":"other","minimumVersion":"47.0.3"}),
        serde_json::json!({"engine":"wasmtime","minimumVersion":"47.0.3","unknown":true}),
        serde_json::json!({"engine":"wasmtime","minimumVersion":"47.00.3"}),
    ] {
        let mut value = original.clone();
        value["compatibility"]["runtime"] = runtime;
        assert!(codec
            .decode_capsule(&serde_json::to_vec(&value).unwrap())
            .is_err());
    }
    let mut manifest = capsule();
    manifest.runtime_requirements.target_triples = Vec::with_capacity(1024);
    assert!(codec.encode_capsule(&manifest).is_err());
    manifest.runtime_requirements.target_triples = vec!["x86_64-unknown-linux-gnu".into(); 2];
    assert!(codec.encode_capsule(&manifest).is_err());
    manifest.runtime_requirements.target_triples.clear();
    manifest.runtime_requirements.cpu_features = vec![String::with_capacity(1024)];
    assert!(codec.encode_capsule(&manifest).is_err());
}

#[test]
fn profile_digest_binds_detected_facts_and_budgets_order_independently() {
    let make = |cpu: &[&str], fuel| {
        RuntimeCompatibilityProfile::new(
            "wasmtime",
            "47.0.3",
            "x86_64-unknown-linux-gnu",
            cpu,
            1024,
            fuel,
        )
        .unwrap()
    };
    let first = make(&["x86_64.sse2", "x86_64.avx2"], 10);
    assert_eq!(
        first.digest(),
        make(&["x86_64.avx2", "x86_64.sse2"], 10).digest()
    );
    assert_ne!(first.digest(), make(&["x86_64.sse2"], 10).digest());
    assert_ne!(
        first.digest(),
        make(&["x86_64.sse2", "x86_64.avx2"], 11).digest()
    );
    assert!(RuntimeCompatibilityProfile::new(
        "wasmtime",
        "47.0.3",
        "aarch64-unknown-linux-gnu",
        &["x86_64.sse2"],
        1024,
        10
    )
    .is_err());
}

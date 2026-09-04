use std::panic::{catch_unwind, AssertUnwindSafe};

use latent_manifest::{JsonManifestCodec, ManifestCodec, ManifestLimits};
use serde_json::{json, Value};

const ECHO_DEPLOYMENT: &[u8] = include_bytes!("../../../examples/echo-contract/deployment.json");
const ECHO_TRIGGER: &[u8] = include_bytes!("../../../examples/echo-contract/http-trigger.json");

#[test]
fn deterministic_malformed_json_corpus_never_panics() {
    let codec = JsonManifestCodec::default();
    let mut state = 0x7f4a_7c15_d6e8_feb8_u64;

    for case in 0..768_usize {
        let length = usize::try_from(next(&mut state) % 2048).expect("bounded length");
        let mut bytes = Vec::with_capacity(length);
        for _ in 0..length {
            bytes.push(u8::try_from(next(&mut state) & 0xff).expect("bounded byte"));
        }
        if case % 7 == 0 {
            bytes.extend_from_slice(br#"{"kind":"Capsule","nested":["#);
        }

        let result = catch_unwind(AssertUnwindSafe(|| {
            let _ = codec.decode_document(&bytes);
            let _ = codec.decode_capsule(&bytes);
            let _ = codec.decode_deployment(&bytes);
            let _ = codec.decode_binding(&bytes);
            let _ = codec.decode_trigger(&bytes);
            let _ = codec.decode_policy(&bytes);
        }));
        assert!(result.is_ok(), "decoder panicked for corpus case {case}");
    }
}

#[test]
fn route_weight_boundaries_are_schema_checked_without_narrowing_panics() {
    let codec = JsonManifestCodec::default();
    let mut deployment: Value = serde_json::from_slice(ECHO_DEPLOYMENT).expect("deployment");

    deployment["spec"]["route"]["weight"] = json!(10_000);
    codec
        .decode_deployment(&serde_json::to_vec(&deployment).expect("JSON"))
        .expect("upper bound is structurally valid");

    deployment["spec"]["route"]["weight"] = json!(10_001);
    let violations = codec
        .decode_deployment(&serde_json::to_vec(&deployment).expect("JSON"))
        .expect_err("weight above maximum");
    assert!(violations.iter().any(|violation| {
        violation.path == "$.spec.route.weight" && violation.code == "out-of-range"
    }));

    deployment["spec"]["route"]["weight"] = json!(u64::from(u16::MAX) + 1);
    let result = catch_unwind(AssertUnwindSafe(|| {
        codec.decode_deployment(&serde_json::to_vec(&deployment).expect("JSON"))
    }));
    assert!(result.is_ok());
    assert!(result.expect("no panic").is_err());
}

#[test]
fn exact_nesting_boundary_is_deterministic() {
    let mut trigger: Value = serde_json::from_slice(ECHO_TRIGGER).expect("trigger");
    // The root and `spec` objects consume two levels. Ten configuration
    // objects therefore reach a maximum depth of exactly twelve.
    trigger["spec"]["configuration"] = nested_value(10);
    let bytes = serde_json::to_vec(&trigger).expect("JSON");

    let permissive = JsonManifestCodec::new(ManifestLimits {
        max_nesting_depth: 12,
        ..ManifestLimits::default()
    });
    permissive
        .decode_trigger(&bytes)
        .expect("configured depth is sufficient");

    let restrictive = JsonManifestCodec::new(ManifestLimits {
        max_nesting_depth: 11,
        ..ManifestLimits::default()
    });
    let first = restrictive
        .decode_trigger(&bytes)
        .expect_err("configured depth is too small");
    let second = restrictive
        .decode_trigger(&bytes)
        .expect_err("configured depth is too small");
    assert_eq!(first, second);
    assert_eq!(first[0].code, "nesting-limit-exceeded");
}

#[test]
fn schema_violation_collection_is_bounded() {
    let codec = JsonManifestCodec::new(ManifestLimits {
        max_violations: 3,
        ..ManifestLimits::default()
    });
    let document = json!({
        "apiVersion": "bad",
        "kind": "Deployment",
        "metadata": {},
        "spec": {
            "service": "",
            "release": "bad",
            "route": {"weight": 10001, "unknown": true},
            "resources": {},
            "availability": {},
            "placement": {},
            "unknown": true
        },
        "unknown": true
    });
    let violations = codec
        .decode_deployment(&serde_json::to_vec(&document).expect("JSON"))
        .expect_err("invalid document");
    assert!(!violations.is_empty());
    assert!(violations.len() <= 3);
}

fn nested_value(depth: usize) -> Value {
    let mut value = json!(true);
    for index in 0..depth {
        value = json!({format!("level-{index}"): value});
    }
    value
}

fn next(state: &mut u64) -> u64 {
    *state = state
        .wrapping_mul(6_364_136_223_846_793_005)
        .wrapping_add(1_442_695_040_888_963_407);
    *state
}

use std::collections::BTreeMap;

use latent_core::{ContractId, ServiceId, TenantId, TriggerId};
use latent_manifest::{
    JsonManifestCodec, ManifestCodec, ObjectMetadata, TriggerKind, TriggerManifest, TriggerTarget,
    MANIFEST_API_VERSION,
};
use serde_json::Value;

const I128_MAX: &str = "170141183460469231731687303715884105727";
const I128_MAX_MINUS_ONE: &str = "170141183460469231731687303715884105726";
const I128_MAX_PLUS_ONE: &str = "170141183460469231731687303715884105728";
const I128_MAX_PLUS_TWO: &str = "170141183460469231731687303715884105729";

#[test]
fn directly_constructed_models_use_value_canonical_numbers() {
    for (left, right) in [
        ("1.5", "1.50"),
        ("1.5", "15e-1"),
        ("1.5", "0.150e1"),
        ("1.5", "1500e-3"),
        ("0", "-0.0"),
        ("1e400", "10e399"),
        ("1e-400", "10e-401"),
    ] {
        assert_direct_model_equivalence(number(left), number(right));
    }
}

#[test]
fn directly_constructed_nested_values_use_value_canonical_numbers() {
    let left: Value = serde_json::from_str(
        r#"{
            "array": [1.50, -0.0, 10e399, 10e-401],
            "object": {
                "ratio": 1500e-3,
                "nested": [0.150e1, {"value": 15e-1}]
            }
        }"#,
    )
    .expect("valid arbitrary-precision JSON");
    let right: Value = serde_json::from_str(
        r#"{
            "object": {
                "nested": [1.5, {"value": 1.5}],
                "ratio": 1.5
            },
            "array": [15e-1, 0, 1e400, 1e-400]
        }"#,
    )
    .expect("valid arbitrary-precision JSON");

    assert_direct_model_equivalence(left, right);
}

#[test]
fn exponents_at_and_beyond_i128_boundaries_remain_exact() {
    assert_direct_model_equivalence(
        number(&format!("1e{I128_MAX}")),
        number(&format!("10e{I128_MAX_MINUS_ONE}")),
    );
    assert_direct_model_equivalence(
        number(&format!("10e{I128_MAX}")),
        number(&format!("1e{I128_MAX_PLUS_ONE}")),
    );
    assert_direct_model_distinct(
        number(&format!("1e{I128_MAX}")),
        number(&format!("10e{I128_MAX}")),
    );

    assert_direct_model_equivalence(
        number(&format!("1e-{I128_MAX_PLUS_ONE}")),
        number(&format!("10e-{I128_MAX_PLUS_TWO}")),
    );
    assert_direct_model_distinct(
        number(&format!("1e-{I128_MAX_PLUS_ONE}")),
        number(&format!("10e-{I128_MAX_PLUS_ONE}")),
    );
}

#[test]
fn very_long_exponents_remain_compact_and_distinct() {
    let exponent = "9".repeat(4096);
    let left = number(&format!("1e{exponent}"));
    let right = number(&format!("10e{exponent}"));

    let left_encoded = encode_direct_value(left);
    let right_encoded = encode_direct_value(right);
    assert_ne!(left_encoded, right_encoded);

    let left_text = std::str::from_utf8(&left_encoded).expect("UTF-8 JSON");
    assert!(left_text.contains(&format!("1e+{exponent}")));
    assert!(left_encoded.len() < 8192);
}

fn assert_direct_model_equivalence(left: Value, right: Value) {
    let codec = JsonManifestCodec::default();
    let left_encoded = encode_direct_value_with(&codec, left);
    let right_encoded = encode_direct_value_with(&codec, right);
    assert_eq!(
        left_encoded, right_encoded,
        "mathematically equivalent directly constructed models must have identical canonical bytes"
    );

    let left_decoded = codec
        .decode_trigger(&left_encoded)
        .expect("canonical left trigger");
    let right_decoded = codec
        .decode_trigger(&right_encoded)
        .expect("canonical right trigger");
    assert_eq!(left_decoded, right_decoded);
    assert_eq!(
        codec
            .encode_trigger(&left_decoded)
            .expect("repeat canonical encoding"),
        left_encoded
    );
}

fn assert_direct_model_distinct(left: Value, right: Value) {
    let codec = JsonManifestCodec::default();
    let left_encoded = encode_direct_value_with(&codec, left);
    let right_encoded = encode_direct_value_with(&codec, right);
    assert_ne!(
        left_encoded, right_encoded,
        "mathematically distinct directly constructed models must not collapse"
    );
}

fn encode_direct_value(value: Value) -> Vec<u8> {
    encode_direct_value_with(&JsonManifestCodec::default(), value)
}

fn encode_direct_value_with(codec: &JsonManifestCodec, value: Value) -> Vec<u8> {
    let mut manifest = base_trigger();
    manifest.configuration.insert("value".to_owned(), value);
    codec
        .encode_trigger(&manifest)
        .expect("directly constructed trigger must encode")
}

fn number(text: &str) -> Value {
    let value: Value = serde_json::from_str(text).expect("valid arbitrary-precision JSON number");
    assert!(value.is_number());
    value
}

fn base_trigger() -> TriggerManifest {
    let name = "canonical-number-test".to_owned();
    TriggerManifest {
        api_version: MANIFEST_API_VERSION.to_owned(),
        id: TriggerId(name.clone()),
        metadata: ObjectMetadata {
            name,
            tenant: Some(TenantId("examples".to_owned())),
            namespace: None,
            labels: BTreeMap::new(),
            annotations: BTreeMap::new(),
        },
        kind: TriggerKind::Http,
        target: TriggerTarget {
            service: ServiceId("examples/echo".to_owned()),
            contract: ContractId("examples:echo/api@0.1.0".to_owned()),
            function: "echo".to_owned(),
            route: Some("production".to_owned()),
        },
        configuration: BTreeMap::new(),
    }
}

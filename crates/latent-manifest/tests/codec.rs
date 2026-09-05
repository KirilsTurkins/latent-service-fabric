use latent_manifest::{
    JsonManifestCodec, ManifestCodec, ManifestDocument, ManifestLimits, ManifestResult,
};
use serde_json::{json, Value};

const ECHO_CAPSULE: &[u8] = include_bytes!("../../../examples/echo-contract/capsule.json");
const COUNTER_CAPSULE: &[u8] = include_bytes!("../../../examples/counter-contract/capsule.json");
const ECHO_DEPLOYMENT: &[u8] = include_bytes!("../../../examples/echo-contract/deployment.json");
const ECHO_BINDING: &[u8] = include_bytes!("../../../examples/bindings/gateway-to-echo.json");
const ECHO_TRIGGER: &[u8] = include_bytes!("../../../examples/echo-contract/http-trigger.json");
const LOG_POLICY: &[u8] = include_bytes!("../../../examples/policies/default-log-policy.json");

#[test]
fn every_supported_example_round_trips_without_semantic_loss() {
    let codec = JsonManifestCodec::default();

    let echo = codec.decode_capsule(ECHO_CAPSULE).expect("echo capsule");
    let encoded = codec.encode_capsule(&echo).expect("encode echo capsule");
    assert_eq!(echo, codec.decode_capsule(&encoded).expect("decode echo"));

    let counter = codec
        .decode_capsule(COUNTER_CAPSULE)
        .expect("counter capsule is structurally valid");
    let encoded = codec
        .encode_capsule(&counter)
        .expect("encode counter capsule");
    assert_eq!(
        counter,
        codec.decode_capsule(&encoded).expect("decode counter")
    );

    let deployment = codec
        .decode_deployment(ECHO_DEPLOYMENT)
        .expect("echo deployment");
    let encoded = codec
        .encode_deployment(&deployment)
        .expect("encode deployment");
    assert_eq!(
        deployment,
        codec
            .decode_deployment(&encoded)
            .expect("decode deployment")
    );

    let binding = codec.decode_binding(ECHO_BINDING).expect("binding");
    let encoded = codec.encode_binding(&binding).expect("encode binding");
    assert_eq!(
        binding,
        codec.decode_binding(&encoded).expect("decode binding")
    );

    let trigger = codec.decode_trigger(ECHO_TRIGGER).expect("trigger");
    let encoded = codec.encode_trigger(&trigger).expect("encode trigger");
    assert_eq!(
        trigger,
        codec.decode_trigger(&encoded).expect("decode trigger")
    );

    let policy = codec.decode_policy(LOG_POLICY).expect("policy");
    let encoded = codec.encode_policy(&policy).expect("encode policy");
    assert_eq!(
        policy,
        codec.decode_policy(&encoded).expect("decode policy")
    );
}

#[test]
fn generic_document_codec_identifies_all_manifest_kinds() {
    let codec = JsonManifestCodec::default();
    assert!(matches!(
        codec.decode_document(ECHO_CAPSULE).expect("capsule"),
        ManifestDocument::Capsule(_)
    ));
    assert!(matches!(
        codec.decode_document(ECHO_DEPLOYMENT).expect("deployment"),
        ManifestDocument::Deployment(_)
    ));
    assert!(matches!(
        codec.decode_document(ECHO_BINDING).expect("binding"),
        ManifestDocument::Binding(_)
    ));
    assert!(matches!(
        codec.decode_document(ECHO_TRIGGER).expect("trigger"),
        ManifestDocument::Trigger(_)
    ));
    assert!(matches!(
        codec.decode_document(LOG_POLICY).expect("policy"),
        ManifestDocument::Policy(_)
    ));
}

#[test]
fn canonical_encoding_normalizes_digest_and_semantic_set_order() {
    let codec = JsonManifestCodec::default();
    let mut left: Value = serde_json::from_slice(ECHO_CAPSULE).expect("example JSON");
    let digest = left["component"]["digest"].as_str().expect("digest");
    left["component"]["digest"] =
        Value::String(format!("sha256:{}", digest[7..].to_ascii_uppercase()));
    left["imports"].as_array_mut().expect("imports").reverse();

    let mut right: Value = serde_json::from_slice(ECHO_CAPSULE).expect("example JSON");
    right["imports"]
        .as_array_mut()
        .expect("imports")
        .sort_by_key(|value| value["contract"].as_str().unwrap_or_default().to_owned());

    let left = codec
        .decode_capsule(&serde_json::to_vec(&left).expect("left JSON"))
        .expect("left capsule");
    let right = codec
        .decode_capsule(&serde_json::to_vec(&right).expect("right JSON"))
        .expect("right capsule");
    let left = codec.encode_capsule(&left).expect("left canonical JSON");
    let right = codec.encode_capsule(&right).expect("right canonical JSON");

    assert_eq!(left, right);
    assert!(!left.contains(&b'\n'));
    let value: Value = serde_json::from_slice(&left).expect("canonical JSON");
    assert!(value["component"]["digest"]
        .as_str()
        .expect("digest")
        .bytes()
        .all(|byte| !byte.is_ascii_uppercase()));
}

#[test]
fn schema_failures_have_stable_paths_and_codes() {
    let codec = JsonManifestCodec::default();

    let mut document: Value = serde_json::from_slice(ECHO_CAPSULE).expect("example JSON");
    document["apiVersion"] = json!("latent.dev/v2");
    assert_violation(
        codec.decode_capsule(&serde_json::to_vec(&document).expect("JSON")),
        "$.apiVersion",
        "unsupported-api-version",
    );

    let mut document: Value = serde_json::from_slice(ECHO_CAPSULE).expect("example JSON");
    document["component"]["digest"] = json!("sha256:nope");
    assert_violation(
        codec.decode_capsule(&serde_json::to_vec(&document).expect("JSON")),
        "$.component.digest",
        "invalid-digest",
    );

    let mut document: Value = serde_json::from_slice(ECHO_CAPSULE).expect("example JSON");
    document["execution"]["limits"]["memoryBytes"] = json!("4194304");
    assert_violation(
        codec.decode_capsule(&serde_json::to_vec(&document).expect("JSON")),
        "$.execution.limits.memoryBytes",
        "invalid-type",
    );

    let mut document: Value = serde_json::from_slice(ECHO_CAPSULE).expect("example JSON");
    document["futureField"] = json!(true);
    assert_violation(
        codec.decode_capsule(&serde_json::to_vec(&document).expect("JSON")),
        "$.futureField",
        "unknown-field",
    );

    let mut document: Value = serde_json::from_slice(ECHO_DEPLOYMENT).expect("example JSON");
    document["spec"]["resources"]["wallDeadlineUnixMillis"] = json!(1_800_000_000_000_u64);
    assert_violation(
        codec.decode_deployment(&serde_json::to_vec(&document).expect("JSON")),
        "$.spec.resources.wallDeadlineUnixMillis",
        "unknown-field",
    );
}

#[test]
fn model_integer_width_failures_keep_their_wire_paths() {
    let codec = JsonManifestCodec::default();

    let mut capsule: Value = serde_json::from_slice(ECHO_CAPSULE).expect("capsule");
    capsule["execution"]["hostCallDepthMaximum"] = json!(u64::from(u32::MAX) + 1);
    assert_violation(
        codec.decode_capsule(&serde_json::to_vec(&capsule).expect("JSON")),
        "$.execution.hostCallDepthMaximum",
        "out-of-range",
    );

    let mut deployment: Value = serde_json::from_slice(ECHO_DEPLOYMENT).expect("deployment");
    deployment["spec"]["availability"]["minimumCachedCopies"] = json!(u64::from(u32::MAX) + 1);
    assert_violation(
        codec.decode_deployment(&serde_json::to_vec(&deployment).expect("JSON")),
        "$.spec.availability.minimumCachedCopies",
        "out-of-range",
    );
}

#[test]
fn direct_serde_support_preserves_the_schema_wire_shape() {
    let codec = JsonManifestCodec::default();
    let deployment = codec
        .decode_deployment(ECHO_DEPLOYMENT)
        .expect("deployment");
    let direct = serde_json::to_value(&deployment).expect("serialize deployment");
    let canonical = codec
        .encode_deployment(&deployment)
        .expect("canonical deployment");
    let canonical: Value = serde_json::from_slice(&canonical).expect("canonical JSON");
    assert_eq!(direct, canonical);
}

#[test]
fn duplicate_keys_are_rejected_before_schema_evaluation() {
    let codec = JsonManifestCodec::default();
    let document = br#"{
        "apiVersion":"latent.dev/v1alpha1",
        "apiVersion":"latent.dev/v1alpha1",
        "kind":"Capsule"
    }"#;
    assert_violation(codec.decode_capsule(document), "$", "duplicate-key");
}

#[test]
fn limits_bound_payload_nesting_and_strings() {
    let limits = ManifestLimits {
        max_document_bytes: ECHO_CAPSULE.len().saturating_sub(1),
        ..ManifestLimits::default()
    };
    assert_violation(
        JsonManifestCodec::new(limits).decode_capsule(ECHO_CAPSULE),
        "$",
        "payload-too-large",
    );

    let mut trigger: Value = serde_json::from_slice(ECHO_TRIGGER).expect("trigger");
    trigger["spec"]["configuration"]["nested"] = json!({"a":{"b":{"c":true}}});
    let limits = ManifestLimits {
        max_nesting_depth: 5,
        ..ManifestLimits::default()
    };
    assert_violation(
        JsonManifestCodec::new(limits).decode_trigger(&serde_json::to_vec(&trigger).expect("JSON")),
        "$",
        "nesting-limit-exceeded",
    );

    let mut trigger: Value = serde_json::from_slice(ECHO_TRIGGER).expect("trigger");
    trigger["spec"]["configuration"]["large"] = json!("x".repeat(65));
    let limits = ManifestLimits {
        max_string_bytes: 64,
        ..ManifestLimits::default()
    };
    assert_violation(
        JsonManifestCodec::new(limits).decode_trigger(&serde_json::to_vec(&trigger).expect("JSON")),
        "$",
        "string-too-large",
    );
}

#[test]
fn forward_compatibility_is_strict_except_schema_extension_points() {
    let codec = JsonManifestCodec::default();
    let mut trigger: Value = serde_json::from_slice(ECHO_TRIGGER).expect("trigger");
    trigger["spec"]["configuration"]["future"] = json!({
        "arbitrary": [1, true, null, {"nested": "retained"}]
    });
    let decoded = codec
        .decode_trigger(&serde_json::to_vec(&trigger).expect("JSON"))
        .expect("configuration extension point");
    let encoded = codec.encode_trigger(&decoded).expect("canonical trigger");
    let decoded_again = codec.decode_trigger(&encoded).expect("round trip");
    assert_eq!(decoded, decoded_again);
    assert_eq!(
        decoded.configuration["future"]["arbitrary"][3]["nested"],
        json!("retained")
    );

    trigger["spec"]["futureRuntimeField"] = json!(true);
    assert_violation(
        codec.decode_trigger(&serde_json::to_vec(&trigger).expect("JSON")),
        "$.spec.futureRuntimeField",
        "unknown-field",
    );
}

#[test]
fn optional_schema_fields_are_preserved_by_the_domain_model() {
    let codec = JsonManifestCodec::default();
    let mut deployment: Value = serde_json::from_slice(ECHO_DEPLOYMENT).expect("deployment");
    deployment["spec"]["grants"][0]["operations"] = json!(["write", "read"]);
    deployment["spec"]["grants"][0]["constraints"] = json!({"scope": "tenant"});
    let decoded = codec
        .decode_deployment(&serde_json::to_vec(&deployment).expect("JSON"))
        .expect("deployment");
    assert_eq!(
        decoded.grants[0].operations,
        vec!["read".to_owned(), "write".to_owned()]
    );
    assert_eq!(decoded.grants[0].constraints["scope"], "tenant");

    let policy = codec.decode_policy(LOG_POLICY).expect("policy");
    assert_eq!(policy.language, "latent-policy/v1");
    let trigger = codec.decode_trigger(ECHO_TRIGGER).expect("trigger");
    assert_eq!(trigger.target.route.as_deref(), Some("production"));
}

fn assert_violation<T: std::fmt::Debug>(
    result: ManifestResult<T>,
    expected_path: &str,
    expected_code: &str,
) {
    let violations = result.expect_err("document unexpectedly succeeded");
    assert!(
        violations
            .iter()
            .any(|violation| violation.path == expected_path && violation.code == expected_code),
        "missing {expected_path} [{expected_code}] in {violations:#?}"
    );
}

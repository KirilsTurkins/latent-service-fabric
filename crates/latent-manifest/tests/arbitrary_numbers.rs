use latent_manifest::{JsonManifestCodec, ManifestCodec, ManifestViolation};
use serde_json::Value;

const CAPSULE: &str = include_str!("../../../examples/echo-contract/capsule.json");
const DEPLOYMENT: &str = include_str!("../../../examples/echo-contract/deployment.json");
const NEAR_INTEGRAL_FRACTION: &str = "1.0000000000000000000000000000000001";

#[test]
fn trigger_configuration_retains_arbitrary_precision_numbers_exactly() {
    let source = trigger_document(
        r#"{
            "wideInteger": 18446744073709551617,
            "wideNegative": -9223372036854775809,
            "ratio": 0.123456789012345678901234567890,
            "largeNumber": 1e400,
            "smallNumber": 1e-400,
            "nested": {
                "array": [
                    18446744073709551617,
                    -9223372036854775809,
                    0.123456789012345678901234567890,
                    1e400,
                    1e-400
                ],
                "object": {
                    "value": 12345678901234567890.12345678901234567890
                }
            }
        }"#,
    );
    let codec = JsonManifestCodec::default();

    let first = codec
        .decode_trigger(source.as_bytes())
        .expect("schema-valid arbitrary-precision trigger numbers");
    assert_number(&first.configuration["wideInteger"], "18446744073709551617");
    assert_number(&first.configuration["wideNegative"], "-9223372036854775809");
    assert_number(
        &first.configuration["ratio"],
        "0.123456789012345678901234567890",
    );
    assert_number(&first.configuration["largeNumber"], "1e400");
    assert_number(&first.configuration["smallNumber"], "1e-400");
    assert_number(
        &first.configuration["nested"]["array"][0],
        "18446744073709551617",
    );
    assert_number(
        &first.configuration["nested"]["array"][1],
        "-9223372036854775809",
    );
    assert_number(
        &first.configuration["nested"]["array"][2],
        "0.123456789012345678901234567890",
    );
    assert_number(&first.configuration["nested"]["array"][3], "1e400");
    assert_number(&first.configuration["nested"]["array"][4], "1e-400");
    assert_number(
        &first.configuration["nested"]["object"]["value"],
        "12345678901234567890.12345678901234567890",
    );

    let encoded_once = codec
        .encode_trigger(&first)
        .expect("canonical trigger encoding");
    let second = codec
        .decode_trigger(&encoded_once)
        .expect("canonical trigger decoding");
    let encoded_twice = codec
        .encode_trigger(&second)
        .expect("second canonical trigger encoding");

    assert_eq!(first.configuration, second.configuration);
    assert_eq!(encoded_once, encoded_twice);

    let encoded = std::str::from_utf8(&encoded_once).expect("UTF-8 JSON");
    for retained in [
        "18446744073709551617",
        "-9223372036854775809",
        "0.123456789012345678901234567890",
        "1e400",
        "1e-400",
        "12345678901234567890.12345678901234567890",
    ] {
        assert!(
            encoded.contains(retained),
            "canonical output did not retain `{retained}`: {encoded}"
        );
    }
}

#[test]
fn near_integral_fractions_are_field_specific_type_errors_for_every_integer_field() {
    let codec = JsonManifestCodec::default();

    let capsule_cases = [
        ("\"cpuFuel\": 1000000", "$.execution.limits.cpuFuel"),
        ("\"memoryBytes\": 4194304", "$.execution.limits.memoryBytes"),
        (
            "\"wallTimeLimitMillis\": null",
            "$.execution.limits.wallTimeLimitMillis",
        ),
        ("\"childCalls\": 0", "$.execution.limits.childCalls"),
        (
            "\"outboundRequests\": 0",
            "$.execution.limits.outboundRequests",
        ),
        ("\"stateReadBytes\": 0", "$.execution.limits.stateReadBytes"),
        (
            "\"stateWriteBytes\": 0",
            "$.execution.limits.stateWriteBytes",
        ),
        ("\"blobReadBytes\": 0", "$.execution.limits.blobReadBytes"),
        ("\"blobWriteBytes\": 0", "$.execution.limits.blobWriteBytes"),
        ("\"logBytes\": 16384", "$.execution.limits.logBytes"),
        ("\"effectCount\": 0", "$.execution.limits.effectCount"),
        (
            "\"hostCallDepthMaximum\": 8",
            "$.execution.hostCallDepthMaximum",
        ),
        (
            "\"componentCallDepthMaximum\": 4",
            "$.execution.componentCallDepthMaximum",
        ),
    ];
    for (anchor, path) in capsule_cases {
        let document = replace_number(CAPSULE, anchor);
        let violations = codec
            .decode_capsule(document.as_bytes())
            .expect_err("near-integral fraction must not enter a typed integer field");
        assert_single_violation(&violations, path, "invalid-type");
    }

    let deployment_cases = [
        ("\"weight\": 10000", "$.spec.route.weight"),
        ("\"cpuFuel\": 1000000", "$.spec.resources.cpuFuel"),
        ("\"memoryBytes\": 4194304", "$.spec.resources.memoryBytes"),
        (
            "\"wallTimeLimitMillis\": null",
            "$.spec.resources.wallTimeLimitMillis",
        ),
        ("\"childCalls\": 0", "$.spec.resources.childCalls"),
        (
            "\"outboundRequests\": 0",
            "$.spec.resources.outboundRequests",
        ),
        ("\"stateReadBytes\": 0", "$.spec.resources.stateReadBytes"),
        ("\"stateWriteBytes\": 0", "$.spec.resources.stateWriteBytes"),
        ("\"blobReadBytes\": 0", "$.spec.resources.blobReadBytes"),
        ("\"blobWriteBytes\": 0", "$.spec.resources.blobWriteBytes"),
        ("\"logBytes\": 16384", "$.spec.resources.logBytes"),
        ("\"effectCount\": 0", "$.spec.resources.effectCount"),
        (
            "\"minimumCachedCopies\": 1",
            "$.spec.availability.minimumCachedCopies",
        ),
        ("\"minimumZones\": 1", "$.spec.availability.minimumZones"),
    ];
    for (anchor, path) in deployment_cases {
        let document = replace_number(DEPLOYMENT, anchor);
        let violations = codec
            .decode_deployment(document.as_bytes())
            .expect_err("near-integral fraction must not enter a typed integer field");
        assert_single_violation(&violations, path, "invalid-type");
    }
}

#[test]
fn violations_deduplicate_by_stable_path_and_code_identity() {
    let mut violations = vec![
        ManifestViolation::new("$.value", "out-of-range", "schema diagnostic"),
        ManifestViolation::new("$.value", "out-of-range", "model diagnostic"),
    ];
    violations.sort();
    violations.dedup();
    assert_eq!(violations.len(), 1);
}

#[test]
fn schema_width_overflows_emit_one_path_code_pair() {
    let codec = JsonManifestCodec::default();

    let u32_overflow = CAPSULE.replacen(
        "\"hostCallDepthMaximum\": 8",
        "\"hostCallDepthMaximum\": 4294967296",
        1,
    );
    let violations = codec
        .decode_capsule(u32_overflow.as_bytes())
        .expect_err("u32 overflow");
    assert_single_violation(
        &violations,
        "$.execution.hostCallDepthMaximum",
        "out-of-range",
    );

    let u64_overflow = CAPSULE.replacen(
        "\"memoryBytes\": 4194304",
        "\"memoryBytes\": 18446744073709551616",
        1,
    );
    let violations = codec
        .decode_capsule(u64_overflow.as_bytes())
        .expect_err("u64 overflow");
    assert_single_violation(
        &violations,
        "$.execution.limits.memoryBytes",
        "out-of-range",
    );

    let route_overflow = DEPLOYMENT.replacen("\"weight\": 10000", "\"weight\": 10001", 1);
    let violations = codec
        .decode_deployment(route_overflow.as_bytes())
        .expect_err("route weight overflow");
    assert_single_violation(&violations, "$.spec.route.weight", "out-of-range");
}

fn trigger_document(configuration: &str) -> String {
    format!(
        r#"{{
            "apiVersion": "latent.dev/v1alpha1",
            "kind": "HttpTrigger",
            "metadata": {{
                "name": "echo-http",
                "tenant": "examples"
            }},
            "spec": {{
                "target": {{
                    "service": "examples/echo",
                    "contract": "examples:echo/api@0.1.0",
                    "function": "echo",
                    "route": "production"
                }},
                "configuration": {configuration}
            }}
        }}"#
    )
}

fn replace_number(template: &str, anchor: &str) -> String {
    assert!(template.contains(anchor), "test anchor must remain present");
    let field = anchor
        .split_once(':')
        .map(|(field, _)| field)
        .expect("field anchor");
    template.replacen(anchor, &format!("{field}: {NEAR_INTEGRAL_FRACTION}"), 1)
}

fn assert_number(value: &Value, expected: &str) {
    let number = value.as_number().expect("retained JSON number");
    assert_eq!(number.as_str(), expected);
}

fn assert_single_violation(
    violations: &[ManifestViolation],
    expected_path: &str,
    expected_code: &str,
) {
    assert_eq!(
        violations.len(),
        1,
        "expected exactly one violation, got {violations:#?}"
    );
    assert_eq!(violations[0].path, expected_path);
    assert_eq!(violations[0].code, expected_code);
}

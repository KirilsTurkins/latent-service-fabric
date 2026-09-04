use std::collections::BTreeMap;

use latent_core::{ContractId, ServiceId, TenantId, TriggerId};
use latent_manifest::{
    JsonManifestCodec, ManifestCodec, ManifestLimits, ManifestViolation, ObjectMetadata,
    TriggerKind, TriggerManifest, TriggerTarget, MANIFEST_API_VERSION,
};
use serde_json::Value;

#[test]
fn decode_enforces_the_canonical_payload_limit_and_remains_closed_under_encode() {
    let source = trigger_source(r#"{"value":1e20}"#);
    let canonical = canonical_bytes(&source);
    assert!(
        source.len() < canonical.len(),
        "the fixture must expand during numeric canonicalization"
    );

    let exact = codec_with_limit(canonical.len());
    let decoded = exact
        .decode_trigger(&source)
        .expect("source and canonical form fit the exact canonical limit");
    let encoded = exact
        .encode_trigger(&decoded)
        .expect("every admitted trigger must encode with the same limits");
    assert_eq!(encoded, canonical);

    let below = codec_with_limit(canonical.len() - 1);
    assert!(source.len() <= below.limits().max_document_bytes);
    let first = below
        .decode_trigger(&source)
        .expect_err("canonical form is one byte above the configured limit");
    let second = below
        .decode_trigger(&source)
        .expect_err("canonical-size rejection must be deterministic");
    assert_eq!(first, second);
    assert_payload_too_large(&first, canonical.len(), canonical.len() - 1);

    let canonical_violation = below
        .decode_trigger(&canonical)
        .expect_err("canonical bytes one byte above the limit must be rejected");
    assert_payload_too_large(
        &canonical_violation,
        canonical.len(),
        canonical.len() - 1,
    );
}

#[test]
fn direct_models_are_limited_after_number_canonicalization() {
    let compact = direct_manifest(number("1.5"));
    let verbose = direct_manifest(number(
        "1.50000000000000000000000000000000000000000000000000",
    ));
    let canonical = JsonManifestCodec::default()
        .encode_trigger(&compact)
        .expect("compact direct model");
    let verbose_wire = serde_json::to_vec(&verbose).expect("verbose trigger JSON");
    assert!(
        verbose_wire.len() > canonical.len(),
        "the verbose model must exceed its canonical representation"
    );

    let exact = codec_with_limit(canonical.len());
    assert_eq!(
        exact
            .encode_trigger(&compact)
            .expect("compact form at exact limit"),
        canonical
    );
    assert_eq!(
        exact
            .encode_trigger(&verbose)
            .expect("verbose equivalent must be canonicalized before the size check"),
        canonical
    );

    let below = codec_with_limit(canonical.len() - 1);
    let compact_error = below
        .encode_trigger(&compact)
        .expect_err("compact canonical form is one byte above the limit");
    let verbose_error = below
        .encode_trigger(&verbose)
        .expect_err("verbose equivalent has the same canonical acceptance result");
    assert_eq!(compact_error, verbose_error);
    assert_payload_too_large(&compact_error, canonical.len(), canonical.len() - 1);
}

#[test]
fn nested_expanding_numbers_obey_the_canonical_payload_limit() {
    let source = trigger_source(
        r#"{"values":[[1e20,1e20,1e20,1e20],[1e20,1e20,1e20,1e20]]}"#,
    );
    let canonical = canonical_bytes(&source);
    assert!(source.len() < canonical.len());

    let exact = codec_with_limit(canonical.len());
    let decoded = exact
        .decode_trigger(&source)
        .expect("nested canonical form at the exact limit");
    assert_eq!(
        exact
            .encode_trigger(&decoded)
            .expect("nested admitted trigger remains encodable"),
        canonical
    );

    let below = codec_with_limit(canonical.len() - 1);
    assert!(source.len() <= below.limits().max_document_bytes);
    let violations = below
        .decode_trigger(&source)
        .expect_err("nested numeric expansion must obey the canonical limit");
    assert_payload_too_large(&violations, canonical.len(), canonical.len() - 1);
}

fn canonical_bytes(source: &[u8]) -> Vec<u8> {
    let codec = JsonManifestCodec::default();
    let decoded = codec
        .decode_trigger(source)
        .expect("schema-valid trigger source");
    codec
        .encode_trigger(&decoded)
        .expect("canonical trigger encoding")
}

fn codec_with_limit(max_document_bytes: usize) -> JsonManifestCodec {
    JsonManifestCodec::new(ManifestLimits {
        max_document_bytes,
        ..ManifestLimits::default()
    })
}

fn direct_manifest(value: Value) -> TriggerManifest {
    let mut manifest = base_trigger();
    manifest.configuration.insert("value".to_owned(), value);
    manifest
}

fn number(text: &str) -> Value {
    let value: Value = serde_json::from_str(text).expect("valid arbitrary-precision JSON number");
    assert!(value.is_number());
    value
}

fn trigger_source(configuration: &str) -> Vec<u8> {
    format!(
        r#"{{"apiVersion":"latent.dev/v1alpha1","kind":"HttpTrigger","metadata":{{"name":"canonical-payload-test","tenant":"examples"}},"spec":{{"target":{{"service":"examples/echo","contract":"examples:echo/api@0.1.0","function":"echo","route":"production"}},"configuration":{configuration}}}}}"#
    )
    .into_bytes()
}

fn base_trigger() -> TriggerManifest {
    let name = "canonical-payload-test".to_owned();
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

fn assert_payload_too_large(
    violations: &[ManifestViolation],
    actual: usize,
    maximum: usize,
) {
    assert_eq!(violations.len(), 1, "unexpected violations: {violations:#?}");
    assert_eq!(violations[0].path, "$");
    assert_eq!(violations[0].code, "payload-too-large");
    assert!(
        violations[0].message.contains(&actual.to_string()),
        "diagnostic must contain the canonical byte count: {violations:#?}"
    );
    assert!(
        violations[0].message.contains(&maximum.to_string()),
        "diagnostic must contain the configured maximum: {violations:#?}"
    );
}

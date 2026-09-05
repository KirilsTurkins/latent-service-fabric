use latent_manifest::{
    JsonManifestCodec, ManifestCodec, ManifestDocument, ManifestLimits, ManifestResult,
    ManifestValidator, ManifestViolation, Phase1ManifestValidator,
};
use serde_json::{json, Value};

const CAPSULE: &[u8] = include_bytes!("fixtures/valid-capsule-v1alpha1.json");
const DEPLOYMENT: &[u8] = include_bytes!("fixtures/valid-deployment-v1alpha1.json");
const BINDING: &[u8] = include_bytes!("fixtures/valid-binding-v1alpha1.json");
const TRIGGER: &[u8] = include_bytes!("fixtures/valid-trigger-v1alpha1.json");
const POLICY: &[u8] = include_bytes!("fixtures/valid-policy-v1alpha1.json");

type RoundTrip = fn(&JsonManifestCodec, &[u8]) -> ManifestResult<Vec<u8>>;

#[test]
fn capsule_schema_defaults_are_closed_under_the_canonical_payload_limit() {
    let (explicit_source, omitted_source) = capsule_default_sources();
    let default_codec = JsonManifestCodec::default();

    let explicit = default_codec
        .decode_capsule(&explicit_source)
        .expect("explicit schema defaults must decode");
    let omitted = default_codec
        .decode_capsule(&omitted_source)
        .expect("omitted schema defaults must decode");
    assert_eq!(explicit, omitted);

    Phase1ManifestValidator::new()
        .validate_capsule(&omitted)
        .expect("the defaulted capsule must be fully admissible in Phase 1");

    let canonical = default_codec
        .encode_capsule(&explicit)
        .expect("explicit defaults must have canonical bytes");
    assert_eq!(
        canonical,
        default_codec
            .encode_capsule(&omitted)
            .expect("omitted defaults must have the same canonical bytes")
    );
    assert!(
        omitted_source.len() < canonical.len(),
        "the fixture must demonstrate expansion from omitted schema defaults"
    );

    let exact = codec_with_limit(canonical.len());
    let decoded = exact
        .decode_capsule(&omitted_source)
        .expect("the canonical form fits the exact payload limit");
    Phase1ManifestValidator::new()
        .validate_capsule(&decoded)
        .expect("the exactly bounded capsule remains fully admissible");
    assert_eq!(
        exact
            .encode_capsule(&decoded)
            .expect("successful decode must remain encodable under identical limits"),
        canonical
    );

    let document = exact
        .decode_document(&omitted_source)
        .expect("type-erased decoding has the same closure guarantee");
    assert!(matches!(document, ManifestDocument::Capsule(_)));
    assert_eq!(
        exact
            .encode_document(&document)
            .expect("type-erased admitted document must remain encodable"),
        canonical
    );

    let below = codec_with_limit(canonical.len() - 1);
    assert!(
        omitted_source.len() <= below.limits().max_document_bytes,
        "the source itself must fit so rejection is caused by canonical expansion"
    );
    let first = below
        .decode_capsule(&omitted_source)
        .expect_err("canonical default materialization exceeds the payload limit");
    let second = below
        .decode_capsule(&omitted_source)
        .expect_err("canonical-size rejection must be deterministic");
    assert_eq!(first, second);
    assert_payload_too_large(&first, canonical.len(), canonical.len() - 1);

    let document_violations = below
        .decode_document(&omitted_source)
        .expect_err("type-erased decoding must reject the same canonical overflow");
    assert_eq!(first, document_violations);
}

#[test]
fn successful_decode_is_closed_under_encode_for_every_manifest_family() {
    let cases: [(&str, &[u8], RoundTrip); 5] = [
        ("capsule", CAPSULE, round_trip_capsule),
        ("deployment", DEPLOYMENT, round_trip_deployment),
        ("binding", BINDING, round_trip_binding),
        ("trigger", TRIGGER, round_trip_trigger),
        ("policy", POLICY, round_trip_policy),
    ];

    for (name, source, round_trip) in cases {
        let canonical = round_trip(&JsonManifestCodec::default(), source)
            .unwrap_or_else(|violations| panic!("{name} fixture failed: {violations:#?}"));
        let exact = codec_with_limit(canonical.len());
        let encoded = round_trip(&exact, &canonical).unwrap_or_else(|violations| {
            panic!("{name} was admitted but could not be re-encoded: {violations:#?}")
        });
        assert_eq!(encoded, canonical, "{name} canonical bytes changed");

        let document = exact
            .decode_document(&canonical)
            .unwrap_or_else(|violations| {
                panic!("type-erased {name} decode failed: {violations:#?}")
            });
        assert_eq!(
            exact
                .encode_document(&document)
                .unwrap_or_else(|violations| {
                    panic!("type-erased {name} encode failed: {violations:#?}")
                }),
            canonical,
            "type-erased {name} canonical bytes changed"
        );
    }
}

fn capsule_default_sources() -> (Vec<u8>, Vec<u8>) {
    let mut explicit: Value = serde_json::from_slice(CAPSULE).expect("canonical capsule fixture");
    let imports = explicit["imports"]
        .as_array_mut()
        .expect("capsule imports array");
    for import in imports {
        import["optional"] = Value::Bool(false);
    }

    let execution = explicit["execution"]
        .as_object_mut()
        .expect("capsule execution object");
    execution.insert("hostCallDepthMaximum".to_owned(), json!(1));
    execution.insert("componentCallDepthMaximum".to_owned(), json!(1));
    execution.insert("snapshotEligible".to_owned(), Value::Bool(false));
    execution.insert("fusionEligible".to_owned(), Value::Bool(false));

    let mut omitted = explicit.clone();
    for import in omitted["imports"]
        .as_array_mut()
        .expect("capsule imports array")
    {
        import
            .as_object_mut()
            .expect("capsule import object")
            .remove("optional");
    }
    let omitted_execution = omitted["execution"]
        .as_object_mut()
        .expect("capsule execution object");
    for field in [
        "hostCallDepthMaximum",
        "componentCallDepthMaximum",
        "snapshotEligible",
        "fusionEligible",
    ] {
        omitted_execution.remove(field);
    }

    (
        serde_json::to_vec(&explicit).expect("explicit-default capsule JSON"),
        serde_json::to_vec(&omitted).expect("omitted-default capsule JSON"),
    )
}

fn codec_with_limit(max_document_bytes: usize) -> JsonManifestCodec {
    JsonManifestCodec::new(ManifestLimits {
        max_document_bytes,
        ..ManifestLimits::default()
    })
}

fn round_trip_capsule(codec: &JsonManifestCodec, source: &[u8]) -> ManifestResult<Vec<u8>> {
    let manifest = codec.decode_capsule(source)?;
    codec.encode_capsule(&manifest)
}

fn round_trip_deployment(codec: &JsonManifestCodec, source: &[u8]) -> ManifestResult<Vec<u8>> {
    let manifest = codec.decode_deployment(source)?;
    codec.encode_deployment(&manifest)
}

fn round_trip_binding(codec: &JsonManifestCodec, source: &[u8]) -> ManifestResult<Vec<u8>> {
    let manifest = codec.decode_binding(source)?;
    codec.encode_binding(&manifest)
}

fn round_trip_trigger(codec: &JsonManifestCodec, source: &[u8]) -> ManifestResult<Vec<u8>> {
    let manifest = codec.decode_trigger(source)?;
    codec.encode_trigger(&manifest)
}

fn round_trip_policy(codec: &JsonManifestCodec, source: &[u8]) -> ManifestResult<Vec<u8>> {
    let manifest = codec.decode_policy(source)?;
    codec.encode_policy(&manifest)
}

fn assert_payload_too_large(violations: &[ManifestViolation], actual: usize, maximum: usize) {
    assert_eq!(
        violations.len(),
        1,
        "unexpected violations: {violations:#?}"
    );
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

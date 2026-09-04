use std::fmt::Debug;

use latent_manifest::{
    JsonManifestCodec, ManifestCodec, ManifestKind, ManifestResult, ManifestValidator,
    Phase1ManifestValidator,
};

const CAPSULE_FIXTURE: &[u8] = include_bytes!("fixtures/valid-capsule-v1alpha1.json");
const DEPLOYMENT_FIXTURE: &[u8] = include_bytes!("fixtures/valid-deployment-v1alpha1.json");
const BINDING_FIXTURE: &[u8] = include_bytes!("fixtures/valid-binding-v1alpha1.json");
const TRIGGER_FIXTURE: &[u8] = include_bytes!("fixtures/valid-trigger-v1alpha1.json");
const POLICY_FIXTURE: &[u8] = include_bytes!("fixtures/valid-policy-v1alpha1.json");

#[test]
fn capsule_golden_fixture_is_schema_valid_and_byte_stable() {
    assert_golden(
        CAPSULE_FIXTURE,
        ManifestKind::Capsule,
        |codec, bytes| codec.decode_capsule(bytes),
        |codec, manifest| codec.encode_capsule(manifest),
    );
}

#[test]
fn deployment_golden_fixture_is_schema_valid_and_byte_stable() {
    assert_golden(
        DEPLOYMENT_FIXTURE,
        ManifestKind::Deployment,
        |codec, bytes| codec.decode_deployment(bytes),
        |codec, manifest| codec.encode_deployment(manifest),
    );
}

#[test]
fn binding_golden_fixture_is_schema_valid_and_byte_stable() {
    assert_golden(
        BINDING_FIXTURE,
        ManifestKind::Binding,
        |codec, bytes| codec.decode_binding(bytes),
        |codec, manifest| codec.encode_binding(manifest),
    );
}

#[test]
fn trigger_golden_fixture_is_schema_valid_and_byte_stable() {
    assert_golden(
        TRIGGER_FIXTURE,
        ManifestKind::Trigger,
        |codec, bytes| codec.decode_trigger(bytes),
        |codec, manifest| codec.encode_trigger(manifest),
    );
}

#[test]
fn policy_golden_fixture_is_schema_valid_and_byte_stable() {
    assert_golden(
        POLICY_FIXTURE,
        ManifestKind::Policy,
        |codec, bytes| codec.decode_policy(bytes),
        |codec, manifest| codec.encode_policy(manifest),
    );
}

#[test]
fn golden_fixtures_pass_phase1_semantic_validation() {
    let codec = JsonManifestCodec::default();
    let validator = Phase1ManifestValidator::new();
    let capsule = codec
        .decode_capsule(CAPSULE_FIXTURE)
        .expect("capsule golden fixture");
    let deployment = codec
        .decode_deployment(DEPLOYMENT_FIXTURE)
        .expect("deployment golden fixture");

    validator
        .validate_capsule(&capsule)
        .expect("capsule Phase 1 semantics");
    validator
        .validate_deployment(&deployment)
        .expect("deployment Phase 1 semantics");
    validator
        .validate_deployment_against_capsule(&deployment, &capsule)
        .expect("cross-manifest Phase 1 semantics");
    validator
        .validate_binding(
            &codec
                .decode_binding(BINDING_FIXTURE)
                .expect("binding golden fixture"),
        )
        .expect("binding Phase 1 semantics");
    validator
        .validate_trigger(
            &codec
                .decode_trigger(TRIGGER_FIXTURE)
                .expect("trigger golden fixture"),
        )
        .expect("trigger Phase 1 semantics");
    validator
        .validate_policy(
            &codec
                .decode_policy(POLICY_FIXTURE)
                .expect("policy golden fixture"),
        )
        .expect("policy Phase 1 semantics");
}

fn assert_golden<T>(
    fixture: &[u8],
    expected_kind: ManifestKind,
    decode: impl Fn(&JsonManifestCodec, &[u8]) -> ManifestResult<T>,
    encode: impl Fn(&JsonManifestCodec, &T) -> ManifestResult<Vec<u8>>,
) where
    T: Debug + PartialEq,
{
    let codec = JsonManifestCodec::default();
    let document = codec
        .decode_document(fixture)
        .expect("golden fixture must pass its canonical schema");
    assert_eq!(document.kind(), expected_kind);

    let manifest = decode(&codec, fixture).expect("golden fixture must decode");
    let first = encode(&codec, &manifest).expect("golden fixture must encode");
    let second = encode(&codec, &manifest).expect("repeated encoding must succeed");
    assert_eq!(first, second, "repeated encoding must be byte stable");

    let expected = fixture.strip_suffix(b"\n").unwrap_or(fixture);
    assert_eq!(
        first.as_slice(),
        expected,
        "checked-in fixture must be the canonical wire encoding"
    );

    let round_tripped = decode(&codec, &first).expect("canonical JSON must decode");
    assert_eq!(manifest, round_tripped, "round trip must preserve meaning");
    let third = encode(&codec, &round_tripped).expect("round-trip encoding must succeed");
    assert_eq!(first, third, "round-trip encoding must remain byte stable");
}

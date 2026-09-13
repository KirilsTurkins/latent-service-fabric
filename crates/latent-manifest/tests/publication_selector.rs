use latent_manifest::{JsonManifestCodec, ManifestCodec};
use serde_json::{json, Value};

const LEGACY: &[u8] = include_bytes!("fixtures/valid-deployment-v1alpha1.json");

#[test]
fn explicit_publication_roundtrips_without_reinterpreting_component_identity() {
    let codec = JsonManifestCodec::default();
    let legacy = codec.decode_deployment(LEGACY).unwrap();
    assert!(legacy.publication.is_none());
    let old_canonical = codec.encode_deployment(&legacy).unwrap();
    let mut document: Value = serde_json::from_slice(LEGACY).unwrap();
    let selected = format!("publication:sha256:{}", "ab".repeat(32));
    document["spec"]["publication"] = json!(selected);
    let current = codec
        .decode_deployment(&serde_json::to_vec(&document).unwrap())
        .unwrap();
    assert_eq!(current.release, legacy.release);
    assert_eq!(current.publication.as_ref().unwrap().as_str(), selected);
    assert_eq!(
        codec
            .decode_deployment(&codec.encode_deployment(&current).unwrap())
            .unwrap(),
        current
    );
    let mut restored = current;
    restored.publication = None;
    assert_eq!(codec.encode_deployment(&restored).unwrap(), old_canonical);
}

#[test]
fn present_publication_requires_exact_typed_identity() {
    let codec = JsonManifestCodec::default();
    for invalid in [
        json!(null),
        json!(17),
        json!(""),
        json!(format!("sha256:{}", "ab".repeat(32))),
        json!(format!("publication:sha256:{}", "AB".repeat(32))),
        json!(format!("publication:sha256:{}\n", "ab".repeat(32))),
        json!({"id":"publication"}),
    ] {
        let mut document: Value = serde_json::from_slice(LEGACY).unwrap();
        document["spec"]["publication"] = invalid.clone();
        assert!(
            codec
                .decode_deployment(&serde_json::to_vec(&document).unwrap())
                .is_err(),
            "accepted {invalid}"
        );
    }
}

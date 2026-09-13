use latent_manifest::{
    JsonManifestCodec, ManifestCodec, ManifestValidator, Phase1ManifestValidator,
};

const DEPLOYMENT: &[u8] = include_bytes!("fixtures/valid-deployment-v1alpha1.json");

#[test]
fn shared_normalization_matches_codec_and_preserves_optional_resources() {
    let codec = JsonManifestCodec::default();
    for wall_limit in [None, Some(1_500)] {
        let mut value = codec.decode_deployment(DEPLOYMENT).unwrap();
        value.release.0 = format!("sha256:{}", "A".repeat(64));
        value.grants.reverse();
        for grant in &mut value.grants {
            grant.operations = vec!["write".into(), "read".into()];
        }
        value.placement.architectures.reverse();
        value.placement.regions = vec!["us-east".into(), "eu-west".into()];
        value.placement.zones = vec!["zone-b".into(), "zone-a".into()];
        value.placement.required_features = vec!["simd".into(), "bulk-memory".into()];
        value.resources.wall_time_limit_millis = wall_limit;
        Phase1ManifestValidator.validate_deployment(&value).unwrap();
        let resources = value.resources.clone();
        let metadata = value.metadata.clone();
        let expected_bytes = codec.encode_deployment(&value).unwrap();
        let expected = codec.decode_deployment(&expected_bytes).unwrap();
        value.normalize_storage_fields();
        assert_eq!(value, expected);
        assert_eq!(value.resources, resources);
        assert_eq!(value.metadata, metadata);
        assert_eq!(value.release.0, format!("sha256:{}", "a".repeat(64)));
        assert_eq!(value.placement.architectures, ["aarch64", "x86_64"]);
        assert_eq!(value.placement.regions, ["eu-west", "us-east"]);
        assert_eq!(value.placement.zones, ["zone-a", "zone-b"]);
        assert_eq!(value.placement.required_features, ["bulk-memory", "simd"]);
        assert!(value
            .grants
            .iter()
            .all(|grant| grant.operations == ["read", "write"]));
        value.normalize_storage_fields();
        assert_eq!(codec.encode_deployment(&value).unwrap(), expected_bytes);
    }
}

#[test]
fn equal_sort_keys_keep_original_grant_order_and_are_not_deduplicated() {
    let codec = JsonManifestCodec::default();
    let mut value = codec.decode_deployment(DEPLOYMENT).unwrap();
    let mut first = value.grants[0].clone();
    first.constraints.insert("position".into(), "first".into());
    let mut second = first.clone();
    second
        .constraints
        .insert("position".into(), "second".into());
    // The field normalizer does not validate or authorize duplicate grants.
    value.grants = vec![first.clone(), second.clone()];
    value.normalize_storage_fields();
    assert_eq!(value.grants, [first, second]);
}

use super::*;

#[test]
fn prepared_parameter_types_define_canonical_record_and_tagged_business_input() {
    let limits = ValueCodecLimits::default();
    let examples = [
        (
            "record",
            r#"[ { "count":7, "name":"test" } ]"#,
            r#"[{"name":"test","count":7}]"#,
        ),
        (
            "variant",
            r#"[{"value":"9","case":"number"}]"#,
            r#"[{"case":"number","value":"9"}]"#,
        ),
        ("flags", r#"[["admin","read"]]"#, r#"[["read","admin"]]"#),
        (
            "result",
            r#"[{"err":{"value":"42","case":"number"}}]"#,
            r#"[{"err":{"case":"number","value":"42"}}]"#,
        ),
    ];
    for (name, input, expected) in examples {
        let signature = [types()[name].clone()];
        let canonical = canonical_params(&signature, input.as_bytes(), MEDIA_TYPE, limits).unwrap();
        assert_eq!(canonical, expected.as_bytes());
        assert_eq!(
            canonical_params(&signature, &canonical, MEDIA_TYPE, limits).unwrap(),
            canonical
        );
    }
}

#[test]
fn canonical_parameters_retain_changed_values_presence_and_original_codec_limits() {
    let signature = [types()["record"].clone()];
    let limits = ValueCodecLimits::default();
    let canonical = |input: &[u8]| canonical_params(&signature, input, MEDIA_TYPE, limits);
    assert_ne!(
        canonical(br#"[{"name":"test","count":7}]"#).unwrap(),
        canonical(br#"[{"count":8,"name":"test"}]"#).unwrap()
    );
    for invalid in [
        br#"[{"name":"test","count":7,"count":8}]"#.as_slice(),
        br#"[{"name":"test"}]"#,
        br#"[{"name":"test","count":7,"extra":0}]"#,
    ] {
        assert!(canonical(invalid).is_err());
    }
    assert!(canonical_params(
        &signature,
        br#"[{"name":"test","count":7}]"#,
        "application/json",
        limits
    )
    .is_err());
    let limited = ValueCodecLimits {
        max_output_bytes: 10,
        ..limits
    };
    assert!(canonical_params(
        &signature,
        br#"[{"name":"test","count":7}]"#,
        MEDIA_TYPE,
        limited
    )
    .is_err());
    let option = [types()["option"].clone()];
    assert_ne!(
        canonical_params(&option, br#"[{"none":null}]"#, MEDIA_TYPE, limits).unwrap(),
        canonical_params(&option, br#"[{"some":""}]"#, MEDIA_TYPE, limits).unwrap()
    );
}

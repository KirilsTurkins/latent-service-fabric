use super::*;

#[test]
fn all_composites_encode_with_explicit_tags_and_declaration_order() {
    let examples = [
        ("list", "[[]]", "[[]]"),
        ("list", "[[0,255]]", "[[0,255]]"),
        ("tuple", r#"[[false,"-1"]]"#, r#"[[false,"-1"]]"#),
        (
            "record",
            r#"[{"count":7,"name":"test"}]"#,
            r#"[{"name":"test","count":7}]"#,
        ),
        ("variant", r#"[{"case":"empty"}]"#, r#"[{"case":"empty"}]"#),
        (
            "variant",
            r#"[{"value":"9","case":"number"}]"#,
            r#"[{"case":"number","value":"9"}]"#,
        ),
        ("enum", r#"["blue"]"#, r#"["blue"]"#),
        ("flags", r#"[["admin","read"]]"#, r#"[["read","admin"]]"#),
        ("option", r#"[{"none":null}]"#, r#"[{"none":null}]"#),
        ("option", r#"[{"some":""}]"#, r#"[{"some":""}]"#),
        (
            "nested",
            r#"[{"some":{"none":null}}]"#,
            r#"[{"some":{"none":null}}]"#,
        ),
        (
            "nested",
            r#"[{"some":{"some":"x"}}]"#,
            r#"[{"some":{"some":"x"}}]"#,
        ),
        ("result", r#"[{"ok":"hello"}]"#, r#"[{"ok":"hello"}]"#),
        (
            "result",
            r#"[{"err":{"case":"number","value":"42"}}]"#,
            r#"[{"err":{"case":"number","value":"42"}}]"#,
        ),
        ("unit-result", r#"[{"ok":null}]"#, r#"[{"ok":null}]"#),
        ("unit-result", r#"[{"err":null}]"#, r#"[{"err":null}]"#),
    ];
    for (name, input, expected) in examples {
        assert_eq!(
            round_trip(&[types()[name].clone()], input),
            expected,
            "{name}"
        );
    }
}

#[test]
fn declared_error_is_only_the_single_top_level_result_branch() {
    let ty = types()["result"].clone();
    let json = r#"[{"err":{"case":"empty"}}]"#;
    let EncodedResult::DeclaredError(error) = encode_result(
        std::slice::from_ref(&ty),
        &decode(std::slice::from_ref(&ty), json),
        ValueCodecLimits::default(),
    )
    .expect("encode") else {
        panic!("declared error")
    };
    assert_eq!(error.code, "declared-error");
    assert_eq!(error.message, "component returned a declared error");
    assert_eq!(error.media_type, MEDIA_TYPE);
    assert_eq!(error.payload, json.as_bytes());
    let nested_ty = types()["nested-result"].clone();
    let nested_json = r#"[[{"err":{"case":"empty"}}]]"#;
    assert!(matches!(
        encode_result(
            std::slice::from_ref(&nested_ty),
            &decode(std::slice::from_ref(&nested_ty), nested_json),
            ValueCodecLimits::default()
        )
        .expect("nested result"),
        EncodedResult::Returned(_)
    ));
    let multiple = [ty.clone(), ty];
    let json = r#"[{"err":{"case":"empty"}},{"ok":"yes"}]"#;
    assert!(matches!(
        encode_result(
            &multiple,
            &decode(&multiple, json),
            ValueCodecLimits::default()
        )
        .expect("multiple results"),
        EncodedResult::Returned(_)
    ));
}

#[test]
fn malformed_composites_do_not_gain_defaults_or_drop_fields() {
    for (name, json) in [
        ("tuple", "[[true]]"),
        ("record", r#"[{"name":"a"}]"#),
        ("record", r#"[{"name":"a","count":1,"extra":0}]"#),
        ("record", r#"[{"name":"a","name":"b","count":1}]"#),
        ("record", r#"[{"name":"a","\u006eame":"b","count":1}]"#),
        ("variant", r#"[{"case":"empty","value":null}]"#),
        ("variant", r#"[{"case":"number"}]"#),
        ("variant", r#"[{"case":"unknown"}]"#),
        ("enum", r#"["green"]"#),
        ("flags", r#"[["read","read"]]"#),
        ("flags", r#"[["unknown"]]"#),
        ("option", "[null]"),
        ("option", r#"[{"none":false}]"#),
        ("option", r#"[{"some":"x","none":null}]"#),
        ("unit-result", r#"[{"ok":false}]"#),
        ("result", r#"[{"err":null}]"#),
    ] {
        rejects(&types()[name], json);
    }
}

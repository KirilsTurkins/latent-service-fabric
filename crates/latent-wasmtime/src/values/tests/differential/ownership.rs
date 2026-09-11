use super::*;

#[test]
fn all_retained_text_is_owned_after_input_overwrite_and_destruction() {
    let signature = [
        Type::String,
        Type::String,
        Type::Char,
        types()["enum"].clone(),
        types()["flags"].clone(),
        types()["variant"].clone(),
        types()["nested"].clone(),
        types()["result"].clone(),
        types()["record-variant"].clone(),
    ];
    let input = r#"["unescaped-first","escaped\nsecond\ud83e\udd80","\u03bb","r\u0065d",["admin","\u0072ead"],{"value":"18446744073709551615","case":"number"},{"some":{"some":"nested\ttext"}},{"err":{"case":"number","value":"42"}},{"value":{"c":{"name":"third\u0000field","count":3},"a":{"count":1,"name":"first\nfield"},"b":{"name":"second\tfield","count":2}},"case":"record"}]"#;
    let mut bytes = input.as_bytes().to_vec();
    let expected =
        decode_params_legacy(&signature, &bytes, MEDIA_TYPE, ValueCodecLimits::default()).unwrap();
    let (actual, path) =
        decode_params_diagnostic(&signature, &bytes, MEDIA_TYPE, ValueCodecLimits::default());
    assert_eq!(path, DecodePath::TypedSuccess);
    let actual = actual.unwrap();
    bytes.fill(0xff);
    drop(bytes);
    same_values(
        "all owned text survives original input",
        &signature,
        &expected,
        &actual,
    );
    let Val::String(first) = &actual[0] else {
        panic!("string result")
    };
    let Val::String(second) = &actual[1] else {
        panic!("string result")
    };
    assert_eq!(first, "unescaped-first");
    assert_eq!(second, "escaped\nsecond\u{1f980}");
}

#[test]
fn repeated_late_rejections_do_not_reuse_scratch_or_the_next_calls_budget() {
    let signature = [types()["wide-list"].clone()];
    let prefix = "prefix".repeat(128);
    let input = format!(
        r#"[[{{"a":{{"name":"{prefix}","count":1}},"b":{{"name":"{prefix}","count":2}},"c":{{"name":"{prefix}","count":false}}}}]]"#
    );
    for _ in 0..16 {
        invalid("late invalid nested count", &signature, input.as_bytes());
        let mut next = br#"["\ud83e\udd80"]"#.to_vec();
        let actual = decode_params(
            &[Type::String],
            &next,
            MEDIA_TYPE,
            ValueCodecLimits {
                max_decoded_value_bytes: 520,
                ..ValueCodecLimits::default()
            },
        )
        .unwrap();
        next.fill(b'x');
        drop(next);
        let Val::String(text) = &actual[0] else {
            panic!("owned string")
        };
        assert_eq!(text, "\u{1f980}");
    }
}

#[test]
fn the_public_return_does_not_retain_a_large_unescaped_payload() {
    let length = 120 * 1024;
    let mut bytes = format!(r#"["{}"]"#, "x".repeat(length)).into_bytes();
    let actual = decode_params(
        &[Type::String],
        &bytes,
        MEDIA_TYPE,
        ValueCodecLimits::default(),
    )
    .unwrap();
    bytes.fill(b'y');
    drop(bytes);
    let Val::String(text) = &actual[0] else {
        panic!("owned large string")
    };
    assert_eq!(text.len(), length);
    assert!(text.bytes().all(|byte| byte == b'x'));
}

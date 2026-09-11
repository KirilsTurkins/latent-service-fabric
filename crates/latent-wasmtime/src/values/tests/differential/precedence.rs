use super::*;

#[test]
fn limits_media_and_full_lexical_preflight_keep_their_original_priority() {
    let broken_limits = ValueCodecLimits {
        max_nodes: 0,
        ..ValueCodecLimits::default()
    };
    let error = equivalent_media(
        "invalid limits before media",
        &[Type::Bool],
        b"\xff",
        "wrong",
        broken_limits,
    )
    .unwrap_err();
    assert_eq!(error.message, "invalid-value-codec-limits");
    let error = equivalent_media(
        "media before bytes",
        &[Type::Bool],
        b"\xff",
        "wrong",
        ValueCodecLimits::default(),
    )
    .unwrap_err();
    assert_eq!(error.message, "unsupported-invocation-media-type");
    rejected(
        "bytes before UTF-8",
        &[Type::Bool],
        b"[\xff]",
        ValueCodecLimits {
            max_input_bytes: 2,
            ..ValueCodecLimits::default()
        },
        PlatformErrorCode::ResourceExhausted,
        "invocation-value-limit",
    );
    invalid("UTF-8 before grammar", &[Type::Bool], b"[\xff]");
    rejected(
        "late lexical limit before early wrong type",
        &[Type::Bool],
        br#"[1,"12345"]"#,
        ValueCodecLimits {
            max_string_bytes: 4,
            ..ValueCodecLimits::default()
        },
        PlatformErrorCode::ResourceExhausted,
        "invocation-value-limit",
    );
    rejected(
        "early malformed escape before later depth limit",
        &[Type::Bool],
        br#"["\q",[[[true]]]]"#,
        ValueCodecLimits {
            max_depth: 2,
            ..ValueCodecLimits::default()
        },
        PlatformErrorCode::InvalidArgument,
        "invalid-invocation-values",
    );
}

#[test]
fn complete_grammar_collection_and_arity_checks_precede_typed_children() {
    rejected(
        "collection before wrong first parameter",
        &[Type::Bool],
        b"[1,[0,1]]",
        ValueCodecLimits {
            max_collection_items: 1,
            ..ValueCodecLimits::default()
        },
        PlatformErrorCode::ResourceExhausted,
        "invocation-value-limit",
    );
    let small = ValueCodecLimits {
        max_decoded_value_bytes: 1,
        ..ValueCodecLimits::default()
    };
    for input in [
        b"[true] null".as_slice(),
        b"[true,]",
        b"[true}",
        b"[true,false]",
        b"[]",
    ] {
        rejected(
            "grammar or root arity before retained charge",
            &[Type::Bool],
            input,
            small,
            PlatformErrorCode::InvalidArgument,
            "invalid-invocation-values",
        );
    }
    rejected(
        "valid empty root still has a charge",
        &[],
        b"[]",
        small,
        PlatformErrorCode::ResourceExhausted,
        "invocation-value-limit",
    );
    rejected(
        "tuple width before wrong child",
        &[types()["tuple"].clone()],
        br#"[["wrong"]]"#,
        ValueCodecLimits {
            max_decoded_value_bytes: 600,
            ..ValueCodecLimits::default()
        },
        PlatformErrorCode::InvalidArgument,
        "invalid-invocation-values",
    );
}

#[test]
fn duplicate_key_at_collection_capacity_keeps_the_collection_error() {
    let input = br#"[{"name":"x","count":1,"\u006eame":"duplicate"}]"#;
    let signature = [types()["record"].clone()];
    for (maximum, code) in [
        (2, PlatformErrorCode::ResourceExhausted),
        (3, PlatformErrorCode::InvalidArgument),
    ] {
        rejected(
            "capacity before duplicate key",
            &signature,
            input,
            ValueCodecLimits {
                max_collection_items: maximum,
                ..ValueCodecLimits::default()
            },
            code,
            if maximum == 2 {
                "invocation-value-limit"
            } else {
                "invalid-invocation-values"
            },
        );
    }
}

#[test]
fn reordered_record_errors_follow_declaration_order_and_transient_text_charges() {
    let signature = [types()["record"].clone()];
    let name = "x".repeat(100);
    for input in [
        format!(r#"[{{"count":false,"name":"{name}"}}]"#),
        format!(r#"[{{"name":"{name}","count":false}}]"#),
    ] {
        rejected(
            "name charge before invalid count",
            &signature,
            input.as_bytes(),
            ValueCodecLimits {
                max_decoded_value_bytes: 800,
                ..ValueCodecLimits::default()
            },
            PlatformErrorCode::ResourceExhausted,
            "invocation-value-limit",
        );
        invalid(
            "invalid count after valid name",
            &signature,
            input.as_bytes(),
        );
    }
    for (name, input, maximum) in [
        ("variant", r#"[{"case":"unknown"}]"#, 512),
        ("flags", r#"[["unknown"]]"#, 512),
        ("flags", r#"[["read","read"]]"#, 800),
    ] {
        rejected(
            "text or node charge before tag rejection",
            &[types()[name].clone()],
            input.as_bytes(),
            ValueCodecLimits {
                max_decoded_value_bytes: maximum,
                ..ValueCodecLimits::default()
            },
            PlatformErrorCode::ResourceExhausted,
            "invocation-value-limit",
        );
        invalid(
            "same tag rejected with enough budget",
            &[types()[name].clone()],
            input.as_bytes(),
        );
    }
}

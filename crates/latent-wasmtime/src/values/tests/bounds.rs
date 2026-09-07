use super::*;

fn limited_input(ty: &Type, json: &str, limits: ValueCodecLimits) {
    let error = decode_params(
        std::slice::from_ref(ty),
        json.as_bytes(),
        MEDIA_TYPE,
        limits,
    )
    .expect_err("bounded input");
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted, "{json}");
}

#[test]
fn input_bytes_depth_nodes_strings_and_collections_are_independently_bounded() {
    let limits = ValueCodecLimits::default();
    limited_input(
        &Type::Bool,
        "[true]",
        ValueCodecLimits {
            max_input_bytes: 5,
            ..limits
        },
    );
    limited_input(
        &types()["nested"],
        r#"[{"some":{"none":null}}]"#,
        ValueCodecLimits {
            max_depth: 2,
            ..limits
        },
    );
    // Array + record + two keys + two values = six nodes.
    limited_input(
        &types()["record"],
        r#"[{"name":"x","count":1}]"#,
        ValueCodecLimits {
            max_nodes: 5,
            ..limits
        },
    );
    limited_input(
        &Type::String,
        r#"["\ud83e\udd80"]"#,
        ValueCodecLimits {
            max_string_bytes: 3,
            ..limits
        },
    );
    limited_input(
        &Type::String,
        r#"["🦀"]"#,
        ValueCodecLimits {
            max_string_bytes: 3,
            ..limits
        },
    );
    limited_input(
        &types()["list"],
        "[[1,2]]",
        ValueCodecLimits {
            max_collection_items: 1,
            ..limits
        },
    );
    limited_input(
        &types()["record"],
        r#"[{"name":"x","count":1}]"#,
        ValueCodecLimits {
            max_collection_items: 1,
            ..limits
        },
    );
    assert!(decode_params(
        &[Type::String],
        br#"["\ud83e\udd80"]"#,
        MEDIA_TYPE,
        ValueCodecLimits {
            max_string_bytes: 4,
            ..limits
        }
    )
    .is_ok());
}

#[test]
fn decoded_values_have_a_separate_allocation_budget() {
    let limits = ValueCodecLimits {
        max_decoded_value_bytes: 512,
        ..ValueCodecLimits::default()
    };
    assert!(decode_params(&[Type::Bool], b"[true]", MEDIA_TYPE, limits).is_ok());
    limited_input(&Type::String, r#"["x"]"#, limits);
    limited_input(&types()["list"], "[[1]]", limits);
    // Raising the lifting allowance does not raise retained input's allowance.
    limited_input(
        &Type::String,
        r#"["x"]"#,
        ValueCodecLimits {
            max_lifted_bytes: 32 * 1024 * 1024,
            ..limits
        },
    );
}

#[test]
fn output_writer_checks_escaped_bytes_and_structure_during_emission() {
    let limits = ValueCodecLimits::default();
    let values = [Val::String("\u{0000}".to_owned())];
    let exact = br#"["\u0000"]"#;
    assert_eq!(
        payload(
            encode_result(
                &[Type::String],
                &values,
                ValueCodecLimits {
                    max_output_bytes: exact.len(),
                    ..limits
                }
            )
            .expect("exact output limit")
        )
        .as_bytes(),
        exact
    );
    let error = encode_result(
        &[Type::String],
        &values,
        ValueCodecLimits {
            max_output_bytes: exact.len() - 1,
            ..limits
        },
    )
    .err()
    .expect("output overflow");
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    let ty = types()["record"].clone();
    let values = decode(std::slice::from_ref(&ty), r#"[{"name":"x","count":1}]"#);
    let error = encode_result(
        std::slice::from_ref(&ty),
        &values,
        ValueCodecLimits {
            max_nodes: 5,
            ..limits
        },
    )
    .err()
    .expect("output nodes");
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    let error = encode_result(
        &[ty],
        &values,
        ValueCodecLimits {
            max_depth: 1,
            ..limits
        },
    )
    .err()
    .expect("output depth");
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
}

#[test]
fn wrong_framing_media_and_host_result_types_are_rejected() {
    for json in [
        "true",
        "[]",
        "[true,false]",
        "[true] false",
        "[true,]",
        "[true}",
    ] {
        rejects(&Type::Bool, json);
    }
    let error = decode_params(
        &[Type::Bool],
        b"[true]",
        "application/json",
        ValueCodecLimits::default(),
    )
    .expect_err("media");
    assert_eq!(error.message, "unsupported-invocation-media-type");
    let error = encode_result(&[Type::Bool], &[Val::U8(1)], ValueCodecLimits::default())
        .err()
        .expect("wrong host value");
    assert_eq!(error.code, PlatformErrorCode::Internal);
}

#[test]
fn signature_plan_accounts_for_nested_inline_list_amplification() {
    let limits = ValueCodecLimits::default();
    let small =
        validate_signature(&[types()["list"].clone()], limits, 128 * 1024).expect("small list");
    let wide =
        validate_signature(&[types()["wide-list"].clone()], limits, 128 * 1024).expect("wide list");
    assert_eq!(small.examined_type_nodes, 2);
    assert_eq!(wide.examined_type_nodes, 20);
    assert!(wide.per_fuel_lift_multiplier > small.per_fuel_lift_multiplier);
    assert!(wide.maximum_lift_bytes > small.maximum_lift_bytes);
    assert_eq!(
        wide.maximum_lift_bytes,
        wide.static_lift_bytes + 128 * 1024 * wide.per_fuel_lift_multiplier
    );
    let error = validate_signature(
        &[types()["wide-list"].clone()],
        ValueCodecLimits {
            max_lifted_bytes: wide.maximum_lift_bytes - 1,
            ..limits
        },
        128 * 1024,
    )
    .expect_err("lift allowance");
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    assert!(validate_signature(
        &[types()["wide-list"].clone()],
        ValueCodecLimits {
            max_lifted_bytes: wide.maximum_lift_bytes,
            ..limits
        },
        128 * 1024 + 1
    )
    .is_err());
}

#[test]
fn schema_walk_limits_and_unsupported_types_fail_before_values_exist() {
    let limits = ValueCodecLimits::default();
    for limited in [
        ValueCodecLimits {
            max_type_nodes: 1,
            ..limits
        },
        ValueCodecLimits {
            max_depth: 1,
            ..limits
        },
        ValueCodecLimits {
            max_type_name_bytes: 1,
            ..limits
        },
        ValueCodecLimits {
            max_collection_items: 1,
            ..limits
        },
    ] {
        assert_eq!(
            validate_signature(&[types()["record"].clone()], limited, 1)
                .expect_err("schema cap")
                .code,
            PlatformErrorCode::ResourceExhausted
        );
    }
    assert_eq!(
        validate_signature(&[Type::ErrorContext], limits, 1)
            .expect_err("unsupported type")
            .code,
        PlatformErrorCode::IncompatibleContract
    );
    assert!(validate_signature(&[Type::Bool], limits, usize::MAX).is_err());
    assert!(ValueCodecLimits {
        max_depth: 65,
        ..limits
    }
    .validate()
    .is_err());
    assert!(ValueCodecLimits {
        max_nodes: 0,
        ..limits
    }
    .validate()
    .is_err());
}

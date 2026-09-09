use super::*;

#[test]
fn actual_record_and_flag_scratch_slots_fit_the_existing_node_allowance() {
    let Type::Record(record) = &types()["record"] else {
        panic!("actual record fixture")
    };
    let field = record.fields().next().unwrap();
    let index_entry = (0_usize, field, false);
    let record_bytes = std::mem::size_of_val(&index_entry) + std::mem::size_of::<(String, Val)>();
    let flag_bytes = std::mem::size_of::<(usize, String)>() + std::mem::size_of::<String>();
    assert!(
        record_bytes <= 256,
        "actual declaration and final slot exceed the fixed node charge"
    );
    assert!(
        flag_bytes <= 256,
        "actual selected-name and final slot exceed the fixed node charge"
    );
}

#[test]
fn retained_charges_include_names_and_transient_numeric_text_at_exact_boundaries() {
    // Independent constants from the retained contract: root/value nodes 256,
    // twice decoded text/name bytes, plus one node per selected flag.
    let cases = [
        (vec![], "[]", 256),
        (vec![Type::Bool], "[true]", 512),
        (vec![Type::String], r#"[""]"#, 512),
        (vec![Type::String], r#"["x"]"#, 514),
        (vec![Type::Char], r#"["\ud83e\udd80"]"#, 520),
        (vec![Type::U64], r#"["12"]"#, 516),
        (vec![Type::S64], r#"["-12"]"#, 518),
        (vec![Type::Float32], r#"["1.5"]"#, 518),
        (vec![Type::Float64], r#"["-0"]"#, 516),
        (vec![types()["list"].clone()], "[[]]", 512),
        (vec![types()["list"].clone()], "[[1]]", 768),
        (vec![types()["tuple"].clone()], r#"[[true,"1"]]"#, 1026),
        (
            vec![types()["record"].clone()],
            r#"[{"count":1,"name":"x"}]"#,
            1044,
        ),
        (vec![types()["enum"].clone()], r#"["red"]"#, 518),
        (
            vec![types()["variant"].clone()],
            r#"[{"case":"empty"}]"#,
            522,
        ),
        (
            vec![types()["variant"].clone()],
            r#"[{"value":"1","case":"number"}]"#,
            782,
        ),
        (vec![types()["flags"].clone()], r#"[["read"]]"#, 776),
        (
            vec![types()["flags"].clone()],
            r#"[["write","read"]]"#,
            1042,
        ),
        (vec![types()["option"].clone()], r#"[{"none":null}]"#, 512),
        (vec![types()["option"].clone()], r#"[{"some":"x"}]"#, 770),
        (
            vec![types()["nested"].clone()],
            r#"[{"some":{"none":null}}]"#,
            768,
        ),
        (
            vec![types()["unit-result"].clone()],
            r#"[{"err":null}]"#,
            512,
        ),
        (vec![types()["result"].clone()], r#"[{"ok":"x"}]"#, 770),
        (
            vec![types()["result"].clone()],
            r#"[{"err":{"case":"empty"}}]"#,
            778,
        ),
    ];
    for (signature, input, exact) in cases {
        for ceiling in [exact - 1, exact, exact + 1] {
            let result = equivalent(
                input,
                &signature,
                input.as_bytes(),
                ValueCodecLimits {
                    max_decoded_value_bytes: ceiling,
                    ..ValueCodecLimits::default()
                },
            );
            if ceiling < exact {
                let error = result.expect_err("one byte below retained charge");
                assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
                assert_eq!(error.message, "invocation-value-limit");
            } else {
                result.expect("exact or larger retained charge");
            }
        }
    }
}

#[test]
fn lexical_and_typed_limits_are_independent_and_inclusive() {
    let input = br#"[{"count":1,"name":"x"}]"#;
    let signature = [types()["record"].clone()];
    for (limit, exact) in [
        ("input", input.len()),
        ("depth", 2),
        ("nodes", 6),
        ("string", 5),
        ("collection", 2),
    ] {
        for ceiling in [exact - 1, exact, exact + 1] {
            let mut limits = ValueCodecLimits::default();
            match limit {
                "input" => limits.max_input_bytes = ceiling,
                "depth" => limits.max_depth = ceiling,
                "nodes" => limits.max_nodes = ceiling,
                "string" => limits.max_string_bytes = ceiling,
                "collection" => limits.max_collection_items = ceiling,
                _ => unreachable!(),
            }
            let result = equivalent(limit, &signature, input, limits);
            assert_eq!(result.is_ok(), ceiling >= exact, "{limit}={ceiling}");
            if let Err(error) = result {
                assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
                assert_eq!(error.message, "invocation-value-limit");
            }
        }
    }
    equivalent(
        "output/schema/lift limits do not silently become input limits",
        &signature,
        input,
        ValueCodecLimits {
            max_output_bytes: 1,
            max_type_nodes: 1,
            max_type_name_bytes: 1,
            max_lifted_bytes: 1,
            ..ValueCodecLimits::default()
        },
    )
    .unwrap();
}

#[test]
fn near_input_string_and_collection_limits_remain_bounded_without_hidden_capacity_credit() {
    let defaults = ValueCodecLimits::default();
    for count in [
        defaults.max_collection_items - 1,
        defaults.max_collection_items,
        defaults.max_collection_items + 1,
    ] {
        let input = format!("[[{}]]", vec!["255"; count].join(","));
        let result = equivalent(
            "collection boundary",
            &[types()["list"].clone()],
            input.as_bytes(),
            defaults,
        );
        assert_eq!(result.is_ok(), count <= defaults.max_collection_items);
    }
    for length in [
        defaults.max_string_bytes - 1,
        defaults.max_string_bytes,
        defaults.max_string_bytes + 1,
    ] {
        let input = format!(r#"["{}"]"#, "x".repeat(length));
        let result = equivalent(
            "string boundary",
            &[Type::String],
            input.as_bytes(),
            defaults,
        );
        assert_eq!(result.is_ok(), length <= defaults.max_string_bytes);
    }
    // Exact input ceiling with legal small decoded content; trailing whitespace
    // is counted as input, and spare Vec capacity is not a codec input byte.
    let mut input = Vec::with_capacity(defaults.max_input_bytes + 4096);
    input.extend_from_slice(b"[true]");
    input.resize(defaults.max_input_bytes, b' ');
    equivalent(
        "exact byte ceiling with spare capacity",
        &[Type::Bool],
        &input,
        defaults,
    )
    .unwrap();
    input.push(b' ');
    rejected(
        "one excess input byte",
        &[Type::Bool],
        &input,
        defaults,
        PlatformErrorCode::ResourceExhausted,
        "invocation-value-limit",
    );
}

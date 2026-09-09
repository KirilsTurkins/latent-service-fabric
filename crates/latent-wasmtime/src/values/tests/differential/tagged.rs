use super::*;

const WIDE: &str =
    r#"{"c":{"count":3,"name":"c"},"a":{"name":"a","count":1},"b":{"count":2,"name":"b"}}"#;

#[test]
fn deferred_record_payloads_decode_in_either_order_and_reject_real_nested_duplicates() {
    let signature = [types()["record-variant"].clone()];
    for input in [
        format!(r#"[{{"value":{WIDE},"case":"record"}}]"#),
        format!(r#"[{{"case":"record","value":{WIDE}}}]"#),
        format!(r#"[{{"\u0076alue":{WIDE},"\u0063ase":"re\u0063ord"}}]"#),
    ] {
        equivalent(
            "valid typed record payload",
            &signature,
            input.as_bytes(),
            ValueCodecLimits::default(),
        )
        .unwrap();
    }
    let duplicate = WIDE.replacen(
        r#""name":"c""#,
        r#""name":"c","\u006eame":"replacement""#,
        1,
    );
    let unknown = WIDE.replacen(r#""name":"c""#, r#""extra":"c""#, 1);
    for value in [duplicate, unknown] {
        for input in [
            format!(r#"[{{"value":{value},"case":"record"}}]"#),
            format!(r#"[{{"case":"record","value":{value}}}]"#),
        ] {
            invalid(
                "nested record keys cannot be overwritten or ignored",
                &signature,
                input.as_bytes(),
            );
        }
    }
    for input in [
        format!(r#"[{{"value":{WIDE},"case":"empty"}}]"#),
        format!(r#"[{{"value":{WIDE},"case":"record","\u0063ase":"record"}}]"#),
        format!(r#"[{{"value":{WIDE},"\u0076alue":{WIDE},"case":"record"}}]"#),
        format!(r#"[{{"value":{WIDE},"case":"record","extra":null}}]"#),
    ] {
        invalid(
            "outer variant structure is exact",
            &signature,
            input.as_bytes(),
        );
    }
}

#[test]
fn deferred_values_share_original_depth_nodes_collections_and_retained_ledger() {
    let signature = [types()["record-variant"].clone()];
    let input = format!(r#"[{{"value":{WIDE},"case":"record"}}]"#);
    for (limit, exact) in [
        ("depth", 4),
        ("nodes", 24),
        ("collection", 3),
        ("decoded", 3150),
    ] {
        for ceiling in [exact - 1, exact, exact + 1] {
            let mut limits = ValueCodecLimits::default();
            match limit {
                "depth" => limits.max_depth = ceiling,
                "nodes" => limits.max_nodes = ceiling,
                "collection" => limits.max_collection_items = ceiling,
                "decoded" => limits.max_decoded_value_bytes = ceiling,
                _ => unreachable!(),
            }
            let result = equivalent(limit, &signature, input.as_bytes(), limits);
            assert_eq!(result.is_ok(), ceiling >= exact, "{limit}={ceiling}");
            if let Err(error) = result {
                assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
                assert_eq!(error.message, "invocation-value-limit");
            }
        }
    }
    let input =
        format!(r#"[[{{"value":{WIDE},"case":"record"}},{{"case":"record","value":{WIDE}}}]]"#);
    for ceiling in [6299, 6300, 6301] {
        let result = equivalent(
            "two deferred payloads share the same ledger",
            &[types()["variant-list"].clone()],
            input.as_bytes(),
            ValueCodecLimits {
                max_decoded_value_bytes: ceiling,
                ..ValueCodecLimits::default()
            },
        );
        assert_eq!(result.is_ok(), ceiling >= 6300);
    }
}

#[test]
fn tagged_null_empty_and_nested_states_never_gain_defaults() {
    for (name, input) in [
        ("variant", r#"[{"case":"empty"}]"#),
        ("variant", r#"[{"value":"9","case":"number"}]"#),
        ("option", r#"[{"\u006eone":null}]"#),
        ("option", r#"[{"some":""}]"#),
        ("nested", r#"[{"some":{"none":null}}]"#),
        ("nested", r#"[{"some":{"some":"x"}}]"#),
        ("unit-result", r#"[{"ok":null}]"#),
        ("unit-result", r#"[{"\u0065rr":null}]"#),
        ("result", r#"[{"err":{"value":"42","case":"number"}}]"#),
    ] {
        equivalent(
            name,
            &[types()[name].clone()],
            input.as_bytes(),
            ValueCodecLimits::default(),
        )
        .unwrap();
    }
    for (name, input) in [
        ("variant", r#"[{"case":"empty","value":null}]"#),
        ("variant", r#"[{"case":"number"}]"#),
        ("variant", r#"[{"value":null,"case":"number"}]"#),
        ("option", "[null]"),
        ("option", r#"[{"none":false}]"#),
        ("option", r#"[{"some":null}]"#),
        ("option", r#"[{"some":"x","none":null}]"#),
        ("option", r#"[{"some":"x","\u0073ome":"y"}]"#),
        ("nested", r#"[{"some":{}}]"#),
        ("unit-result", r#"[{"err":{}}]"#),
        ("unit-result", r#"[{"ok":null,"err":null}]"#),
        ("result", r#"[{"err":null}]"#),
        ("result", r#"[{"ok":"x","\u006fk":"y"}]"#),
    ] {
        invalid(name, &[types()[name].clone()], input.as_bytes());
    }
}

#[test]
fn every_prefix_of_a_deferred_escaped_record_is_rejected_without_accepting_a_partial_value() {
    let wide = WIDE.replace(r#""name":"a""#, r#""name":"\ud83e\udd80\n\"\\""#);
    let input = format!(r#"[{{"value":{wide},"case":"record"}}]"#);
    let signature = [types()["record-variant"].clone()];
    assert!(input.len() < 512);
    equivalent(
        "complete escaped deferred record",
        &signature,
        input.as_bytes(),
        ValueCodecLimits::default(),
    )
    .unwrap();
    for end in 0..input.len() {
        invalid(
            "incomplete deferred record",
            &signature,
            &input.as_bytes()[..end],
        );
    }
}

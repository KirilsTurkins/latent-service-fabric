use super::*;

#[test]
fn exact_numeric_framing_and_unicode_share_the_legacy_contract() {
    for ty in [
        Type::U8,
        Type::U16,
        Type::U32,
        Type::S8,
        Type::S16,
        Type::S32,
    ] {
        for input in ["[0]", "[-0]", "[1]"] {
            equivalent(
                input,
                std::slice::from_ref(&ty),
                input.as_bytes(),
                ValueCodecLimits::default(),
            )
            .unwrap();
        }
        for input in [
            "[1.0]", "[1e0]", "[1E+0]", r#"["1"]"#, "[+1]", "[01]", "[null]", "[true]",
        ] {
            invalid(input, std::slice::from_ref(&ty), input.as_bytes());
        }
    }
    for (ty, boundary, outside) in [
        (Type::U8, "255", "256"),
        (Type::S8, "-128", "-129"),
        (Type::U16, "65535", "65536"),
        (Type::S16, "-32768", "-32769"),
        (Type::U32, "4294967295", "4294967296"),
        (Type::S32, "-2147483648", "-2147483649"),
    ] {
        equivalent(
            boundary,
            std::slice::from_ref(&ty),
            format!("[{boundary}]").as_bytes(),
            ValueCodecLimits::default(),
        )
        .unwrap();
        invalid(outside, &[ty], format!("[{outside}]").as_bytes());
    }
    for ty in [Type::U64, Type::S64] {
        for text in [
            "+1",
            "01",
            "-0",
            " 1",
            "1 ",
            "1e2",
            "",
            "999999999999999999999999999999",
        ] {
            invalid(
                "decimal64 rejected spelling",
                std::slice::from_ref(&ty),
                format!(r#"["{text}"]"#).as_bytes(),
            );
        }
        invalid("decimal64 needs a string", &[ty], b"[1]");
    }
}

#[test]
fn finite_float_rounding_and_specials_are_compared_without_nan_equality() {
    for ty in [Type::Float32, Type::Float64] {
        for text in [
            "0", "-0", "1e-9999", "-1e-9999", "1.25e+2", "nan", "inf", "-inf",
        ] {
            equivalent(
                "float spelling",
                std::slice::from_ref(&ty),
                format!(r#"["{text}"]"#).as_bytes(),
                ValueCodecLimits::default(),
            )
            .unwrap();
        }
        for text in [
            "NaN", "Infinity", "+inf", "+1", "01", ".1", "1.", "1e", " 1", "1e9999",
        ] {
            invalid(
                "invalid float spelling",
                std::slice::from_ref(&ty),
                format!(r#"["{text}"]"#).as_bytes(),
            );
        }
    }
    let input = br#"["1.00000005960464477539062500000000000000000000000000000000001"]"#;
    equivalent(
        "f32 midpoint",
        &[Type::Float32],
        input,
        ValueCodecLimits::default(),
    )
    .unwrap();
    let actual = decode_params(
        &[Type::Float32],
        input,
        MEDIA_TYPE,
        ValueCodecLimits::default(),
    )
    .unwrap();
    let Val::Float32(value) = actual[0] else {
        panic!("f32 result")
    };
    assert_eq!(value.to_bits(), 1.0_f32.to_bits() + 1);
    let huge = format!("[{}]", "9".repeat(1024));
    invalid(
        "bare number overflow still goes through full JSON parser",
        &[Type::Bool],
        huge.as_bytes(),
    );
}

#[test]
fn escaped_unicode_keys_and_values_preserve_decoded_utf8_limits() {
    for input in [r#"["\ud83e\udd80"]"#, "[\"\u{1f980}\"]", r#"["\u0000"]"#] {
        equivalent(
            "single scalar",
            &[Type::Char],
            input.as_bytes(),
            ValueCodecLimits::default(),
        )
        .unwrap();
    }
    for input in [
        r#"[""]"#,
        r#"["ab"]"#,
        r#"["\ud800"]"#,
        r#"["\udc00"]"#,
        r#"["\ud800\u0041"]"#,
        r#"["\uqqqq"]"#,
        r#"["\x20"]"#,
    ] {
        invalid("invalid char or escape", &[Type::Char], input.as_bytes());
    }
    for input in [r#"["\ud83e\udd80"]"#, "[\"\u{1f980}\"]"] {
        for maximum in [3, 4, 5] {
            let result = equivalent(
                "decoded UTF-8 string bytes",
                &[Type::String],
                input.as_bytes(),
                ValueCodecLimits {
                    max_string_bytes: maximum,
                    ..ValueCodecLimits::default()
                },
            );
            assert_eq!(result.is_ok(), maximum >= 4);
        }
    }
    rejected(
        "unsupported value type",
        &[Type::ErrorContext],
        b"[null]",
        ValueCodecLimits::default(),
        PlatformErrorCode::IncompatibleContract,
        "unsupported-component-value-type",
    );
}

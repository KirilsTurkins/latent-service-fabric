use super::*;

#[test]
fn scalar_widths_unicode_and_lossless_decimal64() {
    let types = [
        Type::Bool,
        Type::U8,
        Type::S8,
        Type::U16,
        Type::S16,
        Type::U32,
        Type::S32,
        Type::U64,
        Type::S64,
        Type::Char,
        Type::String,
    ];
    let json = r#"[true,255,-128,65535,-32768,4294967295,-2147483648,"18446744073709551615","-9223372036854775808","🦀","café\n"]"#;
    assert_eq!(round_trip(&types, json), json);
    let values = decode(&types, json);
    assert!(matches!(values[7], Val::U64(u64::MAX)));
    assert!(matches!(values[8], Val::S64(i64::MIN)));
    assert!(matches!(values[9], Val::Char('🦀')));
    assert_eq!(round_trip(&[], "[]"), "[]");
}

#[test]
fn every_small_integer_width_rejects_overflow_and_noninteger_tokens() {
    for (ty, invalid) in [
        (Type::U8, "256"),
        (Type::S8, "-129"),
        (Type::U16, "65536"),
        (Type::S16, "-32769"),
        (Type::U32, "4294967296"),
        (Type::S32, "-2147483649"),
    ] {
        rejects(&ty, &format!("[{invalid}]"));
        rejects(&ty, "[1.0]");
        rejects(&ty, "[1e0]");
        rejects(&ty, r#"["1"]"#);
    }
    rejects(&Type::U8, "[-1]");
    assert_eq!(round_trip(&[Type::S8], "[-0]"), "[0]");
    rejects(&Type::Bool, "[1]");
    rejects(&Type::Char, r#"[""]"#);
    rejects(&Type::Char, r#"["ab"]"#);
    rejects(&Type::Char, r#"["\ud800"]"#);
    assert_eq!(
        round_trip(&[Type::Char], r#"["\ud83e\udd80"]"#),
        r#"["🦀"]"#
    );
}

#[test]
fn decimal64_strings_have_a_single_integer_spelling() {
    for text in [
        "+1",
        "01",
        "-0",
        " 1",
        "1 ",
        "1.0",
        "1e1",
        "",
        "18446744073709551616",
    ] {
        rejects(&Type::U64, &format!(r#"["{text}"]"#));
    }
    for text in [
        "+1",
        "-01",
        "-0",
        "9223372036854775808",
        "-9223372036854775809",
    ] {
        rejects(&Type::S64, &format!(r#"["{text}"]"#));
    }
    rejects(&Type::U64, "[1]");
    rejects(&Type::S64, "[-1]");
}

#[test]
fn floating_point_round_trips_preserve_finite_bits_and_signed_zero() {
    for value in [
        0.0_f32,
        -0.0,
        f32::MIN_POSITIVE,
        f32::from_bits(1),
        f32::MAX,
        -f32::MAX,
        1.000_000_1,
    ] {
        let json = payload(
            encode_result(
                &[Type::Float32],
                &[Val::Float32(value)],
                ValueCodecLimits::default(),
            )
            .expect("encode f32"),
        );
        let Val::Float32(actual) = decode(&[Type::Float32], &json)[0] else {
            panic!("f32")
        };
        assert_eq!(actual.to_bits(), value.to_bits(), "{json}");
    }
    for value in [
        0.0_f64,
        -0.0,
        f64::MIN_POSITIVE,
        f64::from_bits(1),
        f64::MAX,
        -f64::MAX,
        1.000_000_000_000_000_2,
    ] {
        let json = payload(
            encode_result(
                &[Type::Float64],
                &[Val::Float64(value)],
                ValueCodecLimits::default(),
            )
            .expect("encode f64"),
        );
        let Val::Float64(actual) = decode(&[Type::Float64], &json)[0] else {
            panic!("f64")
        };
        assert_eq!(actual.to_bits(), value.to_bits(), "{json}");
    }
    // This decimal is slightly above the midpoint. A preliminary f64 parse
    // would round to the midpoint and then incorrectly down when cast to f32.
    let Val::Float32(value) = decode(
        &[Type::Float32],
        r#"["1.00000005960464477539062500000000000000000000000000000000001"]"#,
    )[0] else {
        panic!("f32")
    };
    assert_eq!(value.to_bits(), 1.0_f32.to_bits() + 1);
}

#[test]
fn floats_accept_explicit_special_values_and_reject_accidental_overflow() {
    for ty in [Type::Float32, Type::Float64] {
        for spelling in ["nan", "inf", "-inf", "-0"] {
            let json = format!(r#"["{spelling}"]"#);
            assert_eq!(round_trip(std::slice::from_ref(&ty), &json), json);
        }
        for spelling in [
            "NaN", "Infinity", "+inf", "+1", "01", "1.", ".1", "1e", " 1", "1e9999",
        ] {
            rejects(&ty, &format!(r#"["{spelling}"]"#));
        }
        rejects(&ty, "[1.5]");
    }
    assert_eq!(round_trip(&[Type::Float64], r#"["1.25e+2"]"#), r#"["125"]"#);
}

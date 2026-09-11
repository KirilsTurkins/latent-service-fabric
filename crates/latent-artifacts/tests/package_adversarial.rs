use latent_artifacts::package::{
    artifact_blob_digest, decode_config, encode_config, PackageLimits,
};
use latent_core::PlatformErrorCode;
use serde_json::{json, Value};

fn asset_config(paths: &[&str]) -> Value {
    let layers: Vec<_> = paths
        .iter()
        .map(|path| {
            json!({
                "path": path, "role": "asset", "mediaType": "text/plain",
                "digest": artifact_blob_digest(b"x").as_str(), "size": 1,
            })
        })
        .collect();
    json!({"formatVersion": 1, "kind": "browser-assets", "name": "example", "version": "1.0.0",
        "entrypoint": paths.first().copied().unwrap_or("empty"), "layers": layers, "annotations": {}})
}

fn wire(value: &Value) -> Vec<u8> {
    serde_json::to_vec(value).unwrap()
}

fn rejects(value: &Value) {
    assert!(
        decode_config(&wire(value), PackageLimits::default()).is_err(),
        "{value}"
    );
}

#[test]
fn portable_paths_reject_traversal_encodings_devices_and_collisions() {
    for path in [
        "",
        "/a",
        "a/",
        "a//b",
        ".",
        "..",
        "a/../b",
        "a/./b",
        "a.",
        "a\\b",
        "C:/a",
        "//host/a",
        "a%2fb",
        "a?b",
        "a#b",
        "a:b",
        "a b",
        "é",
        "CON",
        "con.txt",
        "AUX/a",
        "a/NUL",
        "Lpt9.json",
        "com1",
        "a/PRN",
        "a\0b",
    ] {
        rejects(&asset_config(&[path]));
    }
    rejects(&asset_config(&[&"a".repeat(65)]));
    rejects(&asset_config(&[&vec!["a".repeat(60); 4].join("/")]));
    for paths in [
        vec!["a", "a"],
        vec!["A", "a"],
        vec!["a", "a/b"],
        vec!["A/b", "a"],
        vec!["b", "a"],
    ] {
        rejects(&asset_config(&paths));
    }
    for path in ["a/b.txt", ".hidden", "LPT0", "com10", "under_score-1.js"] {
        decode_config(&wire(&asset_config(&[path])), PackageLimits::default()).unwrap();
    }
}

#[test]
fn closed_json_shapes_reject_duplicate_and_escaped_keys_before_typed_conversion() {
    let valid = String::from_utf8(wire(&asset_config(&["a"]))).unwrap();
    for replacement in [
        r#""name":"example","name":"other""#,
        r#""name":"example","na\u006de":"other""#,
        r#""name":"example","unknown":1"#,
    ] {
        let bad = valid.replace(r#""name":"example""#, replacement);
        assert_eq!(
            decode_config(bad.as_bytes(), PackageLimits::default())
                .unwrap_err()
                .code,
            PlatformErrorCode::InvalidArgument
        );
    }
    for replacement in [
        r#""size":1,"size":2"#,
        r#""size":-1"#,
        r#""size":1.0"#,
        r#""size":1e0"#,
        r#""size":-0"#,
        r#""size":18446744073709551616"#,
        r#""size":null"#,
        r#""size":true"#,
    ] {
        assert!(decode_config(
            valid.replace(r#""size":1"#, replacement).as_bytes(),
            PackageLimits::default()
        )
        .is_err());
    }
    for suffix in ["{}", "false", "\0", "garbage"] {
        assert!(decode_config(
            format!("{valid}{suffix}").as_bytes(),
            PackageLimits::default()
        )
        .is_err());
    }
    let nested = valid.replace(
        r#""annotations":{}"#,
        r#""annotations":{"a":"x","\u0061":"y"}"#,
    );
    assert!(decode_config(nested.as_bytes(), PackageLimits::default()).is_err());
    let mut missing = asset_config(&["a"]);
    missing.as_object_mut().unwrap().remove("annotations");
    rejects(&missing);
    missing["annotations"] = Value::Null;
    rejects(&missing);
    let mut optional = asset_config(&["a"]);
    optional["componentDigest"] = Value::Null;
    rejects(&optional);
}

#[test]
fn syntax_and_role_constraints_reject_invalid_versions_digests_and_media_types() {
    for version in [
        "1",
        "1.0",
        "v1.0.0",
        "01.0.0",
        "1.0.0-",
        "1.0.0+",
        "1.0.0-01",
        "1.0.0-a..b",
        "1.0.0+build+other",
        "1.0.0-a b",
    ] {
        let mut value = asset_config(&["a"]);
        value["version"] = json!(version);
        rejects(&value);
    }
    for version in [
        "0.0.0",
        "1.2.3-alpha.1",
        "1.2.3+001",
        "999999999999999999999999.0.0",
    ] {
        let mut value = asset_config(&["a"]);
        value["version"] = json!(version);
        decode_config(&wire(&value), PackageLimits::default()).unwrap();
    }
    for media_type in [
        "./+",
        "_/-",
        "/html",
        "text/",
        "Text/html",
        "text/html/extra",
        "text/html;charset=utf-8",
        "text/ht ml",
    ] {
        let mut value = asset_config(&["a"]);
        value["layers"][0]["mediaType"] = json!(media_type);
        rejects(&value);
    }
    for digest in [
        "sha256:x".to_owned(),
        "a".repeat(64),
        format!("sha256:{}", "A".repeat(64)),
        format!("sha512:{}", "a".repeat(64)),
        format!("sha256:{} ", "a".repeat(64)),
    ] {
        let mut value = asset_config(&["a"]);
        value["layers"][0]["digest"] = json!(digest);
        rejects(&value);
    }
}

#[test]
fn document_depth_node_string_and_collection_limits_fail_with_bounded_errors() {
    let bytes = wire(&asset_config(&["a"]));
    let defaults = PackageLimits::default();
    let limits = [
        PackageLimits {
            max_document_bytes: bytes.len() - 1,
            ..defaults
        },
        PackageLimits {
            max_depth: 2,
            ..defaults
        },
        PackageLimits {
            max_nodes: 4,
            ..defaults
        },
        PackageLimits {
            max_string_bytes: 8,
            ..defaults
        },
    ];
    for limit in limits {
        let error = decode_config(&bytes, limit).unwrap_err();
        assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
        assert!(error.message.len() < 64);
        assert!(error.details.is_empty());
    }
    decode_config(
        &bytes,
        PackageLimits {
            max_document_bytes: bytes.len(),
            ..defaults
        },
    )
    .unwrap();
    let too_many = wire(&asset_config(&["a", "b"]));
    assert_eq!(
        decode_config(
            &too_many,
            PackageLimits {
                max_layers: 1,
                ..defaults
            }
        )
        .unwrap_err()
        .code,
        PlatformErrorCode::ResourceExhausted
    );
    decode_config(
        &bytes,
        PackageLimits {
            max_layers: 1,
            ..defaults
        },
    )
    .unwrap();
    let deeply_nested = format!("{}0{}", "[".repeat(100), "]".repeat(100));
    assert_eq!(
        decode_config(deeply_nested.as_bytes(), defaults)
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    let mut annotation = asset_config(&["a"]);
    annotation["annotations"] = json!({"a":"1", "b":"2"});
    assert_eq!(
        decode_config(
            &wire(&annotation),
            PackageLimits {
                max_annotations: 1,
                ..defaults
            }
        )
        .unwrap_err()
        .code,
        PlatformErrorCode::ResourceExhausted
    );
    for invalid_limits in [
        PackageLimits {
            max_depth: 0,
            ..defaults
        },
        PackageLimits {
            max_document_bytes: defaults.max_document_bytes + 1,
            ..defaults
        },
    ] {
        assert_eq!(
            decode_config(&bytes, invalid_limits).unwrap_err().code,
            PlatformErrorCode::InvalidArgument
        );
    }
}

#[test]
fn declared_layer_and_total_budgets_are_inclusive_without_large_payload_allocation() {
    let mut value = asset_config(&["a", "b"]);
    for layer in value["layers"].as_array_mut().unwrap() {
        layer["size"] = json!(4);
    }
    let limits = PackageLimits {
        max_layer_bytes: 4,
        max_total_layer_bytes: 8,
        ..PackageLimits::default()
    };
    decode_config(&wire(&value), limits).unwrap();
    assert_eq!(
        decode_config(
            &wire(&value),
            PackageLimits {
                max_total_layer_bytes: 7,
                ..limits
            }
        )
        .unwrap_err()
        .code,
        PlatformErrorCode::ResourceExhausted
    );
    value["layers"][0]["size"] = json!(5);
    assert_eq!(
        decode_config(&wire(&value), limits).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    value["layers"][0]["size"] = json!(u64::MAX);
    rejects(&value);
    let mut empty = asset_config(&["a"]);
    empty["layers"][0]["size"] = json!(0);
    decode_config(&wire(&empty), PackageLimits::default()).unwrap();
}

#[test]
fn public_owned_models_receive_the_same_bounds_before_encoding() {
    let limits = PackageLimits::default();
    let mut model = decode_config(&wire(&asset_config(&["a"])), limits).unwrap();
    model.annotations.insert(
        "oversized".to_owned(),
        "x".repeat(limits.max_string_bytes + 1),
    );
    assert_eq!(
        encode_config(&model, limits).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    model.annotations.clear();
    model
        .annotations
        .insert("line".to_owned(), "bad\nvalue".to_owned());
    assert_eq!(
        encode_config(&model, limits).unwrap_err().code,
        PlatformErrorCode::InvalidArgument
    );
    model.annotations.clear();
    assert_eq!(
        encode_config(
            &model,
            PackageLimits {
                max_document_bytes: 8,
                ..limits
            }
        )
        .unwrap_err()
        .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(
        encode_config(
            &model,
            PackageLimits {
                max_nodes: 1,
                ..limits
            }
        )
        .unwrap_err()
        .code,
        PlatformErrorCode::ResourceExhausted
    );
    model.layers = vec![model.layers[0].clone(); limits.max_layers + 1];
    assert_eq!(
        encode_config(&model, limits).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
}

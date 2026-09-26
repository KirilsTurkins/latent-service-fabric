use super::*;
use serde_json::json;

fn reference() -> VaultReference {
    VaultReference {
        tenant: "tests".into(),
        reference: "allowed".into(),
        mount: "secret".into(),
        path: "example".into(),
        field: "value".into(),
        version: None,
        encoding: VaultEncoding::Utf8,
        media_type: "text/plain".into(),
        expires_at_unix_millis: None,
    }
}
fn response(value: &str) -> serde_json::Value {
    json!({"lease_id":"","lease_duration":0,"renewable":false,
        "data":{"data":{"value":value,"unused":{"arbitrary":"ignored"}},
        "metadata":{"version":2,"destroyed":false,"deletion_time":"","created_time":"2026-09-14T00:00:00Z","custom_metadata":null}}})
}
#[test]
fn selected_utf8_binary_exact_version_and_deleted_metadata() {
    let mut r = reference();
    let v = response("synthetic-\n\u{1f600}");
    let bytes = serde_json::to_vec(&v).unwrap();
    let value = decode(&bytes, &r, 32).unwrap();
    assert_eq!(&*value.bytes, "synthetic-\n\u{1f600}".as_bytes());
    assert_eq!(value.bytes.capacity(), 32);
    assert_eq!(value.version, 2);
    assert_eq!(value.deletion_millis, None);
    r.version = Some(1);
    assert!(matches!(
        decode(&bytes, &r, 32),
        Err(SecretError::Unavailable)
    ));
    r.version = Some(2);
    r.encoding = VaultEncoding::Base64;
    let mut v = response("AAH/");
    let value = decode(&serde_json::to_vec(&v).unwrap(), &r, 3).unwrap();
    assert_eq!(&*value.bytes, &[0, 1, 255]);
    v["data"]["metadata"]["destroyed"] = true.into();
    assert!(matches!(
        decode(&serde_json::to_vec(&v).unwrap(), &r, 3),
        Err(SecretError::NotFound)
    ));
    v["data"]["metadata"]["destroyed"] = false.into();
    v["data"]["metadata"]["deletion_time"] = "2026-09-14T00:00:00Z".into();
    assert!(decode(&serde_json::to_vec(&v).unwrap(), &r, 3)
        .unwrap()
        .deletion_millis
        .is_some());
}
#[test]
fn no_dynamic_lease_or_raw_server_error_or_nonstring_disclosure() {
    let r = reference();
    for (key, value) in [
        ("lease_id", json!("dynamic-lease")),
        ("lease_duration", json!(60)),
        ("renewable", json!(true)),
    ] {
        let mut v = response("synthetic");
        v[key] = value;
        assert!(matches!(
            decode(&serde_json::to_vec(&v).unwrap(), &r, 32),
            Err(SecretError::Unavailable)
        ));
    }
    let v = json!({"errors":["NEVER-RETURN-THIS-TOKEN-OR-DIAGNOSTIC"]});
    assert!(matches!(
        decode(&serde_json::to_vec(&v).unwrap(), &r, 32),
        Err(SecretError::Unavailable)
    ));
    let mut v = response("synthetic");
    v["data"]["data"]["value"] = json!({"nested":"data"});
    assert!(matches!(
        decode(&serde_json::to_vec(&v).unwrap(), &r, 32),
        Err(SecretError::Unavailable)
    ));
    v["data"]["data"].as_object_mut().unwrap().remove("value");
    assert!(matches!(
        decode(&serde_json::to_vec(&v).unwrap(), &r, 32),
        Err(SecretError::NotFound)
    ));
}
#[test]
fn duplicate_depth_collection_and_length_limits_are_enforced() {
    let r = reference();
    let valid = serde_json::to_string(&response("synthetic")).unwrap();
    let duplicate = valid.replace("\"version\":2", "\"version\":1,\"version\":2");
    assert!(matches!(
        decode(duplicate.as_bytes(), &r, 32),
        Err(SecretError::Unavailable)
    ));
    assert!(matches!(
        decode(valid.as_bytes(), &r, 8),
        Err(SecretError::Unavailable)
    ));
    let mut v = response("synthetic");
    v["unused"] = json!([[[[[[[[[0]]]]]]]]]);
    assert!(matches!(
        decode(&serde_json::to_vec(&v).unwrap(), &r, 32),
        Err(SecretError::Unavailable)
    ));
    v["unused"] = json!(vec![0; 65]);
    assert!(matches!(
        decode(&serde_json::to_vec(&v).unwrap(), &r, 32),
        Err(SecretError::Unavailable)
    ));
    v["unused"] = json!("x".repeat(262_145));
    assert!(matches!(
        decode(&serde_json::to_vec(&v).unwrap(), &r, 32),
        Err(SecretError::Unavailable)
    ));
}

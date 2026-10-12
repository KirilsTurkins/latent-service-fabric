use serde_json::{json, Value};

fn fixture() -> Value {
    json!({"formatVersion":1,"consent":true,"purpose":"disposable-development-tests",
        "profile":"former-http-global-values-v1"})
}

#[cfg(not(feature = "development-test-node"))]
#[test]
fn product_node_rejects_former_profile_reproduction_input() {
    let mut value: Value = serde_json::from_str(&super::document()).unwrap();
    value["developmentPreparation"] = fixture();
    assert!(serde_json::from_value::<super::NodeConfig>(value).is_err());
}

#[cfg(feature = "development-test-node")]
#[test]
fn closed_reproduction_binds_recorded_bounds_without_changing_authority_or_deadlines() {
    let (_directory, mut config) = super::config();
    let ordinary = config.derive().unwrap();
    config.engine.java_guest = true;
    config.development_preparation = Some(serde_json::from_value(fixture()).unwrap());
    let controlled = config.derive().unwrap();
    assert_eq!(controlled.wasmtime.hostcall_fuel, 2 * 1024 * 1024);
    assert_eq!(
        controlled.wasmtime.value_codec_limits.max_lifted_bytes,
        64 * 1024 * 1024
    );
    assert!(controlled.wasmtime.buffered_web_value_profile.is_none());
    assert_eq!(controlled.invocation, ordinary.invocation);
    assert_eq!(
        controlled.transport.request_timeout,
        ordinary.transport.request_timeout
    );
    assert_eq!(
        controlled.wasmtime.maximum_fuel,
        ordinary.wasmtime.maximum_fuel
    );
}

#[cfg(feature = "development-test-node")]
#[test]
fn reproduction_requires_explicit_local_consent_and_rejects_unknown_or_duplicate_fields() {
    let (_directory, mut config) = super::config();
    for (field, value) in [
        ("consent", json!(false)),
        ("formatVersion", json!(2)),
        ("purpose", json!("production")),
        ("profile", json!("arbitrary")),
    ] {
        let mut selected = fixture();
        selected[field] = value;
        config.development_preparation = Some(serde_json::from_value(selected).unwrap());
        assert!(config.derive().is_err());
    }
    config.development_preparation = Some(serde_json::from_value(fixture()).unwrap());
    config.security_profile = latent_wasmtime::ExecutionIsolationProfile::ExternalCapsule;
    assert!(config.derive().is_err());
    for input in [
        "null",
        "[]",
        r#"{"formatVersion":1,"consent":true,"consent":false,"purpose":"disposable-development-tests","profile":"former-http-global-values-v1"}"#,
    ] {
        let document =
            super::document().replacen('{', &format!("{{\"developmentPreparation\":{input},"), 1);
        assert!(serde_json::from_str::<super::NodeConfig>(&document).is_err());
    }
}

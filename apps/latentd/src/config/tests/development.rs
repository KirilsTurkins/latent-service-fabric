use serde_json::{json, Value};

fn fixture() -> Value {
    json!({"formatVersion":1,"consent":true,"purpose":"disposable-development-tests",
        "guestClock":{"monotonicNanos":"0","wallUnixMillis":"18446744073709551615"}})
}

#[cfg(not(feature = "development-test-node"))]
#[test]
fn ordinary_node_builds_reject_developer_clock_configuration() {
    let mut value: Value = serde_json::from_str(&super::document()).unwrap();
    value["developmentTest"] = fixture();
    assert!(serde_json::from_value::<super::NodeConfig>(value).is_err());
}

#[cfg(feature = "development-test-node")]
#[test]
fn guest_fixture_changes_checked_configuration_without_changing_node_deadlines() {
    let (directory, mut config) = super::config();
    let ordinary = config.derive().unwrap();
    config.development_test = Some(serde_json::from_value(fixture()).unwrap());
    let controlled = config.derive().unwrap();
    let readings = controlled.wasmtime.development_clock_readings.unwrap();
    assert_eq!(readings.monotonic_nanos, 0);
    assert_eq!(readings.wall_unix_millis, u64::MAX);
    assert_eq!(controlled.invocation, ordinary.invocation);
    assert_eq!(
        controlled.transport.request_timeout,
        ordinary.transport.request_timeout
    );
    assert_eq!(
        controlled.manager.journal.terminal_retention,
        ordinary.manager.journal.terminal_retention
    );
    assert_eq!(
        controlled.load_sample_interval,
        ordinary.load_sample_interval
    );
    // Hardware/ABI compatibility stays the same; guest fixture selection is a
    // separate checked configuration and Wasmtime preparation identity.
    assert_eq!(
        controlled.runtime_profile.as_ref(),
        ordinary.runtime_profile.as_ref()
    );
    let checked = super::super::security::check(&controlled).unwrap();
    assert!(checked.matches(&controlled));
    assert!(!checked.matches(&ordinary));
    assert_eq!(
        serde_json::to_value(checked).unwrap()["developmentGuestClock"],
        fixture()["guestClock"]
    );
    assert!(
        serde_json::to_value(super::super::security::check(&ordinary).unwrap())
            .unwrap()
            .get("developmentGuestClock")
            .is_none()
    );
    assert!(!directory.path().join("data").exists());
}

#[cfg(feature = "development-test-node")]
#[test]
fn node_fixture_objects_reject_null_arrays_duplicates_and_unknown_fields() {
    let document = super::document();
    for selected in [
        "null",
        r#"[1,true,"disposable-development-tests",{"monotonicNanos":"0","wallUnixMillis":"1"}]"#,
        r#"{"formatVersion":1,"consent":true,"purpose":"disposable-development-tests","guestClock":["0","1"]}"#,
        r#"{"formatVersion":1,"consent":true,"consent":false,"purpose":"disposable-development-tests","guestClock":{"monotonicNanos":"0","wallUnixMillis":"1"}}"#,
        r#"{"formatVersion":1,"consent":true,"purpose":"disposable-development-tests","guestClock":{"monotonicNanos":"0","wallUnixMillis":"1","wallUnixMillis":"2"}}"#,
        r#"{"formatVersion":1,"consent":true,"purpose":"disposable-development-tests","guestClock":{"monotonicNanos":"0","wallUnixMillis":"1"},"unknown":true}"#,
    ] {
        let input = document.replacen('{', &format!("{{\"developmentTest\":{selected},"), 1);
        assert!(
            serde_json::from_str::<super::NodeConfig>(&input).is_err(),
            "{selected}"
        );
    }
}

#[cfg(feature = "development-test-node")]
#[test]
fn developer_fixture_consent_values_and_profile_fail_closed() {
    for (field, value) in [
        ("formatVersion", json!(2)),
        ("consent", json!(false)),
        ("purpose", json!("production")),
    ] {
        let mut selected = fixture();
        selected[field] = value;
        let (_, mut config) = super::config();
        config.development_test = Some(serde_json::from_value(selected).unwrap());
        assert!(config.derive().is_err());
    }
    for value in [
        "",
        "00",
        "01",
        "+1",
        "-1",
        "1.0",
        " 1",
        "18446744073709551616",
    ] {
        let mut selected = fixture();
        selected["guestClock"]["wallUnixMillis"] = json!(value);
        let (_, mut config) = super::config();
        config.development_test = Some(serde_json::from_value(selected).unwrap());
        assert!(config.derive().is_err());
    }
    for value in [json!(0), json!(null), json!([]), json!(true)] {
        let mut selected = fixture();
        selected["guestClock"]["wallUnixMillis"] = value;
        assert!(serde_json::from_value::<super::super::DevelopmentTestConfig>(selected).is_err());
    }
    let (_, mut config) = super::config();
    config.development_test = Some(serde_json::from_value(fixture()).unwrap());
    config.security_profile = latent_wasmtime::ExecutionIsolationProfile::ExternalCapsule;
    assert!(config.derive().is_err());
}

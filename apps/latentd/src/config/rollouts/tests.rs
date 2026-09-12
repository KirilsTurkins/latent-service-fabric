use super::*;
use serde_json::json;

fn parsed(value: serde_json::Value) -> RolloutConfig {
    serde_json::from_value(value).unwrap()
}

#[test]
fn optional_manual_configuration_requires_audit_and_has_finite_defaults() {
    assert!(derive(None, false).unwrap().is_none());
    let config = parsed(json!({"mode":"manual"}));
    assert!(derive(Some(&config), false).is_err());
    let settings = derive(Some(&config), true).unwrap().unwrap();
    assert_eq!(settings.store.maximum_active, 16);
    assert_eq!(settings.store.maximum_rows, 256);
    assert_eq!(settings.coordinator.maximum_queued_commands, 8);
    assert_eq!(settings.coordinator.maximum_total_page_bytes, 1024 * 1024);
}

#[test]
fn configured_boundaries_reject_overflow_and_inconsistent_domains() {
    for (field, bad) in [
        ("active", 65),
        ("retained", 1025),
        ("stages", 65),
        ("receipts", 1025),
        ("metadataBytes", 33_554_433),
        ("queuedOperations", 65),
        ("queuedBytes", 4_194_305),
        ("queryOwners", 17),
    ] {
        let mut value = json!({"mode":"manual"});
        value[field] = json!(bad);
        assert!(derive(Some(&parsed(value)), true).is_err(), "{field}");
    }
    for value in [
        json!({"mode":"manual","active":2,"retained":1}),
        json!({"mode":"manual","queuedBytes":65535}),
        json!({"mode":"manual","queryOwners":0}),
    ] {
        assert!(derive(Some(&parsed(value)), true).is_err());
    }
    let settings = derive(
        Some(&parsed(json!({"mode":"manual","active":64,"retained":1024,
        "stages":64,"receipts":1024,"metadataBytes":33_554_432,"queuedOperations":64,
        "queuedBytes":4_194_304,"queryOwners":16}))),
        true,
    )
    .unwrap()
    .unwrap();
    assert_eq!(
        settings.coordinator.maximum_total_page_bytes,
        4 * 1024 * 1024
    );
}

#[test]
fn configuration_is_closed_and_null_is_not_enablement() {
    #[derive(Deserialize)]
    struct Envelope {
        #[serde(default, deserialize_with = "present")]
        rollouts: Option<RolloutConfig>,
    }
    for value in [
        json!(null),
        json!({}),
        json!({"mode":"automatic"}),
        json!({"mode":"manual","healthy":true}),
    ] {
        assert!(serde_json::from_value::<RolloutConfig>(value).is_err());
    }
    assert!(serde_json::from_str::<Envelope>("{\"rollouts\":null}").is_err());
    assert!(serde_json::from_str::<Envelope>("{}")
        .unwrap()
        .rollouts
        .is_none());
}

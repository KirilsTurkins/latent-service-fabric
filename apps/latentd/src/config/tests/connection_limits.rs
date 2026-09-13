use std::time::Duration;

use super::*;

#[test]
fn connection_deadlines_are_derived_and_validated_together() {
    let (directory, defaults) = config();
    let settings = defaults.derive().unwrap();
    assert_eq!(
        settings.transport.maximum_connection_age,
        Duration::from_secs(300)
    );
    assert_eq!(
        settings.transport.connection_drain_timeout,
        Duration::from_secs(5)
    );
    let path = directory.path().join("connection-limits.json");
    let mut value: serde_json::Value = serde_json::from_str(&document()).unwrap();
    value["limits"] = serde_json::json!({
        "unauthenticatedConnectionTimeoutMillis": 200,
        "maximumConnectionAgeMillis": 1000,
        "connectionDrainTimeoutMillis": 300,
    });
    fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
    let selected = NodeConfig::load(&path).unwrap().derive().unwrap();
    assert_eq!(
        selected.transport.unauthenticated_timeout,
        Duration::from_millis(200)
    );
    assert_eq!(
        selected.transport.maximum_connection_age,
        Duration::from_secs(1)
    );
    assert_eq!(
        selected.transport.connection_drain_timeout,
        Duration::from_millis(300)
    );

    for (key, value) in [
        ("maximumConnectionAgeMillis", 0_u64),
        ("maximumConnectionAgeMillis", 199),
        ("maximumConnectionAgeMillis", 86_400_001),
        ("connectionDrainTimeoutMillis", 0),
        ("connectionDrainTimeoutMillis", 60_001),
    ] {
        let mut candidate: serde_json::Value =
            serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        candidate["limits"][key] = value.into();
        let invalid = directory.path().join("invalid-connection-limits.json");
        fs::write(&invalid, serde_json::to_vec(&candidate).unwrap()).unwrap();
        let error = failure(NodeConfig::load(&invalid).unwrap().derive());
        assert!(error.message.contains(key), "{key}: {}", error.message);
    }
}

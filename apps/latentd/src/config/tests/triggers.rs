use super::*;
use serde_json::json;

fn installation() -> serde_json::Value {
    json!({"id":"incoming","epoch":1,"configurationFile":"incoming.json",
        "credentialDirectory":"incoming-credentials", "credentials":[
            {"tenant":"examples","reference":"pull-token","file":"pull-token"}]})
}

#[test]
fn incoming_configuration_refuses_null_unknown_plaintext_and_missing_runtime_owners() {
    let original: serde_json::Value = serde_json::from_str(&document()).unwrap();
    for input in [
        serde_json::Value::Null,
        json!({"id":"incoming","token":"DO-NOT-ECHO"}),
        {
            let mut value = installation();
            value["unknownScope"] = json!("guest");
            value
        },
    ] {
        let mut value = original.clone();
        value["transactionalTriggers"] = input;
        let error = input::decode(&serde_json::to_vec(&value).unwrap())
            .err()
            .unwrap();
        assert!(!error.message.contains("DO-NOT-ECHO"));
    }
    let mut value = original;
    value["transactionalTriggers"] = installation();
    let config = input::decode(&serde_json::to_vec(&value).unwrap()).unwrap();
    assert!(super::super::triggers::derive(&config).is_err());
    assert!(config.derive().is_err());
}

#[test]
fn empty_guest_provider_configuration_remains_refused_without_incoming_opt_in() {
    let mut value: serde_json::Value = serde_json::from_str(&document()).unwrap();
    value["budgetProfile"] = json!({"mode":"phase3"});
    value["audit"] = json!({"mode":"durable"});
    value["capabilityPolicies"] = json!({"formatVersion":1});
    value["providers"] = json!({"formatVersion":1,"bindings":[]});
    let mut config = input::decode(&serde_json::to_vec(&value).unwrap()).unwrap();
    config.credentials_from_protected_file = true;
    assert!(super::super::providers::derive(&config).is_err());
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[test]
fn protected_incoming_file_and_tenant_mapping_are_bounded_without_creating_runtime_storage() {
    use std::os::unix::fs::PermissionsExt;
    let root = tempfile::tempdir().unwrap();
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).unwrap();
    let incoming = json!({"formatVersion":1,"endpoint":{
        "peer":"127.0.0.1:4222","serverName":"localhost","allowNonPublicPeer":true},
        "publicRoots":true,"extraRoots":[],"maximumPayloadBytes":1024,"operationTimeoutMillis":1000,
        "pollIntervalMillis":10,"maximumDeliveries":3,"ackWaitMillis":3000,"redeliveryDelayMillis":100,
        "bindings":[{"id":"incoming-orders","tenant":"examples","principalSubject":"input-subscription",
            "service":"orders","contract":"example:orders/api@1.0.0","function":"submit","route":null,
            "stream":"ORDERS","consumer":"PROCESS","filterSubject":"orders.new",
            "budget":{"cpuFuel":1000,"memoryBytes":65536,"wallTimeMillis":1000,"childCalls":0,
                "outboundRequests":0,"blobReadBytes":0,"blobWriteBytes":0,"logBytes":0},
            "transaction":{"processingScope":"orders-once","namespace":"orders","incarnation":1,
                "duplicateWindowMillis":30000,"stateReadBytes":4096,"stateWriteBytes":4096,"effectCount":4,
                "qualification":{"formatVersion":1,"serverVersion":"2.14.6","streamCreated":"2026-10-06T00:00:00Z",
                    "maximumMessages":10000,"maximumBytes":67108864,"maximumAgeMillis":0,"maximumMessageBytes":16384}}}]});
    let incoming_path = root.path().join("incoming.json");
    fs::write(&incoming_path, serde_json::to_vec(&incoming).unwrap()).unwrap();
    fs::set_permissions(&incoming_path, fs::Permissions::from_mode(0o600)).unwrap();
    let mut value: serde_json::Value = serde_json::from_str(&document()).unwrap();
    value["budgetProfile"] = json!({"mode":"phase4","maximumStateReadBytes":4096,"maximumStateWriteBytes":4096,"maximumEffects":4});
    value["audit"] = json!({"mode":"durable"});
    value["capabilityPolicies"] = json!({"formatVersion":1});
    value["supplyChain"] = json!({"mode":"enforced","policyFile":"policy.json"});
    value["state"] = json!({"formatVersion":1,"configurationEpoch":1,"clockCheckpoint":root.path().join("clock"),"operations":[]});
    value["transactionalTriggers"] = installation();
    let path = root.path().join("node.json");
    fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
    let config = NodeConfig::load(&path).unwrap();
    let derived = super::super::triggers::derive(&config).unwrap().unwrap();
    assert_eq!(derived.configuration.bindings.len(), 1);
    assert!(super::super::providers::derive(&config)
        .unwrap()
        .unwrap()
        .definitions()
        .unwrap()
        .is_empty());
    assert!(!root.path().join("data").exists());
    let mut foreign = config.clone();
    foreign.transactional_triggers.as_mut().unwrap().credentials[0].tenant = "foreign".into();
    assert!(super::super::triggers::derive(&foreign).is_err());
    fs::set_permissions(&incoming_path, fs::Permissions::from_mode(0o644)).unwrap();
    assert!(super::super::triggers::derive(&config).is_err());
    fs::set_permissions(&incoming_path, fs::Permissions::from_mode(0o600)).unwrap();
    fs::write(&incoming_path, vec![b' '; 524_289]).unwrap();
    assert!(super::super::triggers::derive(&config).is_err());
    assert!(!root.path().join("data").exists());
}

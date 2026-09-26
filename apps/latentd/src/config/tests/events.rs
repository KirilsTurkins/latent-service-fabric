use serde_json::{json, Value};

fn document() -> Value {
    let mut value: Value = serde_json::from_str(&super::document()).unwrap();
    value["budgetProfile"] = json!({"mode":"phase3", "maximumOutboundRequests":8,
        "maximumBlobReadBytes":65536, "maximumBlobWriteBytes":65536});
    value["capabilityPolicies"] = json!({"formatVersion":1});
    value["audit"] = json!({"mode":"durable"});
    value["providers"] = json!({"formatVersion":1,
        "events":{"identity":{"id":"events", "tenant":"examples", "service":"event-host", "epoch":1},
            "configuration":{"formatVersion":1, "endpoint":{"serverName":"localhost", "peer":"127.0.0.1:4222", "allowNonPublicPeer":true},
                "publicRoots":false, "extraRoots":[[1,2,3]], "topics":[{"tenant":"examples", "topic":"dev.allowed",
                    "subject":"dev.allowed", "stream":"LSF_DEV", "duplicateWindowMillis":60000}],
                "idempotencyNamespace":"dev", "maximumPayloadBytes":32768, "timeoutMillis":1000},
            "credentialDirectory":"private-events", "credentialReference":"peer", "credentialFile":"token"},
        "bindings":[{"name":"events", "tenant":"examples", "consumerService":"examples/caller",
            "providerService":"event-host", "contract":"latent:events/publisher@0.2.0", "providerBinding":"dev-events"}]});
    value
}

#[test]
fn event_input_rejects_inline_secrets_ambient_auth_and_unknown_fields() {
    for field in ["token", "password", "environment", "username"] {
        let mut value = document();
        value["providers"]["events"][field] = "DO-NOT-ECHO".into();
        let error = super::input::decode(&serde_json::to_vec(&value).unwrap())
            .err()
            .unwrap();
        assert!(!error.message.contains("DO-NOT-ECHO"));
    }
}

#[test]
fn event_binding_requires_exact_tenant_and_provider_service() {
    let mut value = document();
    let config = super::input::decode(&serde_json::to_vec(&value).unwrap()).unwrap();
    assert!(config.providers.unwrap().definitions().is_ok());
    for field in ["tenant", "providerService"] {
        value["providers"]["bindings"][0][field] = "foreign".into();
        let config = super::input::decode(&serde_json::to_vec(&value).unwrap()).unwrap();
        assert!(config.providers.unwrap().definitions().is_err());
        value = document();
    }
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[test]
fn event_protected_configuration_rejects_foreign_topics_paths_and_colliding_identity() {
    use std::os::unix::fs::PermissionsExt;
    let root = tempfile::tempdir().unwrap();
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let path = root.path().join("node.json");
    for replacement in [
        None,
        Some((
            "/providers/events/configuration/topics/0/tenant",
            json!("foreign"),
        )),
        Some(("/providers/events/credentialFile", json!("../token"))),
        Some(("/providers/events/credentialDirectory", json!("../tokens"))),
        Some((
            "/providers/events/configuration/endpoint/allowNonPublicPeer",
            json!(false),
        )),
        Some((
            "/providers/events/configuration/topics/0/topic",
            json!("dev.*"),
        )),
    ] {
        let valid = replacement.is_none();
        let mut value = document();
        if let Some((pointer, replacement)) = replacement {
            *value.pointer_mut(pointer).unwrap() = replacement;
        }
        std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
        assert_eq!(
            super::NodeConfig::load(&path).unwrap().derive().is_ok(),
            valid
        );
    }
    let mut value = document();
    value["providers"]["clockMonotonic"] =
        json!({"identity":value["providers"]["events"]["identity"]});
    std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
    assert!(super::NodeConfig::load(&path).unwrap().derive().is_err());
    assert!(!root.path().join("data").exists());
}

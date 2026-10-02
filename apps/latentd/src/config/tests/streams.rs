use serde_json::{json, Value};

fn document() -> Value {
    let mut value: Value = serde_json::from_str(&super::document()).unwrap();
    value["budgetProfile"] = json!({"mode":"phase3","maximumOutboundRequests":8});
    value["capabilityPolicies"] = json!({"formatVersion":1});
    value["audit"] = json!({"mode":"durable"});
    value["providers"] = json!({"formatVersion":1,
        "outboundStreams":{"identity":{"id":"streams","tenant":"examples","service":"stream-host","epoch":1},
            "configuration":{"formatVersion":1,"profile":"lsf-outbound-streams-v1",
                "destinations":[{"endpoint":{"host":"127.0.0.1","port":32123,"transport":"tcp"},
                    "addresses":{"networks":["127.0.0.1/32"],"specialAddresses":["127.0.0.1"]},
                    "resolution":{"kind":"static","addresses":["127.0.0.1"]}}],
                "limits":{"maximumTransferBytes":65536,"idleTimeoutMillis":1000,"absoluteTimeoutMillis":5000}}},
        "bindings":[{"name":"stream-binding","tenant":"examples","consumerService":"guest-stream",
            "providerService":"stream-host","contract":"latent:network/streams@0.1.0","providerBinding":"streams-installed"}]});
    value
}

#[test]
fn stream_input_is_closed_and_never_echoes_credentials_or_host_key_paths() {
    for (pointer, invalid) in [
        ("/providers/outboundStreams", Value::Null),
        (
            "/providers/outboundStreams/identity/token",
            json!("DO-NOT-ECHO"),
        ),
        (
            "/providers/outboundStreams/credential",
            json!("DO-NOT-ECHO"),
        ),
        (
            "/providers/outboundStreams/configuration/trustRoots",
            json!("DO-NOT-ECHO"),
        ),
        (
            "/providers/outboundStreams/configuration/clientKey",
            json!("DO-NOT-ECHO"),
        ),
        (
            "/providers/outboundStreams/configuration/environment",
            json!(["DO-NOT-ECHO"]),
        ),
    ] {
        let mut value = document();
        let (parent, field) = pointer.rsplit_once('/').unwrap();
        value
            .pointer_mut(parent)
            .unwrap()
            .as_object_mut()
            .unwrap()
            .insert(field.into(), invalid);
        let error = super::input::decode(&serde_json::to_vec(&value).unwrap())
            .err()
            .unwrap();
        assert!(!error.message.contains("DO-NOT-ECHO"));
        assert!(error
            .details
            .iter()
            .all(|detail| !format!("{detail:?}").contains("DO-NOT-ECHO")));
    }
}

#[test]
fn stream_bindings_require_the_exact_installed_identity_and_contract() {
    let original = document();
    let config = super::input::decode(&serde_json::to_vec(&original).unwrap()).unwrap();
    assert_eq!(
        config
            .providers
            .as_ref()
            .unwrap()
            .definitions()
            .unwrap()
            .len(),
        1
    );
    for (field, replacement) in [
        ("tenant", "foreign"),
        ("providerService", "another-provider"),
        ("contract", "latent:http/client@0.2.0"),
    ] {
        let mut value = original.clone();
        value["providers"]["bindings"][0][field] = replacement.into();
        let config = super::input::decode(&serde_json::to_vec(&value).unwrap()).unwrap();
        assert!(config.providers.as_ref().unwrap().definitions().is_err());
    }
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[test]
fn stream_configuration_requires_protected_input_explicit_feature_and_exact_address_policy() {
    use std::os::unix::fs::PermissionsExt;
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let path = directory.path().join("node.json");
    let original = document();
    std::fs::write(&path, serde_json::to_vec(&original).unwrap()).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
    let unprotected = super::input::decode(&serde_json::to_vec(&original).unwrap()).unwrap();
    assert!(unprotected.derive().is_err());
    let result = super::NodeConfig::load(&path).unwrap().derive();
    if !cfg!(feature = "development-outbound-streams") {
        assert!(result.is_err());
        assert!(!directory.path().join("data").exists());
        return;
    }
    assert_eq!(
        result
            .unwrap()
            .providers
            .unwrap()
            .definitions()
            .unwrap()
            .len(),
        1
    );
    assert!(!directory.path().join("data").exists());
    for (pointer, invalid) in [
        ("/providers/outboundStreams/identity/epoch", json!(0)),
        (
            "/providers/outboundStreams/configuration/profile",
            json!("future-profile"),
        ),
        (
            "/providers/outboundStreams/configuration/destinations/0/endpoint/host",
            json!("127.1"),
        ),
        (
            "/providers/outboundStreams/configuration/destinations/0/endpoint/port",
            json!(0),
        ),
        (
            "/providers/outboundStreams/configuration/destinations/0/endpoint/transport",
            json!("host-tls"),
        ),
        (
            "/providers/outboundStreams/configuration/destinations/0/addresses/specialAddresses",
            json!([]),
        ),
        (
            "/providers/outboundStreams/configuration/destinations/0/resolution/addresses",
            json!(["127.0.0.2"]),
        ),
        (
            "/providers/outboundStreams/configuration/limits/maximumTransferBytes",
            json!(1_048_577),
        ),
        (
            "/providers/outboundStreams/configuration/limits/idleTimeoutMillis",
            json!(2001),
        ),
        (
            "/providers/outboundStreams/configuration/limits/absoluteTimeoutMillis",
            json!(10001),
        ),
        ("/budgetProfile", json!({"mode":"phase1"})),
    ] {
        let mut value = original.clone();
        *value.pointer_mut(pointer).unwrap() = invalid;
        std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
        assert!(
            super::NodeConfig::load(&path).unwrap().derive().is_err(),
            "accepted {pointer}"
        );
        assert!(!directory.path().join("data").exists());
    }
    for field in ["audit", "capabilityPolicies"] {
        let mut value = original.clone();
        value.as_object_mut().unwrap().remove(field);
        std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
        assert!(super::NodeConfig::load(&path).unwrap().derive().is_err());
    }
}

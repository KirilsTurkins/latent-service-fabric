use serde_json::{json, Value};

fn document() -> Value {
    let mut value: Value = serde_json::from_str(&super::document()).unwrap();
    value["budgetProfile"] = json!({"mode":"phase3","maximumOutboundRequests":8,"maximumBlobReadBytes":65536,"maximumBlobWriteBytes":65536});
    value["capabilityPolicies"] = json!({"formatVersion":1});
    value["audit"] = json!({"mode":"durable"});
    value["providers"] = json!({"formatVersion":1,
        "blob":{"identity":{"id":"blobs","tenant":"examples","service":"blob-host","epoch":1},"namespace":"workflow"},
        "bindings":[{"name":"blob-binding","tenant":"examples","consumerService":"guest-blob",
            "providerService":"blob-host","contract":"latent:blob/blob@0.2.0","providerBinding":"blob-installed"}]});
    value
}

#[test]
fn provider_input_rejects_null_unknown_and_raw_secret_fields() {
    for (pointer, invalid) in [
        ("/providers", Value::Null),
        ("/providers/blob", Value::Null),
        ("/providers/secrets", Value::Null),
        ("/providers/metrics", Value::Null),
        ("/providers/http", Value::Null),
        ("/providers/clockMonotonic", Value::Null),
        ("/providers/clockWall", Value::Null),
        ("/providers/random", Value::Null),
        ("/providers/blob/profile", json!("future-profile")),
        ("/providers/blob/identity/credential", json!("DO-NOT-ECHO")),
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
    }
}

fn secret_document() -> Value {
    let mut value = document();
    value["providers"].as_object_mut().unwrap().remove("blob");
    value["providers"]["secrets"] = json!({"identity": {"id":"secrets", "tenant":"examples",
        "service":"secret-host", "epoch":1}, "directory":"private-secrets",
        "references":[{"reference":"dev-allowed", "file":"allowed"},
            {"reference":"dev-expired", "file":"expired", "expiresAtUnixMillis":1}]});
    value["providers"]["bindings"][0]["contract"] = "latent:secrets/reader@0.1.0".into();
    value["providers"]["bindings"][0]["providerService"] = "secret-host".into();
    value
}

#[test]
fn secret_input_rejects_plaintext_environment_and_unknown_authority() {
    for (pointer, invalid) in [
        ("/providers/secrets/value", json!("DO-NOT-ECHO")),
        ("/providers/secrets/environment", json!(["HOME"])),
        (
            "/providers/secrets/references/0/value",
            json!("DO-NOT-ECHO"),
        ),
        (
            "/providers/secrets/references/0/purpose",
            json!("provider-credential"),
        ),
        (
            "/providers/secrets/references/0/expiresAtUnixMillis",
            Value::Null,
        ),
    ] {
        let mut value = secret_document();
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
    }
}

#[test]
fn secret_bindings_require_the_actual_provider_service_and_tenant() {
    let value = secret_document();
    let config = super::input::decode(&serde_json::to_vec(&value).unwrap()).unwrap();
    assert!(config.providers.as_ref().unwrap().definitions().is_ok());
    for (field, replacement) in [
        ("tenant", "foreign"),
        ("providerService", "another-provider"),
        ("contract", "latent:http/client@0.2.0"),
    ] {
        let mut value = value.clone();
        value["providers"]["bindings"][0][field] = replacement.into();
        let config = super::input::decode(&serde_json::to_vec(&value).unwrap()).unwrap();
        assert!(config.providers.as_ref().unwrap().definitions().is_err());
    }
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[test]
fn secret_paths_and_reference_limits_are_validated_without_loading_values() {
    use std::os::unix::fs::PermissionsExt;
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let path = directory.path().join("node.json");
    let original = secret_document();
    std::fs::write(&path, serde_json::to_vec(&original).unwrap()).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
    let settings = super::NodeConfig::load(&path).unwrap().derive().unwrap();
    assert_eq!(
        settings.providers.unwrap().secrets.unwrap().directory,
        directory.path().join("private-secrets")
    );
    assert!(!directory.path().join("private-secrets").exists());
    for (pointer, invalid) in [
        ("/providers/secrets/directory", json!("../elsewhere")),
        ("/providers/secrets/references/0/file", json!("../escape")),
        (
            "/providers/secrets/references/1/reference",
            json!("dev-allowed"),
        ),
        (
            "/providers/secrets/references",
            json!(vec![
                original["providers"]["secrets"]["references"][0]
                    .clone();
                9
            ]),
        ),
    ] {
        let mut value = original.clone();
        *value.pointer_mut(pointer).unwrap() = invalid;
        std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
        assert!(super::NodeConfig::load(&path).unwrap().derive().is_err());
        assert!(!directory.path().join("private-secrets").exists());
    }
}

#[test]
fn scalar_provider_definitions_require_the_exact_installed_identity_and_contract() {
    for (field, capability) in [
        ("clockMonotonic", "latent:clock/monotonic@0.1.0"),
        ("clockWall", "latent:clock/wall@0.1.0"),
        ("random", "latent:random/random@0.1.0"),
    ] {
        let mut value = document();
        value["providers"][field] = json!({"identity": {
            "id":field,"tenant":"examples","service":"runtime-host","epoch":1}});
        value["providers"]["bindings"][0]["contract"] = capability.into();
        value["providers"]["bindings"][0]["providerService"] = "runtime-host".into();
        let config = super::input::decode(&serde_json::to_vec(&value).unwrap()).unwrap();
        assert!(config.providers.as_ref().unwrap().definitions().is_ok());
        value["providers"].as_object_mut().unwrap().remove(field);
        let config = super::input::decode(&serde_json::to_vec(&value).unwrap()).unwrap();
        assert!(config.providers.as_ref().unwrap().definitions().is_err());
    }
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[test]
fn protected_provider_configuration_is_opt_in_closed_and_side_effect_free() {
    use std::os::unix::fs::PermissionsExt;
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let path = directory.path().join("node.json");
    let original = document();
    std::fs::write(&path, serde_json::to_vec(&original).unwrap()).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
    let config = super::NodeConfig::load(&path).unwrap();
    let settings = config.derive().unwrap();
    assert_eq!(settings.control_blocking_threads(), 1);
    assert_eq!(settings.providers.unwrap().definitions().unwrap().len(), 1);
    assert!(!directory.path().join("data").exists());
    let unprotected = super::input::decode(&serde_json::to_vec(&original).unwrap()).unwrap();
    assert!(unprotected.derive().is_err());
    for (pointer, replacement) in [
        ("/providers/blob/identity/id", json!("../escape")),
        ("/providers/blob/identity/epoch", json!(0)),
        ("/providers/blob/identity/tenant", json!("foreign")),
        (
            "/providers/bindings/0/contract",
            json!("latent:http/streaming-client@0.1.0"),
        ),
        (
            "/providers/bindings",
            json!(vec![original["providers"]["bindings"][0].clone(); 17]),
        ),
        ("/budgetProfile", json!({"mode":"phase1"})),
    ] {
        let mut value = original.clone();
        *value.pointer_mut(pointer).unwrap() = replacement;
        std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
        assert!(super::NodeConfig::load(&path).unwrap().derive().is_err());
        assert!(!directory.path().join("data").exists());
    }
    for field in ["audit", "capabilityPolicies"] {
        let mut value = original.clone();
        value.as_object_mut().unwrap().remove(field);
        std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
        assert!(super::NodeConfig::load(&path).unwrap().derive().is_err());
    }
    let mut combined = original;
    combined["rollouts"] = json!({"mode":"manual"});
    std::fs::write(&path, serde_json::to_vec(&combined).unwrap()).unwrap();
    let combined = super::NodeConfig::load(&path).unwrap().derive().unwrap();
    assert_eq!(combined.control_blocking_threads(), 2);
}

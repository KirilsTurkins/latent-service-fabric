use super::NodeConfig;
use serde_json::{json, Value};
use std::{fs, os::unix::fs::PermissionsExt, path::Path};

fn write(path: &Path, value: &Value) {
    fs::write(path, serde_json::to_vec(value).unwrap()).unwrap();
    fs::set_permissions(path, fs::Permissions::from_mode(0o600)).unwrap();
}

fn owner() -> (
    tempfile::TempDir,
    std::path::PathBuf,
    Value,
    super::super::StreamReloadGuard,
) {
    let directory = tempfile::tempdir().unwrap();
    fs::set_permissions(directory.path(), fs::Permissions::from_mode(0o700)).unwrap();
    let path = directory.path().join("node.json");
    let value = super::streams::document();
    write(&path, &value);
    let (config, guard) = NodeConfig::load_with_stream_reload(&path).unwrap();
    let guard = guard.unwrap();
    assert!(guard.belongs_to(config.derive().unwrap().stream_reload_binding));
    assert!(!directory.path().join("data").exists());
    (directory, path, value, guard)
}

#[test]
fn protected_epoch_and_tcp_configuration_change_preserves_exact_startup_owner() {
    let (directory, path, mut value, guard) = owner();
    value["providers"]["outboundStreams"]["identity"]["epoch"] = json!(2);
    value["providers"]["outboundStreams"]["configuration"]["limits"]["maximumTransferBytes"] =
        json!(32768);
    write(&path, &value);
    let replacement = guard.replacement().unwrap();
    assert_eq!(replacement.identity.epoch, 2);
    assert_eq!(
        replacement.configuration.limits.maximum_transfer_bytes,
        32768
    );
    assert_eq!(replacement.identity.tenant, "examples");
    assert_eq!(replacement.identity.service, "stream-host");
    assert!(!directory.path().join("data").exists());
}

#[test]
fn another_protected_file_cannot_forge_the_running_nodes_startup_binding() {
    let (_directory, path, value, guard) = owner();
    let first = NodeConfig::load_with_stream_reload(&path)
        .unwrap()
        .0
        .derive()
        .unwrap();
    let alternate = path.with_file_name("another-node.json");
    write(&alternate, &value);
    let (_, foreign) = NodeConfig::load_with_stream_reload(&alternate).unwrap();
    assert!(guard.belongs_to(first.stream_reload_binding));
    assert!(!foreign.unwrap().belongs_to(first.stream_reload_binding));
}

#[test]
fn immutable_tenant_provider_consumer_binding_and_secret_owner_fields_fail_closed() {
    let (_directory, path, original, guard) = owner();
    for (pointer, replacement) in [
        ("/nodeId", json!("other-node")),
        ("/credentials/0/token", json!("PRIVATE-DO-NOT-ECHO")),
        ("/credentials/0/tenant", json!("foreign")),
        (
            "/providers/outboundStreams/identity/id",
            json!("other-provider"),
        ),
        (
            "/providers/outboundStreams/identity/tenant",
            json!("foreign"),
        ),
        (
            "/providers/outboundStreams/identity/service",
            json!("other-service"),
        ),
        (
            "/providers/outboundStreams/configuration/destinations/0/endpoint/port",
            json!(32124),
        ),
        (
            "/providers/outboundStreams/configuration/destinations/0/resolution/addresses",
            json!(["127.0.0.2"]),
        ),
        (
            "/providers/outboundStreams/configuration/destinations/0/addresses/networks",
            json!(["127.0.0.0/24"]),
        ),
        (
            "/providers/bindings/0/consumerService",
            json!("another-consumer"),
        ),
        (
            "/providers/bindings/0/providerBinding",
            json!("another-owner"),
        ),
        ("/audit/mode", json!("disabled")),
    ] {
        let mut changed = original.clone();
        *changed.pointer_mut(pointer).unwrap() = replacement;
        write(&path, &changed);
        let error = guard.replacement().err().unwrap();
        assert!(!error.message.contains("PRIVATE-DO-NOT-ECHO"));
        assert!(error
            .details
            .iter()
            .all(|detail| !format!("{detail:?}").contains("PRIVATE-DO-NOT-ECHO")));
    }
}

#[test]
fn replacement_keeps_original_protected_mode_link_size_and_closed_type_checks() {
    let (_directory, path, original, guard) = owner();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o640)).unwrap();
    assert!(guard.replacement().is_err());
    write(&path, &original);
    let alias = path.with_file_name("alias.json");
    fs::hard_link(&path, &alias).unwrap();
    assert!(guard.replacement().is_err());
    fs::remove_file(alias).unwrap();
    let mut changed = original.clone();
    changed["providers"]["outboundStreams"]["configuration"]["clientKey"] =
        json!("PRIVATE-DO-NOT-ECHO");
    write(&path, &changed);
    assert!(guard.replacement().is_err());
    fs::write(&path, vec![b' '; 65537]).unwrap();
    assert!(guard.replacement().is_err());
}

#[test]
fn ordinary_unconfigured_node_allocates_no_reload_owner_and_input_cannot_forge_marker() {
    let directory = tempfile::tempdir().unwrap();
    fs::set_permissions(directory.path(), fs::Permissions::from_mode(0o700)).unwrap();
    let path = directory.path().join("node.json");
    let mut value: Value = serde_json::from_str(&super::document()).unwrap();
    write(&path, &value);
    let (config, guard) = NodeConfig::load_with_stream_reload(&path).unwrap();
    assert!(guard.is_none());
    assert!(config.derive().unwrap().stream_reload_binding.is_none());
    value["streamReloadBinding"] = json!(vec![0u8; 32]);
    write(&path, &value);
    assert!(NodeConfig::load_with_stream_reload(&path).is_err());
    assert!(!directory.path().join("data").exists());
}

#[test]
fn runtime_and_stream_installations_cannot_share_an_identity_or_service_owner() {
    let (directory, path, original, _guard) = owner();
    for identity in [
        json!({"id":"streams","tenant":"examples","service":"other-host","epoch":1}),
        json!({"id":"activation","tenant":"examples","service":"stream-host","epoch":1}),
    ] {
        let mut value = original.clone();
        value["providers"]["activationRuntime"] = json!({"identity":identity,
            "limits":{"tasks":8,"executors":2,"queuedWork":8,"waits":16,
                "timers":8,"results":8,"nativeOwners":8}});
        write(&path, &value);
        assert!(NodeConfig::load(&path).unwrap().derive().is_err());
        assert!(!directory.path().join("data").exists());
    }
}

#[test]
fn stream_reload_keeps_runtime_identity_epoch_and_all_seven_limits_immutable() {
    let (directory, path, mut original, _first_guard) = owner();
    original["providers"]["activationRuntime"] = json!({
        "identity":{"id":"activation","tenant":"examples","service":"runtime-host","epoch":7},
        "limits":{"tasks":8,"executors":2,"queuedWork":8,"waits":16,
            "timers":8,"results":8,"nativeOwners":8}});
    write(&path, &original);
    let (config, guard) = NodeConfig::load_with_stream_reload(&path).unwrap();
    let settings = config.derive().unwrap();
    let guard = guard.unwrap();
    assert!(guard.belongs_to(settings.stream_reload_binding));
    let mut compatible = original.clone();
    compatible["providers"]["outboundStreams"]["identity"]["epoch"] = json!(2);
    compatible["providers"]["outboundStreams"]["configuration"]["limits"]["maximumTransferBytes"] =
        json!(32768);
    write(&path, &compatible);
    assert_eq!(guard.replacement().unwrap().identity.epoch, 2);
    for (field, changed) in [
        ("id", json!("other-runtime")),
        ("tenant", json!("other")),
        ("service", json!("other-host")),
        ("epoch", json!(8)),
    ] {
        let mut value = compatible.clone();
        value["providers"]["activationRuntime"]["identity"][field] = changed;
        write(&path, &value);
        assert!(guard.replacement().is_err());
    }
    for category in [
        "tasks",
        "executors",
        "queuedWork",
        "waits",
        "timers",
        "results",
        "nativeOwners",
    ] {
        let mut value = compatible.clone();
        let limit = value["providers"]["activationRuntime"]["limits"][category]
            .as_u64()
            .unwrap();
        value["providers"]["activationRuntime"]["limits"][category] = json!(limit + 1);
        write(&path, &value);
        assert!(guard.replacement().is_err(), "{category}");
    }
    assert!(!directory.path().join("data").exists());
}

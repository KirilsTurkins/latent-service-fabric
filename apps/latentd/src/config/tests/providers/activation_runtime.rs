use serde_json::{json, Value};

fn document() -> Value {
    let mut value = super::document();
    value["providers"].as_object_mut().unwrap().remove("blob");
    value["providers"]["activationRuntime"] = json!({
        "identity":{"id":"activation","tenant":"examples","service":"runtime-host","epoch":7},
        "limits":{"tasks":8,"executors":2,"queuedWork":8,"waits":16,
            "timers":8,"results":8,"nativeOwners":8}
    });
    value["providers"]["bindings"][0]["contract"] =
        latent_core::activation_runtime::CAPABILITY.into();
    value["providers"]["bindings"][0]["providerService"] = "runtime-host".into();
    value
}

#[test]
fn runtime_bindings_do_not_follow_clock_read_permissions() {
    let original = document();
    let decode =
        |value: &Value| super::super::input::decode(&serde_json::to_vec(value).unwrap()).unwrap();
    assert_eq!(
        decode(&original)
            .providers
            .unwrap()
            .definitions()
            .unwrap()
            .len(),
        1
    );
    for (field, changed) in [
        ("contract", "latent:runtime/activation@0.2.0"),
        ("contract", "latent:clock/monotonic@0.1.0"),
        ("contract", "latent:network/streams@0.1.0"),
        ("providerService", "another-host"),
        ("tenant", "foreign"),
    ] {
        let mut value = original.clone();
        value["providers"]["bindings"][0][field] = changed.into();
        assert!(decode(&value).providers.unwrap().definitions().is_err());
    }
    let mut clock_only = original;
    clock_only["providers"]
        .as_object_mut()
        .unwrap()
        .remove("activationRuntime");
    clock_only["providers"]["clockMonotonic"] = json!({"identity":{
        "id":"clock","tenant":"examples","service":"runtime-host","epoch":7}});
    assert!(decode(&clock_only)
        .providers
        .unwrap()
        .definitions()
        .is_err());
}

#[test]
fn input_requires_explicit_finite_categories_without_authority_overrides() {
    let original = document();
    for (pointer, changed) in [
        ("/providers/activationRuntime", Value::Null),
        ("/providers/activationRuntime/limits", Value::Null),
        ("/providers/activationRuntime/limits/tasks", json!(true)),
        ("/providers/activationRuntime/limits/timers", json!(-1)),
        (
            "/providers/activationRuntime/limits/nativeOwners",
            json!(4294967296_u64),
        ),
        (
            "/providers/activationRuntime/limits/cpuFuel",
            json!(1000000),
        ),
        (
            "/providers/activationRuntime/profile",
            json!("future-profile"),
        ),
        (
            "/providers/activationRuntime/executor",
            json!("ambient-threadpool"),
        ),
        (
            "/providers/activationRuntime/grants",
            json!(["implicit-authority"]),
        ),
    ] {
        let mut value = original.clone();
        let (parent, field) = pointer.rsplit_once('/').unwrap();
        value
            .pointer_mut(parent)
            .unwrap()
            .as_object_mut()
            .unwrap()
            .insert(field.into(), changed);
        assert!(
            super::super::input::decode(&serde_json::to_vec(&value).unwrap()).is_err(),
            "{pointer}"
        );
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
        let mut value = original.clone();
        value["providers"]["activationRuntime"]["limits"]
            .as_object_mut()
            .unwrap()
            .remove(category);
        assert!(
            super::super::input::decode(&serde_json::to_vec(&value).unwrap()).is_err(),
            "{category}"
        );
    }
}

#[test]
fn runtime_configuration_digest_binds_every_category_and_keeps_epoch_separate() {
    let original = document();
    let installation = |value: &Value| {
        super::super::input::decode(&serde_json::to_vec(value).unwrap())
            .unwrap()
            .providers
            .unwrap()
            .activation_runtime
            .unwrap()
    };
    let expected = installation(&original).configuration_digest().unwrap();
    for category in [
        "tasks",
        "executors",
        "queuedWork",
        "waits",
        "timers",
        "results",
        "nativeOwners",
    ] {
        let mut value = original.clone();
        let limit = &mut value["providers"]["activationRuntime"]["limits"][category];
        *limit = json!(limit.as_u64().unwrap() + 1);
        assert_ne!(
            installation(&value).configuration_digest().unwrap(),
            expected,
            "{category}"
        );
    }
    let mut next_epoch = original;
    next_epoch["providers"]["activationRuntime"]["identity"]["epoch"] = 8.into();
    assert_eq!(
        installation(&next_epoch).configuration_digest().unwrap(),
        expected
    );
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[test]
fn protected_runtime_installation_preserves_finite_backend_limits_without_side_effects() {
    use std::os::unix::fs::PermissionsExt;
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("node.json");
    let mut original = document();
    let uncreated = directory.path().join("uncreated-data");
    original["dataDirectory"] = json!(uncreated);
    let derive = |value: &Value| {
        std::fs::write(&path, serde_json::to_vec(value).unwrap()).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
        super::super::NodeConfig::load(&path).unwrap().derive()
    };
    let settings = derive(&original).unwrap();
    let installed = settings
        .providers
        .as_ref()
        .unwrap()
        .activation_runtime
        .as_ref()
        .unwrap();
    assert_eq!(
        settings.wasmtime.activation_runtime,
        Some(installed.runtime_limits())
    );
    assert_eq!(installed.runtime_limits().total(), 58);
    assert!(!uncreated.exists());
    for (pointer, changed) in [
        ("/providers/activationRuntime/limits/tasks", json!(8193)),
        ("/providers/activationRuntime/limits/waits", json!(8184)),
        ("/providers/activationRuntime/identity/epoch", json!(0)),
        ("/providers/bindings/0/tenant", json!("foreign")),
        (
            "/providers/bindings/0/providerService",
            json!("another-host"),
        ),
    ] {
        let mut value = original.clone();
        *value.pointer_mut(pointer).unwrap() = changed;
        assert!(derive(&value).is_err(), "{pointer}");
        assert!(!uncreated.exists());
    }
    let mut zero = original.clone();
    for limit in zero["providers"]["activationRuntime"]["limits"]
        .as_object_mut()
        .unwrap()
        .values_mut()
    {
        *limit = 0.into();
    }
    assert!(derive(&zero).is_err());
    let mut duplicate = original.clone();
    duplicate["providers"]["clockMonotonic"] = json!({"identity":{
        "id":"activation","tenant":"examples","service":"clock-host","epoch":1}});
    assert!(derive(&duplicate).is_err());
    duplicate["providers"]["clockMonotonic"]["identity"]["id"] = "clock".into();
    duplicate["providers"]["clockMonotonic"]["identity"]["service"] = "runtime-host".into();
    assert!(derive(&duplicate).is_err());
    for required in ["audit", "capabilityPolicies"] {
        let mut value = original.clone();
        value.as_object_mut().unwrap().remove(required);
        assert!(derive(&value).is_err(), "{required}");
    }
    let mut disabled = super::document();
    disabled["dataDirectory"] = json!(uncreated);
    assert_eq!(derive(&disabled).unwrap().wasmtime.activation_runtime, None);
    derive(&original).unwrap();
    let mut external = super::super::NodeConfig::load(&path).unwrap();
    external.security_profile = latent_wasmtime::ExecutionIsolationProfile::ExternalCapsule;
    assert!(crate::config::providers::derive(&external).is_err());
    assert!(!uncreated.exists());
}

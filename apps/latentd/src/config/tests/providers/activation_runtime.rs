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
fn c_native_opt_in_preserves_the_old_provider_digest_and_requires_its_own_binding() {
    let original = document();
    let decode =
        |value: &Value| super::super::input::decode(&serde_json::to_vec(value).unwrap()).unwrap();
    let before = decode(&original)
        .providers
        .unwrap()
        .activation_runtime
        .unwrap();
    let mut explicit_false = original.clone();
    explicit_false["providers"]["activationRuntime"]["nativeThreads"] = false.into();
    let unchanged = decode(&explicit_false)
        .providers
        .unwrap()
        .activation_runtime
        .unwrap();
    assert_eq!(
        before.configuration_digest().unwrap(),
        unchanged.configuration_digest().unwrap()
    );
    assert!(unchanged.native_configuration_digest().is_err());
    let mut selected = original.clone();
    selected["providers"]["activationRuntime"]["nativeThreads"] = true.into();
    let native = decode(&selected)
        .providers
        .unwrap()
        .activation_runtime
        .unwrap();
    assert_ne!(
        before.configuration_digest().unwrap(),
        native.configuration_digest().unwrap()
    );
    native.native_configuration_digest().unwrap();
    let mut native_binding = original["providers"]["bindings"][0].clone();
    native_binding["name"] = "native".into();
    native_binding["contract"] = "latent:runtime-native/threads@0.1.0".into();
    selected["providers"]["bindings"]
        .as_array_mut()
        .unwrap()
        .push(native_binding.clone());
    assert_eq!(
        decode(&selected)
            .providers
            .unwrap()
            .definitions()
            .unwrap()
            .len(),
        2
    );
    explicit_false["providers"]["bindings"]
        .as_array_mut()
        .unwrap()
        .push(native_binding);
    assert!(decode(&explicit_false)
        .providers
        .unwrap()
        .definitions()
        .is_err());
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[test]
fn protected_c_profile_reaches_normal_node_settings_without_raising_any_limits() {
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
    let before = derive(&original).unwrap();
    let mut selected = original.clone();
    selected["engine"] = json!({"threadingProfile":"c-context144-sync-cooperative-v1"});
    assert!(derive(&selected).is_err());
    selected["providers"]["activationRuntime"]["nativeThreads"] = true.into();
    let settings = derive(&selected).unwrap();
    assert!(settings.wasmtime.owned_native_threads && settings.wasmtime.owned_native_stacks);
    assert_eq!(
        settings.wasmtime.native_thread_profile,
        latent_wasmtime::NativeThreadProfile::CContext144SyncCooperativeV1
    );
    assert_eq!(
        settings.wasmtime.activation_runtime,
        before.wasmtime.activation_runtime
    );
    assert_eq!(
        settings.wasmtime.maximum_memory_bytes,
        before.wasmtime.maximum_memory_bytes
    );
    assert_eq!(settings.wasmtime.maximum_fuel, before.wasmtime.maximum_fuel);
    assert_eq!(
        settings.wasmtime.prepared_cache_maximum_source_bytes,
        before.wasmtime.prepared_cache_maximum_source_bytes
    );
    assert_eq!(
        settings.wasmtime.maximum_concurrent_preparations,
        before.wasmtime.maximum_concurrent_preparations
    );
    selected.as_object_mut().unwrap().remove("engine");
    assert!(derive(&selected).is_err());
    assert!(!uncreated.exists());
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

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[test]
fn activation_owned_stack_selection_keeps_native_threads_and_provider_quotas_unchanged() {
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
    let before = derive(&original).unwrap();
    let mut selected = original.clone();
    selected["engine"] = json!({"activationStackAccounting":"activation-owned-v1"});
    let after = derive(&selected).unwrap();
    assert!(!before.wasmtime.owned_native_stacks && !before.wasmtime.owned_native_threads);
    assert!(after.wasmtime.owned_native_stacks && !after.wasmtime.owned_native_threads);
    assert_eq!(
        after.wasmtime.async_stack_bytes,
        before.wasmtime.async_stack_bytes
    );
    assert_eq!(
        after.wasmtime.maximum_memory_bytes,
        before.wasmtime.maximum_memory_bytes
    );
    assert_eq!(after.wasmtime.maximum_fuel, before.wasmtime.maximum_fuel);
    assert_eq!(
        after.wasmtime.prepared_cache_maximum_source_bytes,
        before.wasmtime.prepared_cache_maximum_source_bytes
    );
    assert_eq!(
        after.wasmtime.activation_runtime,
        before.wasmtime.activation_runtime
    );
    let installation = |settings: &super::super::NodeSettings| {
        settings
            .providers
            .as_ref()
            .unwrap()
            .activation_runtime
            .as_ref()
            .unwrap()
            .configuration_digest()
            .unwrap()
    };
    assert_eq!(installation(&after), installation(&before));
    assert!(
        !after
            .providers
            .as_ref()
            .unwrap()
            .activation_runtime
            .as_ref()
            .unwrap()
            .native_threads
    );
    selected["providers"]
        .as_object_mut()
        .unwrap()
        .remove("activationRuntime");
    assert!(derive(&selected).is_err());
    selected["providers"] = original["providers"].clone();
    selected["engine"]["allocator"] = "pooling".into();
    assert!(derive(&selected).is_err());
    assert!(!uncreated.exists());
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
            json!(4_294_967_296_u64),
        ),
        (
            "/providers/activationRuntime/limits/cpuFuel",
            json!(1_000_000),
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

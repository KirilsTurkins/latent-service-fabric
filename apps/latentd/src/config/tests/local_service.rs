use latent_manifest::BindingMode;
use serde_json::{json, Value};

fn document() -> Value {
    let mut value: Value = serde_json::from_str(&super::document()).unwrap();
    value["budgetProfile"] = json!({"mode":"phase3", "maximumOutboundRequests":8,
        "maximumBlobReadBytes":65536, "maximumBlobWriteBytes":65536});
    value["capabilityPolicies"] = json!({"formatVersion":1});
    value["audit"] = json!({"mode":"durable"});
    value["providers"] = json!({"formatVersion":1,
        "localService":{"identity":{"id":"local", "tenant":"examples", "service":"examples/callee", "epoch":1},
            "deployment":"callee", "contract":"examples:callee/api@1.0.0"},
        "bindings":[{"name":"local", "tenant":"examples", "consumerService":"examples/caller",
            "providerService":"examples/callee", "contract":"latent:service/invoke@0.1.0", "providerBinding":"dev-local"}]});
    value
}

#[test]
fn local_dispatcher_preserves_exact_provider_target_and_isolated_mode() {
    let config = super::input::decode(&serde_json::to_vec(&document()).unwrap()).unwrap();
    let definitions = config.providers.unwrap().definitions().unwrap();
    let binding = &definitions[0];
    assert_eq!(binding.manifest.mode, BindingMode::IsolatedLocal);
    assert_eq!(binding.allowed_modes, [BindingMode::IsolatedLocal]);
    assert_eq!(binding.manifest.provider.route.as_deref(), Some("callee"));
    assert_eq!(
        binding.manifest.provider.contract.0,
        "examples:callee/api@1.0.0"
    );
    assert_eq!(
        binding.manifest.consumer.contract.0,
        "latent:service/invoke@0.1.0"
    );
}

#[test]
fn local_dispatcher_rejects_foreign_scope_self_calls_and_invalid_targets() {
    for (pointer, invalid) in [
        ("/providers/bindings/0/tenant", json!("foreign")),
        (
            "/providers/bindings/0/providerService",
            json!("another-callee"),
        ),
        (
            "/providers/bindings/0/consumerService",
            json!("examples/callee"),
        ),
        ("/providers/localService/deployment", json!("")),
        ("/providers/localService/deployment", json!("x".repeat(129))),
        (
            "/providers/localService/contract",
            json!("latent:service/invoke@0.1.0"),
        ),
    ] {
        let mut value = document();
        *value.pointer_mut(pointer).unwrap() = invalid;
        let config = super::input::decode(&serde_json::to_vec(&value).unwrap()).unwrap();
        assert!(
            config.providers.unwrap().definitions().is_err(),
            "{pointer}"
        );
    }
    let mut value = document();
    value["providers"]["localService"]["publication"] = "not-a-grant".into();
    assert!(super::input::decode(&serde_json::to_vec(&value).unwrap()).is_err());
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[test]
fn local_dispatcher_protected_configuration_rejects_ambiguous_provider_identity() {
    use std::os::unix::fs::PermissionsExt;
    let root = tempfile::tempdir().unwrap();
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let path = root.path().join("node.json");
    let mut value = document();
    std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
    let settings = super::NodeConfig::load(&path).unwrap().derive().unwrap();
    let tenant = &settings.admission.tenants[&latent_core::TenantId("examples".into())];
    assert!(tenant
        .allowed_principal_kinds
        .contains(&latent_core::PrincipalKind::Service));
    assert!(tenant
        .allowed_subjects
        .contains("service:8:examples:15:examples/caller"));
    assert!(!tenant
        .allowed_subjects
        .contains("service:8:examples:15:examples/callee"));
    assert!(!tenant
        .allowed_subjects
        .contains("service:7:foreign:15:examples/caller"));
    value["providers"]["clockMonotonic"] =
        json!({"identity": value["providers"]["localService"]["identity"]});
    std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
    assert!(super::NodeConfig::load(&path).unwrap().derive().is_err());
    assert!(!root.path().join("data").exists());
}

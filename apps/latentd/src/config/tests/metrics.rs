use serde_json::{json, Value};

fn document() -> Value {
    let mut value: Value = serde_json::from_str(&super::document()).unwrap();
    value["budgetProfile"] = json!({"mode":"phase3", "maximumOutboundRequests":8,
        "maximumBlobReadBytes":65536, "maximumBlobWriteBytes":65536});
    value["capabilityPolicies"] = json!({"formatVersion":1});
    value["audit"] = json!({"mode":"durable"});
    value["providers"] = json!({"formatVersion":1,
        "metrics":{"identity":{"id":"metrics", "tenant":"examples", "service":"metrics-host", "epoch":1},
            "descriptors":[{"name":"dev.calls", "kind":"counter", "unit":"1", "labels":[], "histogramUpperBounds":[]}]},
        "bindings":[{"name":"metrics", "tenant":"examples", "consumerService":"guest",
            "providerService":"metrics-host", "contract":"latent:telemetry/custom@0.1.0", "providerBinding":"dev-metrics"}]});
    value
}

#[test]
fn metrics_contracts_require_a_matching_configured_provider() {
    let value = document();
    let config = super::input::decode(&serde_json::to_vec(&value).unwrap()).unwrap();
    assert!(config.providers.as_ref().unwrap().definitions().is_ok());
    for (field, wrong) in [
        ("providerService", "other-host"),
        ("tenant", "other-tenant"),
        ("contract", "latent:secrets/reader@0.1.0"),
    ] {
        let mut value = value.clone();
        value["providers"]["bindings"][0][field] = wrong.into();
        let config = super::input::decode(&serde_json::to_vec(&value).unwrap()).unwrap();
        assert!(config.providers.as_ref().unwrap().definitions().is_err());
    }
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[test]
fn metrics_descriptor_validation_starts_no_exporter_and_rejects_reserved_unbounded_or_ambiguous_inputs(
) {
    use std::os::unix::fs::PermissionsExt;
    let root = tempfile::tempdir().unwrap();
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let path = root.path().join("node.json");
    let value = document();
    std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
    let settings = super::NodeConfig::load(&path).unwrap().derive().unwrap();
    assert_eq!(
        settings
            .providers
            .unwrap()
            .metrics
            .unwrap()
            .descriptors
            .len(),
        1
    );
    assert!(!root.path().join("data").exists());
    for (pointer, invalid) in [
        (
            "/providers/metrics/descriptors/0/name",
            json!("latent.host.cpu"),
        ),
        (
            "/providers/metrics/descriptors/0/histogramUpperBounds",
            json!([4, 3]),
        ),
        (
            "/providers/metrics/descriptors/0/labels",
            json!([{"key":"method", "values":["GET","GET"]}]),
        ),
        (
            "/providers/metrics/descriptors",
            json!(vec![
                value["providers"]["metrics"]["descriptors"][0].clone();
                17
            ]),
        ),
    ] {
        let mut invalid_value = value.clone();
        *invalid_value.pointer_mut(pointer).unwrap() = invalid;
        std::fs::write(&path, serde_json::to_vec(&invalid_value).unwrap()).unwrap();
        assert!(super::NodeConfig::load(&path).unwrap().derive().is_err());
    }
}

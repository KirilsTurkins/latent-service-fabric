use serde_json::{json, Value};

fn document(field: &str, contract: &str) -> Value {
    let mut value = super::document();
    value["providers"].as_object_mut().unwrap().remove("blob");
    value["providers"][field] = json!({"identity": {
        "id":"original", "tenant":"examples", "service":"runtime-host", "epoch":7}});
    value["providers"]["scalarAliases"] = json!([{"source":"original", "identity":{
        "id":"foreign-scalar", "tenant":"foreign", "service":"foreign-runtime", "epoch":7}}]);
    value["providers"]["bindings"][0] = json!({"name":"foreign-binding", "tenant":"foreign",
        "consumerService":"guest-server", "providerService":"foreign-runtime",
        "contract":contract, "providerBinding":"foreign-installed"});
    value
}

fn accepted(value: &Value) -> bool {
    let Ok(config) = super::super::input::decode(&serde_json::to_vec(value).unwrap()) else {
        return false;
    };
    config.providers.unwrap().definitions().is_ok()
}

#[test]
fn aliases_are_explicit_and_keep_each_binding_in_its_exact_tenant_and_service() {
    for (field, contract) in [
        ("clockMonotonic", "latent:clock/monotonic@0.1.0"),
        ("clockWall", "latent:clock/wall@0.1.0"),
        ("random", "latent:random/random@0.1.0"),
        ("context", "latent:context/context@0.1.0"),
        ("log", "latent:log/log@0.1.0"),
    ] {
        let value = document(field, contract);
        assert!(accepted(&value), "{field}");
        for (key, changed) in [
            ("tenant", "examples"),
            ("providerService", "runtime-host"),
            ("contract", "latent:http/client@0.2.0"),
        ] {
            let mut invalid = value.clone();
            invalid["providers"]["bindings"][0][key] = changed.into();
            assert!(!accepted(&invalid), "{field}:{key}");
        }
        let mut missing = value;
        missing["providers"]
            .as_object_mut()
            .unwrap()
            .remove("scalarAliases");
        assert!(!accepted(&missing));
    }
}

#[test]
fn aliases_cannot_change_epoch_chain_sources_or_duplicate_any_identity_or_scope() {
    let original = document("context", "latent:context/context@0.1.0");
    for (pointer, changed) in [
        ("/providers/scalarAliases/0/source", json!("absent")),
        ("/providers/scalarAliases/0/source", json!("foreign-scalar")),
        ("/providers/scalarAliases/0/identity/epoch", json!(8)),
        ("/providers/scalarAliases/0/identity/id", json!("original")),
        ("/providers/scalarAliases/0/identity/id", json!("../escape")),
        ("/providers/scalarAliases/0/identity/tenant", json!("")),
    ] {
        let mut invalid = original.clone();
        *invalid.pointer_mut(pointer).unwrap() = changed;
        assert!(!accepted(&invalid), "{pointer}");
    }
    let mut duplicate = original.clone();
    let mut alias = duplicate["providers"]["scalarAliases"][0].clone();
    duplicate["providers"]["scalarAliases"]
        .as_array_mut()
        .unwrap()
        .push(alias.clone());
    assert!(!accepted(&duplicate));
    alias["identity"]["id"] = "another-id".into();
    duplicate["providers"]["scalarAliases"][1] = alias;
    assert!(!accepted(&duplicate));
    let mut original_scope = original.clone();
    original_scope["providers"]["scalarAliases"][0]["identity"]["tenant"] = "examples".into();
    original_scope["providers"]["scalarAliases"][0]["identity"]["service"] = "runtime-host".into();
    assert!(!accepted(&original_scope));
    let mut ambiguous = original.clone();
    ambiguous["providers"]["random"] = original["providers"]["context"].clone();
    assert!(!accepted(&ambiguous));
}

#[test]
fn aliases_never_supply_missing_or_stateful_implementations() {
    let original = document("context", "latent:context/context@0.1.0");
    for field in [
        "http",
        "outboundStreams",
        "httpStreaming",
        "activationRuntime",
        "blob",
        "secrets",
        "metrics",
        "localService",
        "events",
    ] {
        let mut value = super::document();
        value["providers"]["scalarAliases"] = original["providers"]["scalarAliases"].clone();
        value["providers"]["scalarAliases"][0]["source"] = field.into();
        // A real blob installation is still not an aliasable scalar.
        value["providers"]["blob"]["identity"]["id"] = field.into();
        assert!(!accepted(&value), "{field}");
    }
    let mut missing = original;
    missing["providers"]
        .as_object_mut()
        .unwrap()
        .remove("context");
    assert!(!accepted(&missing));
}

#[test]
fn aliases_preserve_original_fourteen_descriptor_slots_and_closed_input() {
    let original = document("context", "latent:context/context@0.1.0");
    let mut bounded = original.clone();
    bounded["providers"]["scalarAliases"] = json!((0..13)
        .map(|index| json!({
            "source":"original", "identity":{"id":format!("alias-{index}"),
                "tenant":format!("tenant-{index}"), "service":"runtime-host", "epoch":7}
        }))
        .collect::<Vec<_>>());
    bounded["providers"]["bindings"][0]["tenant"] = "tenant-0".into();
    bounded["providers"]["bindings"][0]["providerService"] = "runtime-host".into();
    assert!(accepted(&bounded));
    let mut extra = bounded["providers"]["scalarAliases"][0].clone();
    extra["identity"]["id"] = "extra-alias".into();
    extra["identity"]["tenant"] = "extra-tenant".into();
    bounded["providers"]["scalarAliases"]
        .as_array_mut()
        .unwrap()
        .push(extra);
    assert!(!accepted(&bounded));
    for changed in [
        Value::Null,
        json!([null]),
        json!([{"source":"original"}]),
        json!([{"source":"original","identity":original["providers"]["scalarAliases"][0]["identity"],
            "grant":"implicit"}]),
    ] {
        let mut invalid = original.clone();
        invalid["providers"]["scalarAliases"] = changed;
        assert!(!accepted(&invalid));
    }
}

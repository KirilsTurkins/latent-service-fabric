use super::config::config;
use crate::config::NodeConfig;
use serde_json::json;

#[test]
fn browser_origin_bindings_are_closed_unique_tenant_scoped_and_optional_for_native_clients() {
    let original = config();
    assert!(serde_json::from_value::<NodeConfig>(original.clone())
        .unwrap()
        .derive()
        .unwrap()
        .http
        .unwrap()
        .browser_origins
        .is_empty());
    for origins in [
        json!([{"authority":"web.example.test", "tenant":"missing"}]),
        json!([{"authority":"web.example.test:80", "tenant":"tests"}]),
        json!([{"authority":"https://web.example.test", "tenant":"tests"}]),
        json!([{"authority":"*.example.test", "tenant":"tests"}]),
        json!([{"authority":"web.example.test", "tenant":"tests"}, {"authority":"web.example.test", "tenant":"other"}]),
        json!([{"authority":"web.example.test", "tenant":"tests", "allowCredentials":true}]),
        json!(vec![
            json!({"authority":"web.example.test", "tenant":"tests"});
            33
        ]),
    ] {
        let mut changed = original.clone();
        changed["httpIngress"]["browserOrigins"] = origins;
        assert!(serde_json::from_value::<NodeConfig>(changed)
            .map_or(true, |value| value.derive().is_err()));
    }
    let mut allowed = original;
    allowed["httpIngress"]["browserOrigins"] =
        json!([{"authority":"web.example.test", "tenant":"tests"}]);
    let bindings = serde_json::from_value::<NodeConfig>(allowed)
        .unwrap()
        .derive()
        .unwrap()
        .http
        .unwrap()
        .browser_origins;
    assert_eq!(bindings.len(), 1);
    assert_eq!(bindings[0].tenant, "tests");
}

#[test]
fn public_browser_origins_are_derived_not_overridden() {
    let mut value = config();
    value["httpIngress"]["authentication"] = json!({"mode":"public-origins", "origins":[
        {"authority":"web.example.test", "subject":"public-web", "tenant":"tests"}]});
    let bindings = serde_json::from_value::<NodeConfig>(value.clone())
        .unwrap()
        .derive()
        .unwrap()
        .http
        .unwrap()
        .browser_origins;
    assert_eq!(bindings[0].authority, "web.example.test");
    assert_eq!(bindings[0].tenant, "tests");
    value["httpIngress"]["browserOrigins"] =
        json!([{"authority":"web.example.test", "tenant":"other"}]);
    assert!(serde_json::from_value::<NodeConfig>(value)
        .unwrap()
        .derive()
        .is_err());
}

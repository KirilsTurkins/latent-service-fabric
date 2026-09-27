use super::config::config;
use crate::config::NodeConfig;
use serde_json::json;

#[test]
fn public_document_navigation_is_explicit_public_tenant_scoped_and_mount_bounded() {
    let binding = json!({"authority":"web.example.test", "tenant":"tests", "mount":"/docs"});
    let mut original = config();
    original["httpIngress"]["publicDocumentNavigation"] = json!([binding.clone()]);
    assert!(serde_json::from_value::<NodeConfig>(original.clone())
        .unwrap()
        .derive()
        .is_err());
    original["httpIngress"]["authentication"] = json!({"mode":"public-origins", "origins":[
        {"authority":"web.example.test", "subject":"public-web", "tenant":"tests"}]});
    let settings = serde_json::from_value::<NodeConfig>(original.clone())
        .unwrap()
        .derive()
        .unwrap()
        .http
        .unwrap();
    let policy = &settings.public_document_navigation[0];
    for (path, matches) in [
        ("/docs", true),
        ("/docs/guide", true),
        ("/docs-other", false),
        ("/", false),
    ] {
        let target =
            latent_ingress::http::CanonicalTarget::parse(settings.scheme, "web.example.test", path)
                .unwrap();
        assert_eq!(policy.matches(&target, "tests"), matches);
        assert!(!policy.matches(&target, "foreign"));
    }
    for (field, value) in [
        ("authority", "other.example.test"),
        ("tenant", "foreign"),
        ("mount", "//docs"),
        ("mount", "/docs/"),
        ("mount", "/docs?x=1"),
        ("mount", "/_lsf"),
        ("mount", "/_lsf/assets"),
        ("extra", "unsupported"),
    ] {
        let mut changed = original.clone();
        changed["httpIngress"]["publicDocumentNavigation"][0][field] = json!(value);
        assert!(serde_json::from_value::<NodeConfig>(changed)
            .map_or(true, |node| node.derive().is_err()));
    }
    for bindings in [
        json!([binding.clone(), binding.clone()]),
        json!(vec![binding; 33]),
        json!(null),
    ] {
        let mut changed = original.clone();
        changed["httpIngress"]["publicDocumentNavigation"] = bindings;
        assert!(serde_json::from_value::<NodeConfig>(changed)
            .map_or(true, |node| node.derive().is_err()));
    }
}

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

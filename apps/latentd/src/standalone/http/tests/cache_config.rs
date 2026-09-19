use super::config::config;
use crate::config::NodeConfig;
use serde_json::{json, Value};

fn approval() -> Value {
    json!({
        "dependencyProfile": "immutable-public-v1",
        "tenant": "tests", "publication": "publication", "release": "release",
        "rendererProfile": "buffered-v1", "authority": "web.example.test", "path": "/",
        "generation": 1, "maximumAgeSeconds": 30, "vary": []
    })
}
fn approved() -> Value {
    let mut value = config();
    value["httpIngress"]["authentication"] = json!({
        "mode": "public-origins",
        "origins": [{"authority": "web.example.test", "subject": "public-web", "tenant": "tests"}]
    });
    value["httpIngress"]["responseCache"] = json!([approval()]);
    value
}
fn rejects(value: Value) -> bool {
    serde_json::from_value::<NodeConfig>(value).map_or(true, |config| config.derive().is_err())
}

#[test]
fn response_cache_defaults_off_and_requires_public_operator_approval() {
    let disabled = serde_json::from_value::<NodeConfig>(config())
        .unwrap()
        .derive()
        .unwrap();
    assert!(disabled.http.unwrap().response_cache.is_empty());
    let enabled = serde_json::from_value::<NodeConfig>(approved())
        .unwrap()
        .derive()
        .unwrap();
    assert_eq!(enabled.http.unwrap().response_cache.len(), 1);
    let mut bearer = config();
    bearer["httpIngress"]["responseCache"] = json!([approval()]);
    assert!(rejects(bearer));
    let mut value = approved();
    value["httpIngress"]["responseCache"] = Value::Null;
    assert!(rejects(value));
}

#[test]
fn response_cache_configuration_rejects_unsafe_domains_and_cross_origin_approvals() {
    for (field, changed) in [
        ("tenant", json!("other")),
        ("authority", json!("other.example.test")),
        ("authority", json!("WEB.EXAMPLE.TEST")),
        ("path", json!("/a/../b")),
        ("path", json!("/?q=1")),
        ("generation", json!(0)),
        ("maximumAgeSeconds", json!(0)),
        ("maximumAgeSeconds", json!(61)),
        ("rendererProfile", json!("unknown")),
        ("dependencyProfile", json!("secret-dependent-v1")),
        ("unknown", json!(true)),
        ("vary", json!([{"name": "cookie", "values": ["session"]}])),
        ("vary", json!([{"name": "accept", "values": []}])),
        ("vary", json!([{"name": "accept", "values": ["x", "x"]}])),
    ] {
        let mut value = approved();
        value["httpIngress"]["responseCache"][0][field] = changed;
        assert!(rejects(value), "{field}");
    }
    let mut value = approved();
    value["httpIngress"]["responseCache"] = json!([approval(), approval()]);
    assert!(rejects(value));
    let mut value = approved();
    value["httpIngress"]["responseCache"] = json!(vec![approval(); 33]);
    assert!(rejects(value));
}

use super::*;
use serde_json::json;

#[test]
fn renderer_opt_in_is_closed_and_preserves_operator_budgets() {
    let (_directory, mut config) = config();
    let original = config.clone().derive().unwrap();
    assert!(!original.wasmtime.angular_renderer);
    config.renderer_profile = Some(latent_manifest::RendererProfile::AngularSsrComponentV1);
    assert!(
        config.clone().derive().is_err(),
        "buffered renderer requires explicit payload capacity"
    );
    config.limits.maximum_payload_bytes = 2 * MIB;
    let renderer = config.clone().derive().unwrap();
    assert!(renderer.wasmtime.angular_renderer);
    assert_eq!(
        renderer.wasmtime.maximum_memory_bytes,
        original.wasmtime.maximum_memory_bytes
    );
    assert_eq!(
        renderer.wasmtime.maximum_fuel,
        original.wasmtime.maximum_fuel
    );
    assert_eq!(
        renderer.wasmtime.maximum_component_bytes,
        original.wasmtime.maximum_component_bytes
    );
    config.engine.allocator = crate::config::EngineAllocator::Pooling;
    assert!(config.derive().is_err());
    let original: serde_json::Value = serde_json::from_str(&document()).unwrap();
    for value in [
        json!(null),
        json!("node"),
        json!("wasm-web-buffered-v1"),
        json!({}),
    ] {
        let mut invalid = original.clone();
        invalid["rendererProfile"] = value;
        assert!(serde_json::from_value::<NodeConfig>(invalid).is_err());
    }
}

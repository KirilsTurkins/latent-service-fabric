//! Independent WIT-derived type checks for the maintained HTTP codec goldens.
use super::*;
use base64::{engine::general_purpose::STANDARD, Engine as _};
use wasm_encoder::{
    Component as EncodedComponent, ComponentImportSection, ComponentTypeRef, ComponentTypeSection,
};
#[path = "../../../../latent-packaging/tests/fixtures/host.rs"]
mod fixture;

fn signature() -> (Vec<Type>, Vec<Type>) {
    let source = include_str!("../../../../../wit/platform/web/package.wit");
    // The source interface is self-contained; the world separately imports the
    // trusted context, covered by the generated host/guest binding build.
    let source = source.split("\nworld application-service").next().unwrap();
    let interface = fixture::interface(source, "latent:web/application@0.1.0", None);
    let mut types = ComponentTypeSection::new();
    types.instance(&interface);
    let mut imports = ComponentImportSection::new();
    imports.import(
        "latent:web/application@0.1.0",
        ComponentTypeRef::Instance(0),
    );
    let mut bytes = EncodedComponent::new();
    bytes.section(&types).section(&imports);
    let mut config = Config::new();
    config.wasm_component_model_async(true);
    let engine = Engine::new(&config).unwrap();
    let component = Component::new(&engine, bytes.finish()).unwrap();
    let component_type = component.component_type();
    let (_, import) = component_type.imports(&engine).next().unwrap();
    let ComponentItem::ComponentInstance(interface) = import.ty else {
        panic!("interface");
    };
    let function = interface
        .exports(&engine)
        .find_map(|(name, item)| {
            if name != "handle" {
                return None;
            }
            let ComponentItem::ComponentFunc(function) = item.ty else {
                panic!("function");
            };
            Some(function)
        })
        .unwrap();
    assert!(function.async_());
    (
        function.params().map(|(_, ty)| ty).collect(),
        function.results().collect(),
    )
}

fn limits() -> ValueCodecLimits {
    ValueCodecLimits {
        max_input_bytes: 2 * 1024 * 1024,
        max_output_bytes: 2 * 1024 * 1024,
        max_nodes: 32_768,
        max_collection_items: 4096,
        max_string_bytes: 512 * 1024,
        max_lifted_bytes: 64 * 1024 * 1024,
        ..ValueCodecLimits::default()
    }
}

#[test]
fn buffered_http_goldens_round_trip_through_the_actual_wit_type_plan() {
    let (params, results) = signature();
    for (types, bytes) in [
        (
            &params,
            include_str!("../../../../latent-ingress/tests/fixtures/http-request-v1.json"),
        ),
        (
            &results,
            include_str!("../../../../latent-ingress/tests/fixtures/http-response-v1.json"),
        ),
    ] {
        validate_signature(types, limits(), 2 * 1024 * 1024).unwrap();
        let values = decode_params(types, bytes.trim().as_bytes(), MEDIA_TYPE, limits()).unwrap();
        assert_eq!(
            payload(encode_result(types, &values, limits()).unwrap()),
            bytes.trim()
        );
    }
    let forged = include_str!("../../../../latent-ingress/tests/fixtures/http-request-v1.json")
        .replace("\"profile\":", "\"principal\":\"admin\",\"profile\":");
    assert!(decode_params(&params, forged.as_bytes(), MEDIA_TYPE, limits()).is_err());
}

#[test]
fn buffered_http_maximum_body_fits_explicit_codec_profile_without_raising_global_defaults() {
    let (_, results) = signature();
    let mut value: serde_json::Value = serde_json::from_str(include_str!(
        "../../../../latent-ingress/tests/fixtures/http-response-v1.json"
    ))
    .unwrap();
    value[0]["body-base64"] = serde_json::json!(STANDARD.encode(vec![255u8; 256 * 1024]));
    let bytes = serde_json::to_vec(&value).unwrap();
    assert!(decode_params(&results, &bytes, MEDIA_TYPE, ValueCodecLimits::default()).is_err());
    let decoded = decode_params(&results, &bytes, MEDIA_TYPE, limits()).unwrap();
    let encoded = payload(encode_result(&results, &decoded, limits()).unwrap());
    assert_eq!(
        serde_json::from_str::<serde_json::Value>(&encoded).unwrap(),
        value
    );
}

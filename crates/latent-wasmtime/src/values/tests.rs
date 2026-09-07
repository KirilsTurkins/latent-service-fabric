use std::collections::BTreeMap;
use std::sync::OnceLock;

use wasmtime::component::{types::ComponentItem, Component};
use wasmtime::{Config, Engine};

use super::*;

mod bounds;
mod composites;
mod scalars;

fn types() -> &'static BTreeMap<String, Type> {
    static TYPES: OnceLock<BTreeMap<String, Type>> = OnceLock::new();
    TYPES.get_or_init(|| {
        let mut config = Config::new();
        config.wasm_component_model(true);
        let engine = Engine::new(&config).expect("test engine");
        let component =
            Component::new(&engine, include_bytes!("types.wasm")).expect("type fixture");
        component
            .component_type()
            .exports(&engine)
            .map(|(name, export)| {
                let ComponentItem::Type(ty) = export.ty else {
                    panic!("type export expected")
                };
                (name.to_owned(), ty)
            })
            .collect()
    })
}

fn decode(types: &[Type], json: &str) -> Vec<Val> {
    decode_params(
        types,
        json.as_bytes(),
        MEDIA_TYPE,
        ValueCodecLimits::default(),
    )
    .expect("valid values")
}

fn payload(result: EncodedResult) -> String {
    let bytes = match result {
        EncodedResult::Returned(bytes) => bytes,
        EncodedResult::DeclaredError(error) => error.payload,
    };
    String::from_utf8(bytes).expect("JSON is UTF-8")
}

fn round_trip(types: &[Type], json: &str) -> String {
    payload(
        encode_result(types, &decode(types, json), ValueCodecLimits::default())
            .expect("encode values"),
    )
}

fn rejects(ty: &Type, json: &str) {
    let error = decode_params(
        std::slice::from_ref(ty),
        json.as_bytes(),
        MEDIA_TYPE,
        ValueCodecLimits::default(),
    )
    .expect_err("invalid input");
    assert_eq!(error.code, PlatformErrorCode::InvalidArgument, "{json}");
}

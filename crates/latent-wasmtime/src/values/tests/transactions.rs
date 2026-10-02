//! Actual engine reflection and preparation plans, independent of guest builds.
use super::*;
use std::io::Write as _;
use wasm_encoder::{
    Component as EncodedComponent, ComponentImportSection, ComponentTypeRef, ComponentTypeSection,
};
use wasmtime::component::ResourceType;

#[path = "../../../../latent-packaging/tests/fixtures/host.rs"]
mod fixture;

const STATE: &str = "latent:state/key-value@0.2.0";
const INTENTS: &str = "latent:intents/staging@0.1.0";
const SOURCES: &[(&str, &str)] = &[
    (
        "state.wit",
        include_str!("../../../../../wit/platform/state/package.wit"),
    ),
    (
        "intents.wit",
        include_str!("../../../../../wit/platform/intents/package.wit"),
    ),
];

fn limits() -> ValueCodecLimits {
    // This is the existing explicit HTTP-enabled profile, including the #708
    // lifting ledger. Neither the default nor these allowances are increased.
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

fn reflected(sources: &[(&str, &str)], name: &str) -> (Engine, Component) {
    let instance = fixture::interface_with_dependencies(sources, name, None);
    let mut types = ComponentTypeSection::new();
    types.instance(&instance);
    let mut imports = ComponentImportSection::new();
    imports.import(name, ComponentTypeRef::Instance(0));
    let mut bytes = EncodedComponent::new();
    bytes.section(&types).section(&imports);
    let mut config = Config::new();
    config.wasm_component_model_async(true);
    let engine = Engine::new(&config).expect("HTTP preparation engine");
    let component = Component::new(&engine, bytes.finish()).expect("actual WIT import fixture");
    (engine, component)
}

#[test]
fn transaction_owned_signatures_fit_the_existing_http_preparation_profile() {
    let mut records = vec![];
    let mut operations = 0;
    let mut asynchronous = 0;
    for name in [STATE, INTENTS] {
        let (engine, component) = reflected(SOURCES, name);
        let import = component
            .component_type()
            .get_import(&engine, name)
            .unwrap()
            .ty;
        let ComponentItem::ComponentInstance(interface) = import else {
            panic!("interface");
        };
        let resources: Vec<ResourceType> = interface
            .exports(&engine)
            .filter_map(|(_, item)| {
                if let ComponentItem::Resource(resource) = item.ty {
                    Some(resource)
                } else {
                    None
                }
            })
            .collect();
        assert!(
            !resources.is_empty(),
            "imported state owner reuse must survive reflection"
        );
        for (operation, item) in interface.exports(&engine) {
            let ComponentItem::ComponentFunc(function) = item.ty else {
                continue;
            };
            operations += 1;
            asynchronous += usize::from(function.async_());
            let params: Vec<Type> = function.params().map(|(_, ty)| ty).collect();
            let results: Vec<Type> = function.results().collect();
            for (direction, types) in [("params", params), ("results", results)] {
                let plan = validate_host_signature(&types, limits(), 2 * 1024 * 1024, &resources)
                    .unwrap_or_else(|error| panic!("{name}/{operation}/{direction}: {error:?}"));
                assert!(plan.examined_type_nodes <= 4096);
                assert!(plan.maximum_lift_bytes <= 64 * 1024 * 1024);
                records.push(serde_json::json!({ "interface": name, "operation": operation, "direction": direction,
                    "asynchronous": function.async_(), "examinedTypeNodes": plan.examined_type_nodes,
                    "staticLiftBytes": plan.static_lift_bytes, "perFuelLiftMultiplier": plan.per_fuel_lift_multiplier,
                    "maximumLiftBytes": plan.maximum_lift_bytes }));
            }
        }
    }
    assert_eq!(operations, 13);
    assert_eq!(asynchronous, 8);
    if let Some(path) = std::env::var_os("LSF_TRANSACTION_PREPARATION_REPORT") {
        let profile: serde_json::Value = serde_json::from_str(include_str!(
            "../../../../../sdk/profile/transaction-preparation-v1.json"
        ))
        .unwrap();
        let report = serde_json::json!({ "schemaVersion": "latent.transaction-contract.preparation.v1",
            "evidenceKind": "engine-type-plan", "preparationQualified": true, "runtimeExecutionQualified": false,
            "engineVersion": "48.0.3", "profile": profile, "operations": operations, "asynchronous": asynchronous,
            "plans": records });
        let bytes = serde_json::to_vec_pretty(&report).unwrap();
        assert!(bytes.len() <= 32 * 1024);
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path)
            .unwrap();
        file.write_all(&bytes).unwrap();
    }
}

#[test]
fn transaction_resources_need_an_explicit_allowlist_and_nested_pages_reject() {
    let (engine, component) = reflected(SOURCES, STATE);
    let ComponentItem::ComponentInstance(interface) = component
        .component_type()
        .get_import(&engine, STATE)
        .unwrap()
        .ty
    else {
        panic!("interface");
    };
    let ComponentItem::ComponentFunc(acquire) =
        interface.get_export(&engine, "acquire-command").unwrap().ty
    else {
        panic!("function");
    };
    let results: Vec<_> = acquire.results().collect();
    assert_eq!(
        validate_signature(&results, limits(), 2 * 1024 * 1024)
            .unwrap_err()
            .code,
        PlatformErrorCode::IncompatibleContract
    );
    let amplifier = "package tests:transaction-amplification@1.0.0; interface probe {
        use latent:state/key-value@0.2.0.{entry}; entries: func() -> list<entry>; }";
    let (engine, component) = reflected(
        &[SOURCES[0], ("amplification.wit", amplifier)],
        "tests:transaction-amplification/probe@1.0.0",
    );
    let ComponentItem::ComponentInstance(interface) = component
        .component_type()
        .imports(&engine)
        .next()
        .unwrap()
        .1
        .ty
    else {
        panic!("interface");
    };
    let ComponentItem::ComponentFunc(entries) =
        interface.get_export(&engine, "entries").unwrap().ty
    else {
        panic!("function");
    };
    let results: Vec<_> = entries.results().collect();
    assert_eq!(
        validate_signature(&results, limits(), 2 * 1024 * 1024)
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
}

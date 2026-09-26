use std::collections::BTreeMap;

use super::lookup_function;

#[test]
fn borrowed_lookup_preserves_exact_contract_and_function_identity_order() {
    let registered: BTreeMap<_, _> = [
        (("b".to_owned(), "identify".to_owned()), 22),
        (("a".to_owned(), "identify".to_owned()), 11),
        (("a".to_owned(), "function-id".to_owned()), 7),
        (("a/b".to_owned(), "c".to_owned()), 33),
        (("a".to_owned(), "b/c".to_owned()), 44),
    ]
    .into();
    let ordered = registered.into_iter().collect::<Vec<_>>();
    for ((contract, function), expected) in &ordered {
        let actual = lookup_function(&ordered, contract, function).unwrap();
        assert!(std::ptr::eq(actual, expected));
    }
    assert_eq!(lookup_function(&ordered, "a", "identify"), Some(&11));
    assert_eq!(lookup_function(&ordered, "b", "identify"), Some(&22));
    assert_eq!(lookup_function(&ordered, "a", "function-id"), Some(&7));
    assert_eq!(lookup_function(&ordered, "a", "exported-name"), None);
    for (contract, function) in [
        ("", "identify"),
        ("a", ""),
        ("c", "identify"),
        ("a", "identifz"),
    ] {
        assert_eq!(lookup_function(&ordered, contract, function), None);
    }
    assert_eq!(lookup_function::<u8>(&[], "a", "identify"), None);
}

#[test]
fn selected_async_signature_planning_keeps_exact_kind_and_type_work_bounds() {
    use wasm_encoder::{
        Component, ComponentImportSection, ComponentTypeRef, ComponentTypeSection, InstanceType,
        PrimitiveValType,
    };
    use wasmtime::component::types::ComponentItem;
    let policy = crate::WasmtimeConfig::default();
    let mut configuration = wasmtime::Config::new();
    policy.apply_engine(&mut configuration).unwrap();
    let engine = wasmtime::Engine::new(&configuration).unwrap();
    for asynchronous in [false, true] {
        let mut host = InstanceType::new();
        host.ty()
            .function()
            .async_(asynchronous)
            .params([("request", PrimitiveValType::U32)])
            .result(Some(PrimitiveValType::U32.into()));
        host.export("send", ComponentTypeRef::Func(0));
        let mut types = ComponentTypeSection::new();
        types.instance(&host);
        let mut imports = ComponentImportSection::new();
        imports.import("tests:signature/api@1.0.0", ComponentTypeRef::Instance(0));
        let mut bytes = Component::new();
        bytes.section(&types).section(&imports);
        let component = wasmtime::component::Component::new(&engine, bytes.finish()).unwrap();
        let component_type = component.component_type();
        let (_, item) = component_type.imports(&engine).next().unwrap();
        let ComponentItem::ComponentInstance(interface) = item.ty else {
            panic!("interface")
        };
        let (_, item) = interface.exports(&engine).next().unwrap();
        let ComponentItem::ComponentFunc(function) = item.ty else {
            panic!("function")
        };
        super::signature(&function, asynchronous, &policy, &mut 16).unwrap();
        assert_eq!(
            super::signature(&function, !asynchronous, &policy, &mut 16)
                .unwrap_err()
                .code,
            latent_core::PlatformErrorCode::IncompatibleContract
        );
        assert_eq!(
            super::signature(&function, asynchronous, &policy, &mut 0)
                .unwrap_err()
                .code,
            latent_core::PlatformErrorCode::ResourceExhausted
        );
    }
}

use std::collections::BTreeMap;

use super::lookup_function;

#[test]
fn structural_imports_link_without_authority_and_reject_calls_resources_and_work_exhaustion() {
    use wasm_encoder::{
        Component, ComponentImportSection, ComponentTypeRef, ComponentTypeSection, InstanceType,
        PrimitiveValType, TypeBounds,
    };
    use wasmtime::component::types::ComponentItem;
    let policy = crate::WasmtimeConfig::default();
    let mut configuration = wasmtime::Config::new();
    policy.apply_engine(&mut configuration).unwrap();
    let engine = wasmtime::Engine::new(&configuration).unwrap();
    for extra in ["none", "call", "resource"] {
        let mut interface = InstanceType::new();
        interface
            .ty()
            .defined_type()
            .primitive(PrimitiveValType::String);
        interface.export("value", ComponentTypeRef::Type(TypeBounds::Eq(0)));
        match extra {
            "call" => {
                let index = interface.type_count();
                interface
                    .ty()
                    .function()
                    .params([] as [(&str, PrimitiveValType); 0])
                    .result(None);
                interface.export("hidden", ComponentTypeRef::Func(index));
            }
            "resource" => {
                interface.export("authority", ComponentTypeRef::Type(TypeBounds::SubResource));
            }
            _ => {}
        }
        let mut types = ComponentTypeSection::new();
        types.instance(&interface);
        let mut imports = ComponentImportSection::new();
        let name = "example:values/types@1.0.0";
        imports.import(name, ComponentTypeRef::Instance(0));
        let mut encoded = Component::new();
        encoded.section(&types).section(&imports);
        let component = wasmtime::component::Component::new(&engine, encoded.finish()).unwrap();
        let component_type = component.component_type();
        let (_, item) = component_type.imports(&engine).next().unwrap();
        let ComponentItem::ComponentInstance(interface) = item.ty else {
            panic!("interface")
        };
        let validated = super::validate_type_interface(&interface, &engine, &policy, &mut 64);
        if extra == "none" {
            validated.unwrap();
            assert_eq!(
                super::validate_type_interface(&interface, &engine, &policy, &mut 0)
                    .unwrap_err()
                    .code,
                latent_core::PlatformErrorCode::ResourceExhausted
            );
            let mut linker = wasmtime::component::Linker::<()>::new(&engine);
            linker.instance(name).unwrap();
            linker.instantiate_pre(&component).unwrap();
        } else {
            assert_eq!(
                validated.unwrap_err().code,
                latent_core::PlatformErrorCode::IncompatibleContract
            );
        }
    }
}

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

#[test]
#[expect(
    clippy::too_many_lines,
    reason = "Finite encoded nominal-owner and negative admission shapes remain together."
)]
fn phase_type_owner_requires_selected_installed_phase_and_never_supplies_legacy_calls() {
    use wasm_encoder::{
        Alias, Component, ComponentImportSection, ComponentOuterAliasKind, ComponentTypeRef,
        ComponentTypeSection, InstanceType, PrimitiveValType, TypeBounds,
    };
    use wasmtime::component::types::ComponentItem;
    let selected = latent_capabilities::broker::streaming_http::PHASE_TIMING_CAPABILITY;
    let original = latent_capabilities::broker::streaming_http::STREAMING_HTTP_CAPABILITY;
    let mut config = wasmtime::Config::new();
    crate::WasmtimeConfig::default()
        .apply_engine(&mut config)
        .unwrap();
    let engine = wasmtime::Engine::new(&config).unwrap();
    for extra in ["none", "call", "nested", "phase-absent"] {
        let mut owner = InstanceType::new();
        for name in ["upload", "body", "chunk"] {
            owner.export(name, ComponentTypeRef::Type(TypeBounds::SubResource));
        }
        if extra == "call" {
            let index = owner.type_count();
            owner
                .ty()
                .function()
                .params([] as [(&str, PrimitiveValType); 0])
                .result(None);
            owner.export("open", ComponentTypeRef::Func(index));
        } else if extra == "nested" {
            let index = owner.type_count();
            owner.ty().instance(&InstanceType::new());
            owner.export("hidden", ComponentTypeRef::Instance(index));
        }
        let mut types = ComponentTypeSection::new();
        types.instance(&owner);
        let mut imports = ComponentImportSection::new();
        imports.import(original, ComponentTypeRef::Instance(0));
        let mut encoded = Component::new();
        encoded.section(&types).section(&imports);
        if extra != "phase-absent" {
            let mut aliases = wasm_encoder::ComponentAliasSection::new();
            for name in ["upload", "body", "chunk"] {
                aliases.alias(Alias::InstanceExport {
                    instance: 0,
                    kind: wasm_encoder::ComponentExportKind::Type,
                    name,
                });
            }
            encoded.section(&aliases);
            let mut phases = InstanceType::new();
            for (outer, name) in [(1, "upload"), (2, "body"), (3, "chunk")] {
                let index = phases.type_count();
                phases.alias(Alias::Outer {
                    kind: ComponentOuterAliasKind::Type,
                    count: 1,
                    index: outer,
                });
                phases.export(name, ComponentTypeRef::Type(TypeBounds::Eq(index)));
            }
            let mut types = ComponentTypeSection::new();
            types.instance(&phases);
            let mut imports = ComponentImportSection::new();
            imports.import(selected, ComponentTypeRef::Instance(4));
            encoded.section(&types).section(&imports);
        }
        let component = wasmtime::component::Component::new(&engine, encoded.finish()).unwrap();
        let component_type = component.component_type();
        let (_, item) = component_type
            .imports(&engine)
            .find(|(name, _)| *name == original)
            .unwrap();
        let ComponentItem::ComponentInstance(interface) = item.ty else {
            panic!("instance")
        };
        super::streaming::validate_phase_aliases(&component_type, &engine).unwrap();
        for (enabled, installed) in [(false, false), (false, true), (true, false), (true, true)] {
            assert_eq!(
                super::streaming::phase_type_owner(
                    &component_type,
                    original,
                    &interface,
                    &engine,
                    enabled,
                    installed
                ),
                extra == "none" && enabled && installed
            );
        }
        assert!(!super::streaming::phase_type_owner(
            &component_type,
            "example:unrelated/types@1.0.0",
            &interface,
            &engine,
            true,
            true
        ));
        assert!(!super::Providers {
            phase_http: true,
            ..super::Providers::default()
        }
        .supports(original));
        assert!(super::Providers {
            streaming_http: true,
            ..super::Providers::default()
        }
        .supports(original));
    }
}

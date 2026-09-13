use super::*;
#[path = "../../../tests/fixtures/component.rs"]
mod fixtures;
use fixtures::{component, Options};
use latent_core::PlatformErrorCode;
use wasm_encoder::{Component, Encode, ModuleSection, RawSection};

#[test]
fn small_real_nested_types_and_clock_import_validate_without_execution() {
    let bytes = component(Options::default());
    assert!(bytes.len() < 512);
    validate(&bytes, SemanticLimits::default()).unwrap();
}

#[test]
fn all_core_bodies_are_validated_including_unused_modules() {
    for options in [
        Options {
            invalid_body: true,
            ..Options::default()
        },
        Options {
            invalid_unused_body: true,
            ..Options::default()
        },
    ] {
        let bytes = component(options);
        // Parsing payloads alone does not catch this same-signature stack error.
        assert!(Parser::new(0)
            .parse_all(&bytes)
            .all(|payload| payload.is_ok()));
        assert!(validate(&bytes, SemanticLimits::default()).is_err());
    }
    assert!(validate(&fixtures::core(false).finish(), SemanticLimits::default()).is_err());
}

#[test]
fn bounded_vectors_and_recursive_types_fail_before_validation() {
    let limits = SemanticLimits::default();
    let mut oversized = vec![];
    u32::MAX.encode(&mut oversized);
    let mut root = Component::new();
    root.section(&RawSection {
        id: 7,
        data: &oversized,
    });
    assert_eq!(
        validate(&root.finish(), limits).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );

    // One outer item recursively embeds instance type declarations. This must
    // be stopped before wasmparser constructs its recursive boxed type tree.
    let mut nested = vec![1];
    for _ in 0..=limits.max_type_depth {
        nested.extend_from_slice(&[0x42, 1, 1]);
    }
    nested.extend_from_slice(&[0x42, 0]);
    let mut root = Component::new();
    root.section(&RawSection {
        id: 7,
        data: &nested,
    });
    assert_eq!(
        validate(&root.finish(), limits).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );

    // A tiny malformed recursive group declares a huge vector without bytes.
    let mut types = vec![1, 0x4e];
    u32::MAX.encode(&mut types);
    let mut module = wasm_encoder::Module::new();
    module.section(&RawSection {
        id: 1,
        data: &types,
    });
    let mut root = Component::new();
    root.section(&ModuleSection(&module));
    assert_eq!(
        validate(&root.finish(), limits).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
}

#[test]
fn lowered_limits_and_truncated_nested_extents_are_rejected() {
    let bytes = component(Options::default());
    for limits in [
        SemanticLimits {
            max_component_bytes: bytes.len() - 1,
            ..SemanticLimits::default()
        },
        SemanticLimits {
            max_sections: 1,
            ..SemanticLimits::default()
        },
        SemanticLimits {
            max_component_items: 1,
            ..SemanticLimits::default()
        },
        SemanticLimits {
            max_operators: 1,
            ..SemanticLimits::default()
        },
    ] {
        assert_eq!(
            validate(&bytes, limits).unwrap_err().code,
            PlatformErrorCode::ResourceExhausted
        );
    }
    let mut truncated = Component::HEADER.to_vec();
    truncated.extend_from_slice(&[1, 100, 0, 97, 115, 109]);
    assert!(validate(&truncated, SemanticLimits::default()).is_err());
}

#[test]
fn alias_names_are_bounded_in_sections_and_nested_type_declarations() {
    use wasm_encoder::{
        Alias, ComponentAliasSection, ComponentTypeSection, ExportKind, InstanceType,
    };
    for nested in [false, true] {
        let alias = Alias::CoreInstanceExport {
            instance: 0,
            kind: ExportKind::Func,
            name: "oversized-name",
        };
        let mut root = Component::new();
        if nested {
            let mut instance = InstanceType::new();
            instance.alias(alias);
            let mut types = ComponentTypeSection::new();
            types.instance(&instance);
            root.section(&types);
        } else {
            let mut aliases = ComponentAliasSection::new();
            aliases.alias(alias);
            root.section(&aliases);
        }
        let limits = SemanticLimits {
            max_name_bytes: 4,
            ..SemanticLimits::default()
        };
        assert_eq!(
            validate(&root.finish(), limits).unwrap_err().code,
            PlatformErrorCode::ResourceExhausted
        );
    }
}

#[test]
fn hidden_package_docs_and_huge_local_counts_have_independent_preflight_limits() {
    use std::borrow::Cow;
    use wasm_encoder::{CodeSection, CustomSection, Function, Instruction, ValType};
    let mut root = Component::new();
    for _ in 0..2 {
        root.section(&CustomSection {
            name: Cow::Borrowed("package-docs"),
            data: Cow::Borrowed(b"\x01{}"),
        });
    }
    let limits = SemanticLimits {
        max_total_wit_bytes: 4,
        ..SemanticLimits::default()
    };
    assert_eq!(
        validate(&root.finish(), limits).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );

    let mut body = Function::new([(u32::MAX, ValType::I32)]);
    body.instruction(&Instruction::End);
    let mut code = CodeSection::new();
    code.function(&body);
    let mut module = wasm_encoder::Module::new();
    let mut types = wasm_encoder::TypeSection::new();
    types.ty().function([], []);
    module.section(&types);
    let mut functions = wasm_encoder::FunctionSection::new();
    functions.function(0);
    module.section(&functions);
    module.section(&code);
    let mut root = Component::new();
    root.section(&ModuleSection(&module));
    assert_eq!(
        validate(&root.finish(), SemanticLimits::default())
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
}

#[test]
fn operator_vectors_are_bounded_before_owned_operand_allocation() {
    for prefix in [
        vec![0x1f, 0x40],
        vec![0xe3, 0],
        vec![0xe4, 0, 0],
        vec![0xe5, 0],
        vec![0x1c],
    ] {
        let mut body = vec![0]; // no locals
        body.extend(prefix);
        body.extend_from_slice(&[3, 0x0b]); // excessive vector count; no entries required
        let mut module = wasm_encoder::Module::new();
        let mut types = wasm_encoder::TypeSection::new();
        types.ty().function([], []);
        module.section(&types);
        let mut functions = wasm_encoder::FunctionSection::new();
        functions.function(0);
        module.section(&functions);
        let mut code = wasm_encoder::CodeSection::new();
        code.raw(&body);
        module.section(&code);
        let mut root = Component::new();
        root.section(&ModuleSection(&module));
        let limits = SemanticLimits {
            max_type_members: 2,
            ..SemanticLimits::default()
        };
        assert_eq!(
            validate(&root.finish(), limits).unwrap_err().code,
            PlatformErrorCode::ResourceExhausted
        );
    }
}

#[test]
fn flat_transitive_type_chains_are_bounded_before_wit_decoding() {
    let mut types = wasm_encoder::ComponentTypeSection::new();
    types
        .defined_type()
        .primitive(wasm_encoder::PrimitiveValType::U32);
    for index in 0..65 {
        types
            .defined_type()
            .list(wasm_encoder::ComponentValType::Type(index));
    }
    let mut root = Component::new();
    root.section(&types);
    assert_eq!(
        validate(&root.finish(), SemanticLimits::default())
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
}

#[test]
fn nested_flat_chains_and_result_diamonds_are_bounded_before_validator() {
    let mut instance = wasm_encoder::InstanceType::new();
    instance
        .ty()
        .defined_type()
        .primitive(wasm_encoder::PrimitiveValType::U32);
    for index in 0..65 {
        instance
            .ty()
            .defined_type()
            .list(wasm_encoder::ComponentValType::Type(index));
    }
    let mut types = wasm_encoder::ComponentTypeSection::new();
    types.instance(&instance);
    let mut root = Component::new();
    root.section(&types);
    let bytes = root.finish();
    assert_eq!(
        heights::validate(&bytes, SemanticLimits::default())
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert!(validate(&bytes, SemanticLimits::default()).is_err());

    let mut types = wasm_encoder::ComponentTypeSection::new();
    types
        .defined_type()
        .primitive(wasm_encoder::PrimitiveValType::U32);
    for index in 0..8 {
        let prior = Some(wasm_encoder::ComponentValType::Type(index));
        types.defined_type().result(prior, prior);
    }
    let mut root = Component::new();
    root.section(&types);
    let bytes = root.finish();
    let limits = SemanticLimits {
        max_type_nodes: 128,
        ..SemanticLimits::default()
    };
    assert_eq!(
        heights::validate(&bytes, limits).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    assert!(validate(&bytes, limits).is_err());
}

//! Tiny real components generated in memory from the pinned encoder.
#![allow(dead_code)]

use wasm_encoder::{
    Alias, CanonicalFunctionSection, CodeSection, Component, ComponentAliasSection,
    ComponentExportKind, ComponentExportSection, ComponentImportSection, ComponentInstanceSection,
    ComponentTypeRef, ComponentTypeSection, ComponentValType, ExportKind, ExportSection, Function,
    FunctionSection, InstanceSection, InstanceType, Instruction, Module, ModuleArg, ModuleSection,
    PrimitiveValType, TypeSection, ValType,
};

pub const CONTRACT: &str = "tests:packaging/api@1.0.0";
pub const CLOCK: &str = "latent:clock/monotonic@0.1.0";
pub const CONTEXT: &str = "latent:context/context@0.1.0";
pub const SERVICE_WIT: &[u8] = include_bytes!("service.wit");
pub const CLOCK_WIT: &[u8] = include_bytes!("../../../../wit/platform/clock/package.wit");
pub const CONTEXT_WIT: &[u8] = include_bytes!("../../../../wit/platform/context/package.wit");

#[derive(Debug, Clone, Copy, Default)]
#[expect(
    clippy::struct_excessive_bools,
    reason = "Independent adversarial mutations of a fixed binary fixture."
)]
pub struct Options {
    pub invalid_body: bool,
    pub invalid_unused_body: bool,
    pub signed_record_field: bool,
    pub changed_variant_case: bool,
    pub signed_result_error: bool,
    pub unknown_host: bool,
    pub wrong_clock_signature: bool,
    pub pruned_context: bool,
    pub extra_export: bool,
}

pub fn component(options: Options) -> Vec<u8> {
    let mut component = Component::new();
    let mut types = ComponentTypeSection::new();
    types.instance(&host(options)); // 0: host interface
    types.defined_type().record([
        (
            "value",
            if options.signed_record_field {
                PrimitiveValType::S32
            } else {
                PrimitiveValType::U32
            },
        ),
        ("enabled", PrimitiveValType::Bool),
    ]); // 1: payload
    types.defined_type().variant([
        ("empty", None),
        (
            if options.changed_variant_case {
                "changed"
            } else {
                "payload"
            },
            Some(ComponentValType::Type(1)),
        ),
    ]); // 2: choice
    types.defined_type().result(
        Some(ComponentValType::Type(2)),
        Some(
            if options.signed_result_error {
                PrimitiveValType::S32
            } else {
                PrimitiveValType::U32
            }
            .into(),
        ),
    ); // 3: outcome
    types.defined_type().record([
        ("count", ComponentValType::Primitive(PrimitiveValType::U32)),
        ("outcome", ComponentValType::Type(3)),
    ]); // 4: input
    types
        .function()
        .params([("input", ComponentValType::Type(4))])
        .result(Some(PrimitiveValType::U32.into())); // 5
    component.section(&types);
    let mut imports = ComponentImportSection::new();
    imports.import(
        if options.unknown_host {
            "tests:unknown/host@1.0.0"
        } else if options.pruned_context {
            CONTEXT
        } else {
            CLOCK
        },
        ComponentTypeRef::Instance(0),
    );
    component.section(&imports);
    component.section(&ModuleSection(&core(options.invalid_body)));
    if options.invalid_unused_body {
        component.section(&ModuleSection(&core(true)));
    }
    let mut instances = InstanceSection::new();
    instances.instantiate(0, [] as [(&str, ModuleArg); 0]);
    component.section(&instances);
    let mut aliases = ComponentAliasSection::new();
    aliases.alias(Alias::CoreInstanceExport {
        instance: 0,
        kind: ExportKind::Func,
        name: "inspect",
    });
    component.section(&aliases);
    let mut canonical = CanonicalFunctionSection::new();
    canonical.lift(0, 5, []);
    component.section(&canonical);
    export_api(&mut component, options);
    component.finish()
}

fn host(options: Options) -> InstanceType {
    let mut host = InstanceType::new();
    let result = if options.wrong_clock_signature {
        PrimitiveValType::U32
    } else if options.pruned_context {
        PrimitiveValType::String
    } else {
        PrimitiveValType::U64
    };
    host.ty()
        .function()
        .params([] as [(&str, ComponentValType); 0])
        .result(Some(result.into()));
    host.export(
        if options.pruned_context {
            "activation-id"
        } else {
            "now-nanos"
        },
        ComponentTypeRef::Func(0),
    );
    host
}

fn export_api(component: &mut Component, options: Options) {
    let mut api = ComponentInstanceSection::new();
    api.export_items([
        ("payload", ComponentExportKind::Type, 1),
        ("choice", ComponentExportKind::Type, 2),
        ("outcome", ComponentExportKind::Type, 3),
        ("input", ComponentExportKind::Type, 4),
        ("inspect", ComponentExportKind::Func, 0),
    ]);
    component.section(&api);
    let mut exports = ComponentExportSection::new();
    exports.export(CONTRACT, ComponentExportKind::Instance, 1, None);
    if options.extra_export {
        exports.export(
            "tests:packaging/extra@1.0.0",
            ComponentExportKind::Instance,
            1,
            None,
        );
    }
    component.section(&exports);
}

pub fn core(invalid_body: bool) -> Module {
    let mut module = Module::new();
    let mut types = TypeSection::new();
    types.ty().function([ValType::I32; 5], [ValType::I32]);
    module.section(&types);
    let mut functions = FunctionSection::new();
    functions.function(0);
    module.section(&functions);
    let mut exports = ExportSection::new();
    exports.export("inspect", ExportKind::Func, 0);
    module.section(&exports);
    let mut function = Function::new([]);
    function.instruction(&if invalid_body {
        Instruction::I64Const(7)
    } else {
        Instruction::I32Const(7)
    });
    function.instruction(&Instruction::End);
    let mut code = CodeSection::new();
    code.function(&function);
    module.section(&code);
    module
}

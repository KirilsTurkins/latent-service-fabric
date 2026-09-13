//! One zero-argument scalar function; no toolchain fixture or guest imports.

use wasm_encoder::{
    Alias, CanonicalFunctionSection, CodeSection, Component, ComponentAliasSection,
    ComponentExportKind, ComponentExportSection, ComponentInstanceSection, ComponentTypeSection,
    ComponentValType, ExportKind, ExportSection, Function, FunctionSection, InstanceSection,
    Instruction, Module, ModuleArg, ModuleSection, PrimitiveValType, TypeSection, ValType,
};

pub const CONTRACT: &str = "tests:admission/api@1.0.0";

pub fn bytes() -> Vec<u8> {
    let mut module = Module::new();
    let mut types = TypeSection::new();
    types.ty().function([], [ValType::I32]);
    module.section(&types);
    let mut functions = FunctionSection::new();
    functions.function(0);
    module.section(&functions);
    let mut exports = ExportSection::new();
    exports.export("answer", ExportKind::Func, 0);
    module.section(&exports);
    let mut body = Function::new([]);
    body.instruction(&Instruction::I32Const(7));
    body.instruction(&Instruction::End);
    let mut code = CodeSection::new();
    code.function(&body);
    module.section(&code);
    let mut component = Component::new();
    let mut types = ComponentTypeSection::new();
    types
        .function()
        .params([] as [(&str, ComponentValType); 0])
        .result(Some(PrimitiveValType::U32.into()));
    component.section(&types);
    component.section(&ModuleSection(&module));
    let mut instances = InstanceSection::new();
    instances.instantiate(0, [] as [(&str, ModuleArg); 0]);
    component.section(&instances);
    let mut aliases = ComponentAliasSection::new();
    aliases.alias(Alias::CoreInstanceExport {
        instance: 0,
        kind: ExportKind::Func,
        name: "answer",
    });
    component.section(&aliases);
    let mut canonical = CanonicalFunctionSection::new();
    canonical.lift(0, 0, []);
    component.section(&canonical);
    let mut instances = ComponentInstanceSection::new();
    instances.export_items([("answer", ComponentExportKind::Func, 0)]);
    component.section(&instances);
    let mut exports = ComponentExportSection::new();
    exports.export(CONTRACT, ComponentExportKind::Instance, 0, None);
    component.section(&exports);
    component.finish()
}

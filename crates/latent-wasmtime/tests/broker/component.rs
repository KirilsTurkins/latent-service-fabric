//! A tiny binary component makes two real calls to the installed wall clock.
use wasm_encoder::*;
pub const CAP: &str = "latent:clock/wall@0.1.0";
pub const CONTRACT: &str = "tests:broker/api@0.1.0";
pub fn bytes() -> Vec<u8> {
    build(false)
}
pub fn spin_after_clocks() -> Vec<u8> {
    build(true)
}
fn build(spin: bool) -> Vec<u8> {
    let mut component = Component::new();
    let mut wall = InstanceType::new();
    wall.ty()
        .function()
        .params([] as [(&str, ComponentValType); 0])
        .result(Some(PrimitiveValType::U64.into()));
    wall.export("now-unix-millis", ComponentTypeRef::Func(0));
    let mut types = ComponentTypeSection::new();
    types.instance(&wall);
    types
        .function()
        .params([] as [(&str, ComponentValType); 0])
        .result(Some(PrimitiveValType::U64.into()));
    component.section(&types);
    let mut imports = ComponentImportSection::new();
    imports.import(CAP, ComponentTypeRef::Instance(0));
    component.section(&imports);
    let mut alias = ComponentAliasSection::new();
    alias.alias(Alias::InstanceExport {
        instance: 0,
        kind: ComponentExportKind::Func,
        name: "now-unix-millis",
    });
    component.section(&alias);
    let mut canonical = CanonicalFunctionSection::new();
    canonical.lower(0, []);
    component.section(&canonical);
    let mut module = Module::new();
    let mut types = TypeSection::new();
    types.ty().function([], [ValType::I64]);
    module.section(&types);
    let mut imports = ImportSection::new();
    imports.import("clock", "now", EntityType::Function(0));
    module.section(&imports);
    let mut functions = FunctionSection::new();
    functions.function(0);
    module.section(&functions);
    let mut exports = ExportSection::new();
    exports.export("read", ExportKind::Func, 1);
    module.section(&exports);
    let mut body = Function::new([]);
    body.instruction(&Instruction::Call(0));
    body.instruction(&Instruction::Drop);
    body.instruction(&Instruction::Call(0));
    if spin {
        body.instruction(&Instruction::Drop);
        body.instruction(&Instruction::Loop(BlockType::Empty));
        body.instruction(&Instruction::Br(0));
        body.instruction(&Instruction::End);
        body.instruction(&Instruction::Unreachable);
    }
    body.instruction(&Instruction::End);
    let mut code = CodeSection::new();
    code.function(&body);
    module.section(&code);
    component.section(&ModuleSection(&module));
    let mut instances = InstanceSection::new();
    instances.export_items([("now", ExportKind::Func, 0)]);
    instances.instantiate(0, [("clock", ModuleArg::Instance(0))]);
    component.section(&instances);
    let mut alias = ComponentAliasSection::new();
    alias.alias(Alias::CoreInstanceExport {
        instance: 1,
        kind: ExportKind::Func,
        name: "read",
    });
    component.section(&alias);
    let mut canonical = CanonicalFunctionSection::new();
    canonical.lift(1, 1, []);
    component.section(&canonical);
    let mut instances = ComponentInstanceSection::new();
    instances.export_items([("read", ComponentExportKind::Func, 1)]);
    component.section(&instances);
    let mut exports = ComponentExportSection::new();
    exports.export(CONTRACT, ComponentExportKind::Instance, 1, None);
    component.section(&exports);
    component.finish()
}

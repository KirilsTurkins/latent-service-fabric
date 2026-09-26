//! Test-only async interface: canonical async lowering, a real subtask and
//! waitable-set suspension. This does not enable a product provider contract.
use wasm_encoder::*;

pub fn bytes() -> Vec<u8> {
    let mut component = Component::new();
    let mut types = ComponentTypeSection::new();
    types
        .function()
        .async_(true)
        .params([] as [(&str, ComponentValType); 0])
        .result(Some(PrimitiveValType::U32.into()));
    component.section(&types);
    let mut imports = ComponentImportSection::new();
    imports.import("read", ComponentTypeRef::Func(0));
    component.section(&imports);

    let mut memory = Module::new();
    let mut memories = MemorySection::new();
    memories.memory(MemoryType {
        minimum: 1,
        maximum: Some(1),
        memory64: false,
        shared: false,
        page_size_log2: None,
    });
    memory.section(&memories);
    let mut exports = ExportSection::new();
    exports.export("memory", ExportKind::Memory, 0);
    memory.section(&exports);
    component.section(&ModuleSection(&memory));
    let mut instances = InstanceSection::new();
    instances.instantiate(0, [] as [(&str, ModuleArg); 0]);
    component.section(&instances);
    let mut alias = ComponentAliasSection::new();
    alias.alias(Alias::CoreInstanceExport {
        instance: 0,
        kind: ExportKind::Memory,
        name: "memory",
    });
    component.section(&alias);
    let mut canonical = CanonicalFunctionSection::new();
    canonical.lower(0, [CanonicalOption::Async, CanonicalOption::Memory(0)]);
    canonical.waitable_set_new();
    canonical.waitable_join();
    canonical.waitable_set_wait(false, 0);
    canonical.subtask_drop();
    canonical.waitable_set_drop();
    component.section(&canonical);

    component.section(&ModuleSection(&guest_module()));
    let mut instances = InstanceSection::new();
    instances.export_items([
        ("read", ExportKind::Func, 0),
        ("new", ExportKind::Func, 1),
        ("join", ExportKind::Func, 2),
        ("wait", ExportKind::Func, 3),
        ("subtask-drop", ExportKind::Func, 4),
        ("set-drop", ExportKind::Func, 5),
    ]);
    instances.instantiate(
        1,
        [
            ("io", ModuleArg::Instance(1)),
            ("memory", ModuleArg::Instance(0)),
        ],
    );
    component.section(&instances);
    let mut alias = ComponentAliasSection::new();
    alias.alias(Alias::CoreInstanceExport {
        instance: 2,
        kind: ExportKind::Func,
        name: "run",
    });
    component.section(&alias);
    let mut canonical = CanonicalFunctionSection::new();
    canonical.lift(6, 0, []);
    component.section(&canonical);
    let mut exports = ComponentExportSection::new();
    exports.export("run", ComponentExportKind::Func, 1, None);
    component.section(&exports);
    component.finish()
}

fn guest_module() -> Module {
    let mut module = Module::new();
    let mut types = TypeSection::new();
    types.ty().function([ValType::I32], [ValType::I32]);
    types.ty().function([], [ValType::I32]);
    types.ty().function([ValType::I32, ValType::I32], []);
    types
        .ty()
        .function([ValType::I32, ValType::I32], [ValType::I32]);
    types.ty().function([ValType::I32], []);
    module.section(&types);
    let mut imports = ImportSection::new();
    for (name, ty) in [
        ("read", 0),
        ("new", 1),
        ("join", 2),
        ("wait", 3),
        ("subtask-drop", 4),
        ("set-drop", 4),
    ] {
        imports.import("io", name, EntityType::Function(ty));
    }
    imports.import(
        "memory",
        "memory",
        EntityType::Memory(MemoryType {
            minimum: 1,
            maximum: Some(1),
            memory64: false,
            shared: false,
            page_size_log2: None,
        }),
    );
    module.section(&imports);
    let mut functions = FunctionSection::new();
    functions.function(1);
    module.section(&functions);
    let mut exports = ExportSection::new();
    exports.export("run", ExportKind::Func, 6);
    module.section(&exports);
    let mut body = Function::new([(2, ValType::I32)]);
    for instruction in [
        Instruction::I32Const(0),
        Instruction::Call(0),
        Instruction::LocalSet(0),
        Instruction::LocalGet(0),
        Instruction::I32Const(15),
        Instruction::I32And,
        Instruction::I32Const(1),
        Instruction::I32Eq,
        Instruction::If(BlockType::Empty),
        Instruction::LocalGet(0),
        Instruction::I32Const(4),
        Instruction::I32ShrU,
        Instruction::LocalSet(0),
        Instruction::Call(1),
        Instruction::LocalSet(1),
        Instruction::LocalGet(0),
        Instruction::LocalGet(1),
        Instruction::Call(2),
        Instruction::LocalGet(1),
        Instruction::I32Const(16),
        Instruction::Call(3),
        Instruction::Drop,
        Instruction::LocalGet(0),
        Instruction::Call(4),
        Instruction::LocalGet(1),
        Instruction::Call(5),
        Instruction::Else,
        Instruction::LocalGet(0),
        Instruction::I32Const(15),
        Instruction::I32And,
        Instruction::I32Const(2), // canonical CallState::Returned
        Instruction::I32Ne,
        Instruction::If(BlockType::Empty),
        Instruction::Unreachable,
        Instruction::End,
        Instruction::End,
        Instruction::I32Const(0),
        Instruction::I32Load(MemArg {
            offset: 0,
            align: 2,
            memory_index: 0,
        }),
        Instruction::End,
    ] {
        body.instruction(&instruction);
    }
    let mut code = CodeSection::new();
    code.function(&body);
    module.section(&code);
    module
}

//! A finite hand-encoded canonical-ABI scheduler diagnostic, not TypeScript.
//! It imports one genuinely pending host future and a synchronous observation
//! callback. Poll and (only in the selected positive case) thread.yield run
//! while that original subtask remains joined to its original waitable set.
use wasm_encoder::*;

pub fn bytes(async_export: bool, yielding: bool) -> Vec<u8> {
    let mut component = Component::new();
    let mut types = ComponentTypeSection::new();
    types
        .function()
        .async_(true)
        .params([] as [(&str, ComponentValType); 0])
        .result(Some(PrimitiveValType::U32.into()));
    types
        .function()
        .params([
            ("turn", PrimitiveValType::U32),
            ("event", PrimitiveValType::U32),
        ])
        .result(None);
    types
        .function()
        .async_(async_export)
        .params([] as [(&str, ComponentValType); 0])
        .result(Some(PrimitiveValType::U32.into()));
    component.section(&types);
    let mut imports = ComponentImportSection::new();
    imports.import("read", ComponentTypeRef::Func(0));
    imports.import("observe", ComponentTypeRef::Func(1));
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

    let mut canon = CanonicalFunctionSection::new();
    canon.lower(0, [CanonicalOption::Memory(0), CanonicalOption::Async]);
    canon.lower(1, []);
    canon.waitable_set_new();
    canon.waitable_join();
    canon.waitable_set_poll(0);
    canon.thread_yield();
    canon.subtask_drop();
    canon.waitable_set_drop();
    canon.subtask_cancel(false);
    component.section(&canon);
    component.section(&ModuleSection(&guest(async_export, yielding)));
    let mut instances = InstanceSection::new();
    instances.export_items([
        ("read", ExportKind::Func, 0),
        ("observe", ExportKind::Func, 1),
        ("new", ExportKind::Func, 2),
        ("join", ExportKind::Func, 3),
        ("poll", ExportKind::Func, 4),
        ("yield", ExportKind::Func, 5),
        ("drop-subtask", ExportKind::Func, 6),
        ("drop-set", ExportKind::Func, 7),
        ("cancel", ExportKind::Func, 8),
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
    let mut canon = CanonicalFunctionSection::new();
    canon.lift(9, 2, []);
    component.section(&canon);
    let mut exports = ComponentExportSection::new();
    exports.export("run", ComponentExportKind::Func, 2, None);
    component.section(&exports);
    component.finish()
}

fn guest(async_export: bool, yielding: bool) -> Module {
    let mut module = Module::new();
    let mut types = TypeSection::new();
    types.ty().function([ValType::I32], [ValType::I32]); // 0 read/cancel
    types.ty().function([ValType::I32, ValType::I32], []); // 1 observe/join
    types.ty().function([], [ValType::I32]); // 2 new/yield/run
    types
        .ty()
        .function([ValType::I32, ValType::I32], [ValType::I32]); // 3 poll
    types.ty().function([ValType::I32], []); // 4 drop
    module.section(&types);
    let mut imports = ImportSection::new();
    for (name, ty) in [
        ("read", 0),
        ("observe", 1),
        ("new", 2),
        ("join", 1),
        ("poll", 3),
        ("yield", 2),
        ("drop-subtask", 4),
        ("drop-set", 4),
        ("cancel", 0),
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
    functions.function(2);
    module.section(&functions);
    let mut exports = ExportSection::new();
    exports.export("run", ExportKind::Func, 9);
    module.section(&exports);
    let mut body = Function::new([(3, ValType::I32)]);
    for instruction in [
        Instruction::I32Const(0),
        Instruction::Call(0),
        Instruction::LocalTee(0),
        Instruction::I32Const(15),
        Instruction::I32And,
        Instruction::I32Const(1),
        Instruction::I32Ne,
        Instruction::If(BlockType::Empty),
        Instruction::Unreachable,
        Instruction::End,
        Instruction::LocalGet(0),
        Instruction::I32Const(4),
        Instruction::I32ShrU,
        Instruction::LocalSet(0),
        Instruction::Call(2),
        Instruction::LocalSet(1),
        Instruction::LocalGet(0),
        Instruction::LocalGet(1),
        Instruction::Call(3),
    ] {
        body.instruction(&instruction);
    }
    for turn in 0..5 {
        // Validate that a reported subtask event names the original handle
        // and the original returned status. All other events are invalid.
        for instruction in [
            Instruction::LocalGet(1),
            Instruction::I32Const(16),
            Instruction::Call(4),
            Instruction::LocalSet(2),
            Instruction::LocalGet(2),
            Instruction::I32Const(1),
            Instruction::I32Eq,
            Instruction::If(BlockType::Empty),
            Instruction::I32Const(16),
            Instruction::I32Load(MemArg {
                offset: 0,
                align: 2,
                memory_index: 0,
            }),
            Instruction::LocalGet(0),
            Instruction::I32Ne,
            Instruction::If(BlockType::Empty),
            Instruction::Unreachable,
            Instruction::End,
            Instruction::I32Const(20),
            Instruction::I32Load(MemArg {
                offset: 0,
                align: 2,
                memory_index: 0,
            }),
            Instruction::I32Const(2),
            Instruction::I32Ne,
            Instruction::If(BlockType::Empty),
            Instruction::Unreachable,
            Instruction::End,
            Instruction::Else,
            Instruction::LocalGet(2),
            Instruction::I32Const(0),
            Instruction::I32Ne,
            Instruction::If(BlockType::Empty),
            Instruction::Unreachable,
            Instruction::End,
            Instruction::End,
            Instruction::I32Const(turn),
            Instruction::LocalGet(2),
            Instruction::Call(1),
        ] {
            body.instruction(&instruction);
        }
        if yielding && turn != 4 {
            body.instruction(&Instruction::Call(5));
            body.instruction(&Instruction::Drop);
        }
    }
    if async_export {
        if yielding {
            // Check the actual value lowered into the original result buffer.
            for instruction in [
                Instruction::I32Const(0),
                Instruction::I32Load(MemArg {
                    offset: 0,
                    align: 2,
                    memory_index: 0,
                }),
                Instruction::I32Const(42),
                Instruction::I32Ne,
                Instruction::If(BlockType::Empty),
                Instruction::Unreachable,
                Instruction::End,
            ] {
                body.instruction(&instruction);
            }
        }
        for instruction in [
            Instruction::LocalGet(0),
            Instruction::I32Const(0),
            Instruction::Call(3),
        ] {
            body.instruction(&instruction);
        }
        if !yielding {
            body.instruction(&Instruction::LocalGet(0));
            body.instruction(&Instruction::Call(8));
            // The synchronous canonical cancellation must acknowledge that
            // this exact started host subtask returned cancelled.
            body.instruction(&Instruction::I32Const(4));
            body.instruction(&Instruction::I32Ne);
            body.instruction(&Instruction::If(BlockType::Empty));
            body.instruction(&Instruction::Unreachable);
            body.instruction(&Instruction::End);
        }
        for instruction in [
            Instruction::LocalGet(0),
            Instruction::Call(6),
            Instruction::LocalGet(1),
            Instruction::Call(7),
            Instruction::I32Const(42),
        ] {
            body.instruction(&instruction);
        }
    } else {
        // No blocking cleanup in a still-running sync task; an intentional trap
        // lets the host prove actual future destruction when the Store drops.
        body.instruction(&Instruction::Unreachable);
    }
    body.instruction(&Instruction::End);
    let mut code = CodeSection::new();
    code.function(&body);
    module.section(&code);
    module
}

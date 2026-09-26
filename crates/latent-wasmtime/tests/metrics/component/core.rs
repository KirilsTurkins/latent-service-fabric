use wasm_encoder::*;
pub(super) fn memory() -> Module {
    let mut module = Module::new();
    let mut types = TypeSection::new();
    types.ty().function([ValType::I32; 4], [ValType::I32]);
    module.section(&types);
    let mut functions = FunctionSection::new();
    functions.function(0);
    module.section(&functions);
    let mut memories = MemorySection::new();
    memories.memory(memory_type());
    module.section(&memories);
    let mut globals = GlobalSection::new();
    globals.global(
        GlobalType {
            val_type: ValType::I32,
            mutable: true,
            shared: false,
        },
        &ConstExpr::i32_const(4096),
    );
    module.section(&globals);
    let mut exports = ExportSection::new();
    exports.export("memory", ExportKind::Memory, 0);
    exports.export("realloc", ExportKind::Func, 0);
    module.section(&exports);
    let mut code = CodeSection::new();
    let mut f = Function::new([(1, ValType::I32)]);
    for i in [
        Instruction::GlobalGet(0),
        Instruction::LocalTee(4),
        Instruction::LocalGet(3),
        Instruction::I32Add,
        Instruction::I32Const(15),
        Instruction::I32Add,
        Instruction::I32Const(-16),
        Instruction::I32And,
        Instruction::GlobalSet(0),
        Instruction::LocalGet(4),
        Instruction::End,
    ] {
        f.instruction(&i);
    }
    code.function(&f);
    module.section(&code);
    module
}
fn memory_type() -> MemoryType {
    MemoryType {
        minimum: 2,
        maximum: Some(4),
        memory64: false,
        shared: false,
        page_size_log2: None,
    }
}
fn load(offset: u64) -> MemArg {
    MemArg {
        offset,
        align: 0,
        memory_index: 0,
    }
}

pub(super) fn caller() -> Module {
    let mut module = Module::new();
    let metric = [
        ValType::I32,
        ValType::I32,
        ValType::I32,
        ValType::F64,
        ValType::I32,
        ValType::I32,
        ValType::I32,
        ValType::I32,
    ];
    let mut types = TypeSection::new();
    types.ty().function(
        metric.into_iter().chain([ValType::I32]).collect::<Vec<_>>(),
        [],
    );
    types.ty().function(
        metric
            .into_iter()
            .chain([ValType::I32; 2])
            .collect::<Vec<_>>(),
        [ValType::I32],
    );
    module.section(&types);
    let mut imports = ImportSection::new();
    imports.import("metrics", "emit-metric", EntityType::Function(0));
    imports.import("memory", "memory", EntityType::Memory(memory_type()));
    module.section(&imports);
    let mut functions = FunctionSection::new();
    functions.function(1);
    module.section(&functions);
    let mut exports = ExportSection::new();
    exports.export("run", ExportKind::Func, 1);
    module.section(&exports);
    // Inputs 0..8 metric, 8 count, 9 mode; locals 10 index and 11 result.
    let mut f = Function::new([(2, ValType::I32)]);
    for (mode, number) in [(1, f64::NAN), (2, f64::INFINITY), (3, f64::NEG_INFINITY)] {
        for i in [
            Instruction::LocalGet(9),
            Instruction::I32Const(mode),
            Instruction::I32Eq,
            Instruction::If(BlockType::Empty),
            Instruction::F64Const(number.into()),
            Instruction::LocalSet(3),
            Instruction::End,
        ] {
            f.instruction(&i);
        }
    }
    for i in [
        Instruction::Block(BlockType::Empty),
        Instruction::Loop(BlockType::Empty),
        Instruction::LocalGet(10),
        Instruction::LocalGet(8),
        Instruction::I32GeU,
        Instruction::BrIf(1),
    ] {
        f.instruction(&i);
    }
    for index in 0..8 {
        f.instruction(&Instruction::LocalGet(index));
    }
    for i in [
        Instruction::I32Const(512),
        Instruction::Call(0),
        Instruction::I32Const(512),
        Instruction::I32Load8U(load(0)),
        Instruction::If(BlockType::Empty),
        Instruction::I32Const(513),
        Instruction::I32Load8U(load(0)),
        Instruction::I32Const(i32::MIN),
        Instruction::I32Or,
        Instruction::Return,
        Instruction::End,
        Instruction::I32Const(513),
        Instruction::I32Load8U(load(0)),
        Instruction::LocalSet(11),
        Instruction::LocalGet(10),
        Instruction::I32Const(1),
        Instruction::I32Add,
        Instruction::LocalSet(10),
        Instruction::Br(0),
        Instruction::End,
        Instruction::End,
        Instruction::LocalGet(11),
        Instruction::End,
    ] {
        f.instruction(&i);
    }
    let mut code = CodeSection::new();
    code.function(&f);
    module.section(&code);
    module
}

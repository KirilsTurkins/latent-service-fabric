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
    let mut types = TypeSection::new();
    types.ty().function([ValType::I32; 2], []);
    types.ty().function([ValType::I32], []);
    types.ty().function([ValType::I32; 3], [ValType::I64]);
    module.section(&types);
    let mut imports = ImportSection::new();
    imports.import("random", "bytes", EntityType::Function(0));
    imports.import("random", "u64-value", EntityType::Function(1));
    imports.import("memory", "memory", EntityType::Memory(memory_type()));
    module.section(&imports);
    let mut functions = FunctionSection::new();
    functions.function(2);
    module.section(&functions);
    let mut exports = ExportSection::new();
    exports.export("run", ExportKind::Func, 2);
    module.section(&exports);
    // locals 3=index, 4=u64 mode, 5=last value.
    let mut f = Function::new([(2, ValType::I32), (1, ValType::I64)]);
    for i in [
        Instruction::Block(BlockType::Empty),
        Instruction::Loop(BlockType::Empty),
        Instruction::LocalGet(3),
        Instruction::LocalGet(2),
        Instruction::I32GeU,
        Instruction::BrIf(1),
        Instruction::LocalGet(0),
        Instruction::I32Const(1),
        Instruction::I32Eq,
        Instruction::LocalGet(0),
        Instruction::I32Const(2),
        Instruction::I32Eq,
        Instruction::LocalGet(3),
        Instruction::I32Const(1),
        Instruction::I32Eq,
        Instruction::I32And,
        Instruction::I32Or,
        Instruction::LocalTee(4),
        Instruction::If(BlockType::Empty),
        Instruction::I32Const(512),
        Instruction::Call(1),
        Instruction::Else,
        Instruction::LocalGet(1),
        Instruction::I32Const(512),
        Instruction::Call(0),
        Instruction::End,
        Instruction::I32Const(512),
        Instruction::I32Load8U(load(0)),
        Instruction::If(BlockType::Empty),
        Instruction::LocalGet(4),
        Instruction::If(BlockType::Result(ValType::I32)),
        Instruction::I32Const(520),
        Instruction::Else,
        Instruction::I32Const(516),
        Instruction::End,
        Instruction::I32Load8U(load(0)),
        Instruction::I64ExtendI32U,
        Instruction::I64Const(i64::MIN),
        Instruction::I64Or,
        Instruction::Return,
        Instruction::End,
        Instruction::LocalGet(4),
        Instruction::If(BlockType::Result(ValType::I64)),
        Instruction::I32Const(512),
        Instruction::I64Load(load(8)),
        Instruction::Else,
        Instruction::I32Const(512),
        Instruction::I32Load(load(8)),
        Instruction::I64ExtendI32U,
        Instruction::LocalGet(1),
        Instruction::If(BlockType::Result(ValType::I64)),
        Instruction::I32Const(512),
        Instruction::I32Load(load(4)),
        Instruction::I32Load8U(load(0)),
        Instruction::I64ExtendI32U,
        Instruction::I64Const(32),
        Instruction::I64Shl,
        Instruction::Else,
        Instruction::I64Const(0),
        Instruction::End,
        Instruction::I64Or,
        Instruction::End,
        Instruction::LocalSet(5),
        Instruction::LocalGet(3),
        Instruction::I32Const(1),
        Instruction::I32Add,
        Instruction::LocalSet(3),
        Instruction::Br(0),
        Instruction::End,
        Instruction::End,
        Instruction::LocalGet(5),
        Instruction::End,
    ] {
        f.instruction(&i);
    }
    let mut code = CodeSection::new();
    code.function(&f);
    module.section(&code);
    module
}

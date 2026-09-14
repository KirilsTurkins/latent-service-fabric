#![allow(dead_code)]
use wasm_encoder::*;
#[path = "../../../latent-packaging/tests/fixtures/host.rs"]
mod host;
pub const CALLER: &str = "tests:caller/api@1.0.0";
pub const CALLEE: &str = "tests:local/api@1.0.0";
pub const CALLER_WIT: &str = "package tests:caller@1.0.0; interface api { run: async func(which: u32) -> u32; } world service { import latent:service/invoke@0.1.0; export api; }";
pub const CALLEE_WIT: &str = "package tests:local@1.0.0; interface api { answer: func() -> u32; fail: func() -> result<u32, string>; spin: func() -> u32; } world service { export api; }";
const ARGS: i32 = 128;
const RESULT: i32 = 512;

pub fn caller(tenant: Option<&str>) -> Vec<u8> {
    let mut component = Component::new();
    let spec = latent_core::PHASE3_HOST_ABI_V2
        .interface(latent_capabilities::broker::SERVICE_INVOCATION_CAPABILITY)
        .unwrap();
    let mut types = ComponentTypeSection::new();
    types.instance(&host::interface(spec.wit, spec.interface, None));
    types
        .function()
        .async_(true)
        .params([("which", PrimitiveValType::U32)])
        .result(Some(PrimitiveValType::U32.into()));
    component.section(&types);
    let mut imports = ComponentImportSection::new();
    imports.import(spec.interface, ComponentTypeRef::Instance(0));
    component.section(&imports);
    let mut aliases = ComponentAliasSection::new();
    aliases.alias(Alias::InstanceExport {
        instance: 0,
        kind: ComponentExportKind::Func,
        name: "call",
    });
    component.section(&aliases);
    component.section(&ModuleSection(&memory(tenant)));
    let mut instances = InstanceSection::new();
    instances.instantiate(0, [] as [(&str, ModuleArg); 0]);
    component.section(&instances);
    let mut aliases = ComponentAliasSection::new();
    aliases.alias(Alias::CoreInstanceExport {
        instance: 0,
        kind: ExportKind::Memory,
        name: "memory",
    });
    aliases.alias(Alias::CoreInstanceExport {
        instance: 0,
        kind: ExportKind::Func,
        name: "realloc",
    });
    component.section(&aliases);
    let mut canonical = CanonicalFunctionSection::new();
    canonical.lower(
        0,
        [
            CanonicalOption::Async,
            CanonicalOption::Memory(0),
            CanonicalOption::Realloc(0),
        ],
    );
    canonical.waitable_set_new();
    canonical.waitable_join();
    canonical.waitable_set_wait(false, 0);
    canonical.subtask_drop();
    canonical.waitable_set_drop();
    component.section(&canonical);
    component.section(&ModuleSection(&caller_module()));
    let mut instances = InstanceSection::new();
    instances.export_items([
        ("call", ExportKind::Func, 1),
        ("new", ExportKind::Func, 2),
        ("join", ExportKind::Func, 3),
        ("wait", ExportKind::Func, 4),
        ("subtask-drop", ExportKind::Func, 5),
        ("set-drop", ExportKind::Func, 6),
    ]);
    instances.instantiate(
        1,
        [
            ("io", ModuleArg::Instance(1)),
            ("memory", ModuleArg::Instance(0)),
        ],
    );
    component.section(&instances);
    let mut aliases = ComponentAliasSection::new();
    aliases.alias(Alias::CoreInstanceExport {
        instance: 2,
        kind: ExportKind::Func,
        name: "run",
    });
    component.section(&aliases);
    let mut canonical = CanonicalFunctionSection::new();
    canonical.lift(7, 1, []);
    component.section(&canonical);
    let mut instances = ComponentInstanceSection::new();
    instances.export_items([("run", ComponentExportKind::Func, 1)]);
    component.section(&instances);
    let mut exports = ComponentExportSection::new();
    exports.export(CALLER, ComponentExportKind::Instance, 1, None);
    component.section(&exports);
    component.finish()
}
fn memory_type() -> MemoryType {
    MemoryType {
        minimum: 4,
        maximum: Some(4),
        memory64: false,
        shared: false,
        page_size_log2: None,
    }
}
fn string(bytes: &mut [u8], cursor: &mut usize, field: usize, value: &str) {
    bytes[field..field + 4].copy_from_slice(&u32::try_from(*cursor).unwrap().to_le_bytes());
    bytes[field + 4..field + 8].copy_from_slice(&u32::try_from(value.len()).unwrap().to_le_bytes());
    bytes[*cursor..*cursor + value.len()].copy_from_slice(value.as_bytes());
    *cursor += value.len();
}

fn memory(tenant: Option<&str>) -> Module {
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
    let mut body = Function::new([(1, ValType::I32)]);
    for instruction in [
        Instruction::GlobalGet(0),
        Instruction::LocalGet(2),
        Instruction::I32Add,
        Instruction::I32Const(1),
        Instruction::I32Sub,
        Instruction::I32Const(0),
        Instruction::LocalGet(2),
        Instruction::I32Sub,
        Instruction::I32And,
        Instruction::LocalTee(4),
        Instruction::LocalGet(3),
        Instruction::I32Add,
        Instruction::GlobalSet(0),
        Instruction::GlobalGet(0),
        Instruction::I32Const(262_144),
        Instruction::I32GtU,
        Instruction::If(BlockType::Empty),
        Instruction::Unreachable,
        Instruction::End,
        Instruction::LocalGet(4),
        Instruction::End,
    ] {
        body.instruction(&instruction);
    }
    let mut code = CodeSection::new();
    code.function(&body);
    module.section(&code);
    let mut bytes = vec![0u8; 2048];
    let mut cursor = 1024usize;
    let base = ARGS as usize;
    if let Some(tenant) = tenant {
        bytes[base] = 1;
        string(&mut bytes, &mut cursor, base + 4, tenant);
    }
    string(&mut bytes, &mut cursor, base + 12, "callee");
    string(&mut bytes, &mut cursor, base + 20, CALLEE);
    string(&mut bytes, &mut cursor, base + 28, "answer");
    string(&mut bytes, &mut cursor, base + 48, "[]");
    string(
        &mut bytes,
        &mut cursor,
        base + 56,
        "application/vnd.latent.wit-values.v1+json",
    );
    bytes[1800..1804].copy_from_slice(b"fail");
    bytes[1804..1808].copy_from_slice(b"spin");
    bytes[1810..1815].copy_from_slice(b"bogus");
    let mut data = DataSection::new();
    data.active(0, &ConstExpr::i32_const(0), bytes);
    module.section(&data);
    module
}
fn mem(offset: u64) -> MemArg {
    MemArg {
        offset,
        align: 2,
        memory_index: 0,
    }
}
#[expect(
    clippy::too_many_lines,
    reason = "explicit core instructions for canonical async call, wait and outcome decoding"
)]
fn caller_module() -> Module {
    let mut module = Module::new();
    let mut types = TypeSection::new();
    types
        .ty()
        .function([ValType::I32, ValType::I32], [ValType::I32]); // call and wait
    types.ty().function([], [ValType::I32]); // set-new
    types.ty().function([ValType::I32, ValType::I32], []); // join
    types.ty().function([ValType::I32], []); // drops
    types.ty().function([ValType::I32], [ValType::I32]); // run
    module.section(&types);
    let mut imports = ImportSection::new();
    for (name, ty) in [
        ("call", 0),
        ("new", 1),
        ("join", 2),
        ("wait", 0),
        ("subtask-drop", 3),
        ("set-drop", 3),
    ] {
        imports.import("io", name, EntityType::Function(ty));
    }
    imports.import("memory", "memory", EntityType::Memory(memory_type()));
    module.section(&imports);
    let mut functions = FunctionSection::new();
    functions.function(4); // run
    functions.function(3); // wait for one async subtask
    functions.function(4); // decode bounded test outcome
    module.section(&functions);
    let mut exports = ExportSection::new();
    exports.export("run", ExportKind::Func, 6);
    module.section(&exports);
    let mut body = Function::new([(2, ValType::I32)]);
    for (mode, fields) in [
        (4, vec![(ARGS + 52, 65537)]),
        (5, vec![(ARGS + 28, 1810), (ARGS + 32, 5)]),
        (6, vec![(ARGS + 36, 1), (ARGS + 40, 1810), (ARGS + 44, 5)]),
        (7, vec![(ARGS + 64, 1)]), // expired absolute deadline, zero u64 payload
    ] {
        body.instruction(&Instruction::LocalGet(0));
        body.instruction(&Instruction::I32Const(mode));
        body.instruction(&Instruction::I32Eq);
        body.instruction(&Instruction::If(BlockType::Empty));
        for (address, value) in fields {
            body.instruction(&Instruction::I32Const(address));
            body.instruction(&Instruction::I32Const(value));
            body.instruction(&Instruction::I32Store(mem(0)));
        }
        body.instruction(&Instruction::End);
    }
    for instruction in [
        Instruction::LocalGet(0),
        Instruction::I32Const(1),
        Instruction::I32GeU,
        Instruction::LocalGet(0),
        Instruction::I32Const(2),
        Instruction::I32LeU,
        Instruction::I32And,
        Instruction::If(BlockType::Empty),
        Instruction::I32Const(ARGS + 28),
        Instruction::I32Const(1796),
        Instruction::LocalGet(0),
        Instruction::I32Const(4),
        Instruction::I32Mul,
        Instruction::I32Add,
        Instruction::I32Store(mem(0)),
        Instruction::I32Const(ARGS + 32),
        Instruction::I32Const(4),
        Instruction::I32Store(mem(0)),
        Instruction::End,
        Instruction::I32Const(ARGS),
        Instruction::I32Const(RESULT),
        Instruction::Call(0),
        Instruction::LocalSet(1),
        // Start the second imported call before awaiting the first. Each result
        // has distinct guest memory and each child needs its own owned grant.
        Instruction::LocalGet(0),
        Instruction::I32Const(3),
        Instruction::I32Eq,
        Instruction::If(BlockType::Empty),
        Instruction::I32Const(ARGS),
        Instruction::I32Const(RESULT + 128),
        Instruction::Call(0),
        Instruction::LocalSet(2),
        Instruction::End,
        Instruction::LocalGet(1),
        Instruction::Call(7),
        Instruction::LocalGet(0),
        Instruction::I32Const(3),
        Instruction::I32Eq,
        Instruction::If(BlockType::Result(ValType::I32)),
        Instruction::LocalGet(2),
        Instruction::Call(7),
        Instruction::I32Const(RESULT + 128),
        Instruction::Else,
        Instruction::I32Const(RESULT),
        Instruction::End,
        Instruction::Call(8),
        Instruction::End,
    ] {
        body.instruction(&instruction);
    }
    let mut wait = Function::new([(1, ValType::I32)]);
    for instruction in [
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
        Instruction::I32Const(768),
        Instruction::Call(3),
        Instruction::Drop,
        Instruction::LocalGet(0),
        Instruction::Call(4),
        Instruction::LocalGet(1),
        Instruction::Call(5),
        Instruction::End,
        Instruction::End,
    ] {
        wait.instruction(&instruction);
    }
    let mut read = Function::new([(1, ValType::I32)]);
    for instruction in [
        Instruction::LocalGet(0),
        Instruction::I32Load8U(MemArg { align: 0, ..mem(0) }),
        Instruction::LocalSet(1),
        Instruction::LocalGet(1),
        Instruction::I32Eqz,
        Instruction::If(BlockType::Result(ValType::I32)),
        Instruction::LocalGet(0),
        Instruction::I32Load(mem(4)),
        Instruction::I32Load(mem(0)),
        Instruction::Else,
        Instruction::LocalGet(1),
        Instruction::I32Const(1000),
        Instruction::I32Mul,
        Instruction::LocalGet(1),
        Instruction::I32Const(2),
        Instruction::I32Eq,
        Instruction::If(BlockType::Result(ValType::I32)),
        Instruction::LocalGet(0),
        Instruction::I32Load8U(MemArg { align: 0, ..mem(4) }),
        Instruction::Else,
        Instruction::I32Const(0),
        Instruction::End,
        Instruction::I32Add,
        Instruction::End,
        Instruction::End,
    ] {
        read.instruction(&instruction);
    }
    let mut code = CodeSection::new();
    code.function(&body);
    code.function(&wait);
    code.function(&read);
    module.section(&code);
    module
}

pub fn callee(answer: i32) -> Vec<u8> {
    let mut module = Module::new();
    let mut types = TypeSection::new();
    types.ty().function([], [ValType::I32]);
    module.section(&types);
    let mut functions = FunctionSection::new();
    for _ in 0..3 {
        functions.function(0);
    }
    module.section(&functions);
    let mut memories = MemorySection::new();
    memories.memory(MemoryType {
        minimum: 1,
        maximum: Some(1),
        ..memory_type()
    });
    module.section(&memories);
    let mut exports = ExportSection::new();
    for (name, index) in [("answer", 0), ("fail", 1), ("spin", 2)] {
        exports.export(name, ExportKind::Func, index);
    }
    exports.export("memory", ExportKind::Memory, 0);
    module.section(&exports);
    let mut code = CodeSection::new();
    for value in [answer, 0] {
        let mut body = Function::new([]);
        body.instruction(&Instruction::I32Const(value));
        body.instruction(&Instruction::End);
        code.function(&body);
    }
    let mut body = Function::new([]);
    for instruction in [
        Instruction::Loop(BlockType::Empty),
        Instruction::Br(0),
        Instruction::End,
        Instruction::Unreachable,
        Instruction::End,
    ] {
        body.instruction(&instruction);
    }
    code.function(&body);
    module.section(&code);
    let mut bytes = vec![0u8; 24];
    bytes[0] = 1; // result::err
    bytes[4] = 16;
    bytes[8] = 8;
    bytes[16..24].copy_from_slice(b"declined");
    let mut data = DataSection::new();
    data.active(0, &ConstExpr::i32_const(0), bytes);
    module.section(&data);
    let mut component = Component::new();
    component.section(&ModuleSection(&module));
    let mut instances = InstanceSection::new();
    instances.instantiate(0, [] as [(&str, ModuleArg); 0]);
    component.section(&instances);
    let mut types = ComponentTypeSection::new();
    types.defined_type().result(
        Some(PrimitiveValType::U32.into()),
        Some(PrimitiveValType::String.into()),
    );
    types
        .function()
        .params([] as [(&str, ComponentValType); 0])
        .result(Some(PrimitiveValType::U32.into()));
    types
        .function()
        .params([] as [(&str, ComponentValType); 0])
        .result(Some(ComponentValType::Type(0)));
    component.section(&types);
    let mut aliases = ComponentAliasSection::new();
    for name in ["answer", "fail", "spin"] {
        aliases.alias(Alias::CoreInstanceExport {
            instance: 0,
            kind: ExportKind::Func,
            name,
        });
    }
    aliases.alias(Alias::CoreInstanceExport {
        instance: 0,
        kind: ExportKind::Memory,
        name: "memory",
    });
    component.section(&aliases);
    let mut canonical = CanonicalFunctionSection::new();
    canonical.lift(0, 1, []);
    canonical.lift(1, 2, [CanonicalOption::Memory(0)]);
    canonical.lift(2, 1, []);
    component.section(&canonical);
    let mut instances = ComponentInstanceSection::new();
    instances.export_items([
        ("answer", ComponentExportKind::Func, 0),
        ("fail", ComponentExportKind::Func, 1),
        ("spin", ComponentExportKind::Func, 2),
    ]);
    component.section(&instances);
    let mut exports = ComponentExportSection::new();
    exports.export(CALLEE, ComponentExportKind::Instance, 0, None);
    component.section(&exports);
    component.finish()
}

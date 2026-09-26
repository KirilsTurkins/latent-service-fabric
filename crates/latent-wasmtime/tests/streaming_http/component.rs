//! Tiny executed resource guest, encoded from the frozen streaming WIT.
use wasm_encoder::*;
#[path = "../../../latent-packaging/tests/fixtures/host.rs"]
mod host;
pub const CONTRACT: &str = "tests:streaming-http/api@1.0.0";
pub const CAP: &str = latent_capabilities::broker::streaming_http::STREAMING_HTTP_CAPABILITY;
const ARGS: i32 = 128;
const RESULT: i32 = 512;
const OPS: [&str; 8] = [
    "open",
    "write",
    "finish",
    "read",
    "chunk-bytes",
    "trailers",
    "abort-upload",
    "abort-body",
];
#[expect(
    clippy::too_many_lines,
    reason = "Finite encoded guest instructions remain in canonical ABI execution order."
)]
pub fn bytes(url: &str) -> Vec<u8> {
    let mut component = Component::new();
    let spec = latent_core::PHASE3_HOST_ABI_V3.interface(CAP).unwrap();
    let mut types = ComponentTypeSection::new();
    types.instance(&host::interface(spec.wit, spec.interface, None));
    types
        .function()
        .async_(true)
        .params([("which", PrimitiveValType::U32)])
        .result(Some(PrimitiveValType::U32.into()));
    component.section(&types);
    let mut imports = ComponentImportSection::new();
    imports.import(CAP, ComponentTypeRef::Instance(0));
    component.section(&imports);
    let mut aliases = ComponentAliasSection::new();
    for name in OPS {
        aliases.alias(Alias::InstanceExport {
            instance: 0,
            kind: ComponentExportKind::Func,
            name,
        });
    }
    for name in ["upload", "body", "chunk"] {
        aliases.alias(Alias::InstanceExport {
            instance: 0,
            kind: ComponentExportKind::Type,
            name,
        });
    }
    component.section(&aliases);
    component.section(&ModuleSection(&memory(url)));
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
    for function in 0..8 {
        canonical.lower(
            function,
            [
                CanonicalOption::Async,
                CanonicalOption::Memory(0),
                CanonicalOption::Realloc(0),
            ],
        );
    }
    for resource in 2..5 {
        canonical.resource_drop(resource);
    }
    canonical.waitable_set_new();
    canonical.waitable_join();
    canonical.waitable_set_wait(false, 0);
    canonical.subtask_drop();
    canonical.waitable_set_drop();
    component.section(&canonical);
    component.section(&ModuleSection(&caller()));
    let mut instances = InstanceSection::new();
    let exports = OPS
        .into_iter()
        .chain([
            "drop-upload",
            "drop-body",
            "drop-chunk",
            "new",
            "join",
            "wait",
            "subtask-drop",
            "set-drop",
        ])
        .enumerate()
        .map(|(i, n)| (n, ExportKind::Func, u32::try_from(i + 1).unwrap()));
    instances.export_items(exports.collect::<Vec<_>>());
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
    canonical.lift(17, 1, []);
    component.section(&canonical);
    let mut instances = ComponentInstanceSection::new();
    instances.export_items([("run", ComponentExportKind::Func, 8)]);
    component.section(&instances);
    let mut exports = ComponentExportSection::new();
    exports.export(CONTRACT, ComponentExportKind::Instance, 1, None);
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

fn memory(url: &str) -> Module {
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
    string(&mut bytes, &mut cursor, base + 4, url);
    bytes[base + 24] = 1;
    bytes[base + 32..base + 40].copy_from_slice(&8u64.to_le_bytes());
    bytes[960..968].copy_from_slice(b"abcdefgh");
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

fn instructions(body: &mut Function, values: impl IntoIterator<Item = Instruction<'static>>) {
    for value in values {
        body.instruction(&value);
    }
}
fn call(
    body: &mut Function,
    function: u32,
    params: impl IntoIterator<Item = Instruction<'static>>,
) {
    instructions(body, params);
    instructions(
        body,
        [
            Instruction::I32Const(RESULT),
            Instruction::Call(function),
            Instruction::Call(17),
        ],
    );
}
fn require_ok(body: &mut Function) {
    instructions(
        body,
        [
            Instruction::I32Const(RESULT),
            Instruction::I32Load8U(MemArg { align: 0, ..mem(0) }),
            Instruction::If(BlockType::Empty),
            Instruction::Unreachable,
            Instruction::End,
        ],
    );
}
fn mode(body: &mut Function, which: i32) {
    instructions(
        body,
        [
            Instruction::LocalGet(0),
            Instruction::I32Const(which),
            Instruction::I32Eq,
            Instruction::If(BlockType::Empty),
        ],
    );
}
#[expect(
    clippy::too_many_lines,
    reason = "Finite encoded guest instructions remain in canonical ABI execution order."
)]
fn caller() -> Module {
    let mut module = Module::new();
    let mut types = TypeSection::new();
    types.ty().function([ValType::I32; 2], [ValType::I32]);
    types.ty().function([ValType::I32; 4], [ValType::I32]);
    types.ty().function([ValType::I32; 3], [ValType::I32]);
    types.ty().function([ValType::I32], []);
    types.ty().function([], [ValType::I32]);
    types.ty().function([ValType::I32; 2], []);
    types.ty().function([ValType::I32], [ValType::I32]);
    module.section(&types);
    let mut imports = ImportSection::new();
    for (name, ty) in OPS.into_iter().zip([0, 1, 0, 2, 0, 0, 0, 0]).chain([
        ("drop-upload", 3),
        ("drop-body", 3),
        ("drop-chunk", 3),
        ("new", 4),
        ("join", 5),
        ("wait", 0),
        ("subtask-drop", 3),
        ("set-drop", 3),
    ]) {
        imports.import("io", name, EntityType::Function(ty));
    }
    imports.import("memory", "memory", EntityType::Memory(memory_type()));
    module.section(&imports);
    let mut functions = FunctionSection::new();
    functions.function(6);
    functions.function(3);
    module.section(&functions);
    let mut exports = ExportSection::new();
    exports.export("run", ExportKind::Func, 16);
    module.section(&exports);
    // locals: 0 mode, 1 upload, 2 body, 3 chunk, 4 byte total, 5 status.
    let mut body = Function::new([(5, ValType::I32)]);
    call(&mut body, 0, [Instruction::I32Const(ARGS)]);
    // Denials are returned as a stable test code; the provider must never start.
    instructions(
        &mut body,
        [
            Instruction::I32Const(RESULT),
            Instruction::I32Load8U(MemArg { align: 0, ..mem(0) }),
            Instruction::If(BlockType::Empty),
            Instruction::I32Const(1000),
            Instruction::I32Const(RESULT),
            Instruction::I32Load8U(MemArg { align: 0, ..mem(4) }),
            Instruction::I32Add,
            Instruction::Return,
            Instruction::End,
            Instruction::I32Const(RESULT),
            Instruction::I32Load(mem(4)),
            Instruction::LocalSet(1),
        ],
    );
    mode(&mut body, 4);
    call(&mut body, 6, [Instruction::LocalGet(1)]);
    require_ok(&mut body);
    instructions(
        &mut body,
        [
            Instruction::I32Const(0),
            Instruction::Return,
            Instruction::End,
        ],
    );
    mode(&mut body, 9);
    instructions(&mut body, [Instruction::Unreachable, Instruction::End]);
    for offset in [960, 964] {
        call(
            &mut body,
            1,
            [
                Instruction::LocalGet(1),
                Instruction::I32Const(offset),
                Instruction::I32Const(4),
            ],
        );
        require_ok(&mut body);
    }
    call(&mut body, 2, [Instruction::LocalGet(1)]);
    require_ok(&mut body);
    instructions(
        &mut body,
        [
            Instruction::I32Const(RESULT),
            Instruction::I32Load(mem(28)),
            Instruction::LocalSet(2),
            Instruction::I32Const(RESULT),
            Instruction::I32Load16U(MemArg { align: 1, ..mem(4) }),
            Instruction::LocalSet(5),
        ],
    );
    mode(&mut body, 5);
    call(&mut body, 4, [Instruction::I32Const(-1)]);
    instructions(&mut body, [Instruction::Unreachable, Instruction::End]);
    mode(&mut body, 6);
    call(&mut body, 4, [Instruction::LocalGet(2)]);
    instructions(&mut body, [Instruction::Unreachable, Instruction::End]);
    instructions(
        &mut body,
        [
            Instruction::Block(BlockType::Empty),
            Instruction::Loop(BlockType::Empty),
        ],
    );
    call(
        &mut body,
        3,
        [Instruction::LocalGet(2), Instruction::I32Const(4)],
    );
    require_ok(&mut body);
    instructions(
        &mut body,
        [
            Instruction::I32Const(RESULT),
            Instruction::I32Load8U(MemArg { align: 0, ..mem(4) }),
            Instruction::I32Eqz,
            Instruction::BrIf(1),
            Instruction::I32Const(RESULT),
            Instruction::I32Load(mem(8)),
            Instruction::LocalSet(3),
        ],
    );
    mode(&mut body, 3);
    call(&mut body, 7, [Instruction::LocalGet(2)]);
    require_ok(&mut body);
    instructions(&mut body, [Instruction::End]);
    call(&mut body, 4, [Instruction::LocalGet(3)]);
    require_ok(&mut body);
    instructions(
        &mut body,
        [
            Instruction::LocalGet(4),
            Instruction::I32Const(RESULT),
            Instruction::I32Load(mem(8)),
            Instruction::I32Add,
            Instruction::LocalSet(4),
        ],
    );
    mode(&mut body, 1);
    instructions(&mut body, [Instruction::Unreachable, Instruction::End]);
    // A second materialization is a typed invalid-state, preventing duplicate copies.
    call(&mut body, 4, [Instruction::LocalGet(3)]);
    instructions(
        &mut body,
        [
            Instruction::I32Const(RESULT),
            Instruction::I32Load8U(MemArg { align: 0, ..mem(0) }),
            Instruction::I32Eqz,
            Instruction::If(BlockType::Empty),
            Instruction::Unreachable,
            Instruction::End,
            Instruction::LocalGet(3),
            Instruction::Call(10),
        ],
    );
    mode(&mut body, 7);
    instructions(
        &mut body,
        [
            Instruction::LocalGet(3),
            Instruction::Call(10),
            Instruction::Unreachable,
            Instruction::End,
        ],
    );
    for which in [0, 3] {
        mode(&mut body, which);
        instructions(
            &mut body,
            [
                Instruction::LocalGet(4),
                Instruction::I32Const(1000),
                Instruction::I32Mul,
                Instruction::LocalGet(5),
                Instruction::I32Add,
                Instruction::Return,
                Instruction::End,
            ],
        );
    }
    instructions(
        &mut body,
        [Instruction::Br(0), Instruction::End, Instruction::End],
    );
    call(&mut body, 5, [Instruction::LocalGet(2)]);
    require_ok(&mut body);
    call(&mut body, 5, [Instruction::LocalGet(2)]);
    instructions(
        &mut body,
        [
            Instruction::I32Const(RESULT),
            Instruction::I32Load8U(MemArg { align: 0, ..mem(0) }),
            Instruction::I32Eqz,
            Instruction::If(BlockType::Empty),
            Instruction::Unreachable,
            Instruction::End,
            Instruction::LocalGet(2),
            Instruction::Call(9),
            Instruction::LocalGet(4),
            Instruction::I32Const(1000),
            Instruction::I32Mul,
            Instruction::LocalGet(5),
            Instruction::I32Add,
            Instruction::End,
        ],
    );
    let mut wait = Function::new([(1, ValType::I32)]);
    instructions(
        &mut wait,
        [
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
            Instruction::Call(11),
            Instruction::LocalSet(1),
            Instruction::LocalGet(0),
            Instruction::LocalGet(1),
            Instruction::Call(12),
            Instruction::LocalGet(1),
            Instruction::I32Const(768),
            Instruction::Call(13),
            Instruction::Drop,
            Instruction::LocalGet(0),
            Instruction::Call(14),
            Instruction::LocalGet(1),
            Instruction::Call(15),
            Instruction::End,
            Instruction::End,
        ],
    );
    let mut code = CodeSection::new();
    code.function(&body);
    code.function(&wait);
    module.section(&code);
    module
}

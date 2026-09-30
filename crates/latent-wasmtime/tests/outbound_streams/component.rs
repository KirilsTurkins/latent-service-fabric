//! Tiny executed resource guest, encoded from the frozen stream WIT.
use wasm_encoder::*;
#[path = "../../../latent-packaging/tests/fixtures/host.rs"]
mod host;
pub const CONTRACT: &str = "tests:outbound-streams/api@1.0.0";
pub const CAP: &str = latent_capabilities::broker::network::STREAM_CAPABILITY;
const RESULT: i32 = 512;
pub const OPS: [&str; 8] = [
    "connect",
    "read",
    "write",
    "ready",
    "inspect",
    "shutdown",
    "close",
    "chunk-bytes",
];
#[expect(
    clippy::too_many_lines,
    reason = "Finite encoded guest instructions remain in canonical ABI execution order."
)]
pub fn bytes(port: u16) -> Vec<u8> {
    let mut component = Component::new();
    let spec = latent_core::PHASE3_HOST_ABI_V5.interface(CAP).unwrap();
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
    for name in ["connection", "chunk"] {
        aliases.alias(Alias::InstanceExport {
            instance: 0,
            kind: ComponentExportKind::Type,
            name,
        });
    }
    component.section(&aliases);
    component.section(&ModuleSection(&memory(port)));
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
        let mut options = vec![CanonicalOption::Memory(0), CanonicalOption::Realloc(0)];
        if function != 4 {
            options.push(CanonicalOption::Async);
        }
        canonical.lower(function, options);
    }
    for resource in 2..4 {
        canonical.resource_drop(resource);
    }
    canonical.waitable_set_new();
    canonical.waitable_join();
    canonical.waitable_set_wait(0);
    canonical.subtask_drop();
    canonical.waitable_set_drop();
    component.section(&canonical);
    component.section(&ModuleSection(&caller()));
    let mut instances = InstanceSection::new();
    let exports = OPS
        .into_iter()
        .chain([
            "drop-connection",
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
    canonical.lift(16, 1, []);
    component.section(&canonical);
    let mut instances = ComponentInstanceSection::new();
    instances.export_items([("run", ComponentExportKind::Func, 8)]);
    component.section(&instances);
    let mut exports = ComponentExportSection::new();
    exports.export(CONTRACT, ComponentExportKind::Instance, 1, None);
    component.section(&exports);
    let bytes = component.finish();
    wasmparser::Validator::new_with_features(wasmparser::WasmFeatures::all())
        .validate_all(&bytes)
        .unwrap();
    bytes
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
fn memory(port: u16) -> Module {
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
    bytes[1024..1033].copy_from_slice(b"127.0.0.1");
    bytes[1040..1044].copy_from_slice(b"PING");
    bytes[128..132].copy_from_slice(&1024u32.to_le_bytes());
    bytes[132..136].copy_from_slice(&9u32.to_le_bytes());
    bytes[136..138].copy_from_slice(&port.to_le_bytes());
    bytes[164..168].copy_from_slice(&1040u32.to_le_bytes());
    bytes[168..172].copy_from_slice(&4u32.to_le_bytes());
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
            Instruction::Call(16),
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
    reason = "finite encoded guest keeps canonical calls and owner drops in execution order"
)]
fn caller() -> Module {
    let mut module = Module::new();
    let mut types = TypeSection::new();
    for count in [2, 5, 2, 5] {
        types
            .ty()
            .function(vec![ValType::I32; count], [ValType::I32]);
    }
    types.ty().function([ValType::I32; 2], []);
    types.ty().function([ValType::I32; 3], [ValType::I32]);
    types.ty().function([ValType::I32; 2], [ValType::I32]);
    types.ty().function([ValType::I32], []);
    types.ty().function([], [ValType::I32]);
    types.ty().function([ValType::I32], [ValType::I32]);
    module.section(&types);
    let mut imports = ImportSection::new();
    for (name, ty) in OPS.into_iter().zip([0, 1, 2, 3, 4, 5, 6, 6]).chain([
        ("drop-connection", 7),
        ("drop-chunk", 7),
        ("new", 8),
        ("join", 4),
        ("wait", 6),
        ("subtask-drop", 7),
        ("set-drop", 7),
    ]) {
        imports.import("io", name, EntityType::Function(ty));
    }
    imports.import("memory", "memory", EntityType::Memory(memory_type()));
    module.section(&imports);
    let mut functions = FunctionSection::new();
    functions.function(9);
    functions.function(7);
    module.section(&functions);
    let mut exports = ExportSection::new();
    exports.export("run", ExportKind::Func, 15);
    module.section(&exports);
    // 0 scenario, 1 connection, 2 chunk, 3 total, 4 partial result.
    let mut body = Function::new([(4, ValType::I32)]);
    call(&mut body, 0, [Instruction::I32Const(128)]);
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
    mode(&mut body, 1);
    instructions(&mut body, [Instruction::Unreachable, Instruction::End]);
    instructions(
        &mut body,
        [
            Instruction::I32Const(160),
            Instruction::LocalGet(1),
            Instruction::I32Store(mem(0)),
        ],
    );
    mode(&mut body, 4);
    instructions(
        &mut body,
        [
            Instruction::I32Const(168),
            Instruction::I32Const(16385),
            Instruction::I32Store(mem(0)),
        ],
    );
    call(&mut body, 2, [Instruction::I32Const(160)]);
    instructions(
        &mut body,
        [
            Instruction::I32Const(RESULT),
            Instruction::I32Load8U(MemArg { align: 0, ..mem(0) }),
            Instruction::I32Eqz,
            Instruction::If(BlockType::Empty),
            Instruction::Unreachable,
            Instruction::End,
            Instruction::I32Const(RESULT),
            Instruction::I32Load8U(MemArg { align: 0, ..mem(4) }),
            Instruction::LocalSet(4),
        ],
    );
    call(&mut body, 6, [Instruction::LocalGet(1)]);
    require_ok(&mut body);
    instructions(
        &mut body,
        [
            Instruction::LocalGet(4),
            Instruction::Return,
            Instruction::End,
        ],
    );
    call(&mut body, 2, [Instruction::I32Const(160)]);
    require_ok(&mut body);
    instructions(
        &mut body,
        [
            Instruction::I32Const(RESULT),
            Instruction::I32Load(mem(4)),
            Instruction::I32Const(4),
            Instruction::I32Ne,
            Instruction::If(BlockType::Empty),
            Instruction::Unreachable,
            Instruction::End,
        ],
    );
    instructions(
        &mut body,
        [
            Instruction::LocalGet(0),
            Instruction::I32Const(2),
            Instruction::I32Ne,
            Instruction::If(BlockType::Empty),
        ],
    );
    call(
        &mut body,
        5,
        [Instruction::LocalGet(1), Instruction::I32Const(0)],
    );
    require_ok(&mut body);
    instructions(&mut body, [Instruction::End]);
    instructions(
        &mut body,
        [
            Instruction::Block(BlockType::Empty),
            Instruction::Loop(BlockType::Empty),
        ],
    );
    call(
        &mut body,
        1,
        [
            Instruction::LocalGet(1),
            Instruction::I32Const(2),
            Instruction::I32Const(0),
            Instruction::I32Const(0),
        ],
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
            Instruction::LocalSet(2),
        ],
    );
    mode(&mut body, 5);
    call(
        &mut body,
        1,
        [
            Instruction::LocalGet(2),
            Instruction::I32Const(1),
            Instruction::I32Const(0),
            Instruction::I32Const(0),
        ],
    );
    instructions(&mut body, [Instruction::Unreachable, Instruction::End]);
    call(&mut body, 7, [Instruction::LocalGet(2)]);
    require_ok(&mut body);
    instructions(
        &mut body,
        [
            Instruction::LocalGet(3),
            Instruction::I32Const(RESULT),
            Instruction::I32Load(mem(8)),
            Instruction::I32Add,
            Instruction::LocalSet(3),
        ],
    );
    call(&mut body, 7, [Instruction::LocalGet(2)]);
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
            Instruction::Br(0),
            Instruction::End,
            Instruction::End,
        ],
    );
    call(&mut body, 6, [Instruction::LocalGet(1)]);
    require_ok(&mut body);
    mode(&mut body, 6);
    call(&mut body, 6, [Instruction::LocalGet(1)]);
    instructions(&mut body, [Instruction::Unreachable, Instruction::End]);
    instructions(&mut body, [Instruction::LocalGet(3), Instruction::End]);
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
            Instruction::Call(10),
            Instruction::LocalSet(1),
            Instruction::LocalGet(0),
            Instruction::LocalGet(1),
            Instruction::Call(11),
            Instruction::LocalGet(1),
            Instruction::I32Const(768),
            Instruction::Call(12),
            Instruction::Drop,
            Instruction::LocalGet(0),
            Instruction::Call(13),
            Instruction::LocalGet(1),
            Instruction::Call(14),
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

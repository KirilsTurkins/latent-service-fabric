//! Tiny executed resource guest, encoded from the versioned blob WIT.
use wasm_encoder::*;
#[path = "../../../latent-packaging/tests/fixtures/host.rs"]
mod host;
pub const CONTRACT: &str = "tests:local-blobs/api@1.0.0";
pub const CAP: &str = latent_capabilities::broker::blob::BLOB_CAPABILITY;
const ARGS: i32 = 128;
const RESULT: i32 = 512;
const OPS: [&str; 7] = [
    "create",
    "open",
    "write",
    "read",
    "chunk-bytes",
    "seal",
    "close",
];
#[expect(
    clippy::too_many_lines,
    reason = "Finite encoded guest instructions remain in canonical ABI execution order."
)]
pub fn bytes() -> Vec<u8> {
    let mut component = Component::new();
    let spec = latent_core::PHASE3_HOST_ABI_CURRENT.interface(CAP).unwrap();
    let mut types = ComponentTypeSection::new();
    types.instance(&host::interface(spec.wit, spec.interface, None));
    types
        .function()
        .async_(true)
        .params([
            ("which", PrimitiveValType::U32),
            ("handle", PrimitiveValType::U64),
        ])
        .result(Some(PrimitiveValType::U64.into()));
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
    {
        let name = "chunk";
        aliases.alias(Alias::InstanceExport {
            instance: 0,
            kind: ComponentExportKind::Type,
            name,
        });
    }
    component.section(&aliases);
    component.section(&ModuleSection(&memory()));
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
    for function in 0..7 {
        canonical.lower(
            function,
            [
                CanonicalOption::Async,
                CanonicalOption::Memory(0),
                CanonicalOption::Realloc(0),
            ],
        );
    }
    for resource in 2..3 {
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
    canonical.lift(14, 1, []);
    component.section(&canonical);
    let mut instances = ComponentInstanceSection::new();
    instances.export_items([("run", ComponentExportKind::Func, 7)]);
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

fn memory() -> Module {
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
    string(&mut bytes, &mut cursor, ARGS as usize, "text/plain");
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
            Instruction::Call(14),
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

fn expect_error(body: &mut Function) {
    instructions(
        body,
        [
            Instruction::I32Const(RESULT),
            Instruction::I32Load8U(MemArg { align: 0, ..mem(0) }),
            Instruction::I32Eqz,
            Instruction::If(BlockType::Empty),
            Instruction::Unreachable,
            Instruction::End,
        ],
    );
}
#[expect(
    clippy::too_many_lines,
    reason = "Finite guest instructions prove canonical lowering, async waiting and actual handle ownership."
)]
fn caller() -> Module {
    use Instruction::*;
    let mut module = Module::new();
    let mut types = TypeSection::new();
    let i = ValType::I32;
    let l = ValType::I64;
    types.ty().function([i, i, i, l, i], [i]); // create
    types.ty().function([i, i], [i]); // open, chunk bytes, wait
    types.ty().function([l, l, i, i, i], [i]); // write
    types.ty().function([l, l, i, i], [i]); // read
    types.ty().function([l, i], [i]); // seal, close
    types.ty().function([i], []); // drop
    types.ty().function([], [i]); // new
    types.ty().function([i, i], []); // join
    types.ty().function([i, l], [l]); // run
    module.section(&types);
    let mut imports = ImportSection::new();
    for (name, ty) in OPS.into_iter().zip([0, 1, 2, 3, 1, 4, 4]).chain([
        ("drop-chunk", 5),
        ("new", 6),
        ("join", 7),
        ("wait", 1),
        ("subtask-drop", 5),
        ("set-drop", 5),
    ]) {
        imports.import("io", name, EntityType::Function(ty));
    }
    imports.import("memory", "memory", EntityType::Memory(memory_type()));
    module.section(&imports);
    let mut functions = FunctionSection::new();
    functions.function(8);
    functions.function(5);
    module.section(&functions);
    let mut exports = ExportSection::new();
    exports.export("run", ExportKind::Func, 13);
    module.section(&exports);
    // 0 mode, 1 foreign u64, 2 writer u64, 3 reader u64, 4 chunk u32, 5 sum u32.
    let mut body = Function::new([(2, l), (2, i)]);
    mode(&mut body, 4);
    call(&mut body, 6, [LocalGet(1)]);
    expect_error(&mut body);
    instructions(&mut body, [I64Const(4444), Return, End]);
    // Exact expected zero for mode 9; otherwise eight bytes.
    call(
        &mut body,
        0,
        [
            I32Const(1024),
            I32Const(10),
            I32Const(1),
            I64Const(0),
            I64Const(8),
            LocalGet(0),
            I32Const(9),
            I32Eq,
            Select,
        ],
    );
    instructions(
        &mut body,
        [
            I32Const(RESULT),
            I32Load8U(MemArg { align: 0, ..mem(0) }),
            If(BlockType::Empty),
            I64Const(1000),
            Return,
            End,
            I32Const(RESULT),
            I64Load(mem(8)),
            LocalSet(2),
        ],
    );
    mode(&mut body, 1);
    call(&mut body, 6, [LocalGet(2)]);
    require_ok(&mut body);
    call(&mut body, 6, [LocalGet(2)]);
    expect_error(&mut body);
    instructions(&mut body, [I64Const(0), Return, End]);
    mode(&mut body, 3);
    instructions(&mut body, [LocalGet(2), Return, End]);
    mode(&mut body, 5);
    call(&mut body, 3, [LocalGet(2), I64Const(0), I32Const(0)]);
    expect_error(&mut body);
    instructions(&mut body, [I64Const(5555), Return, End]);
    instructions(
        &mut body,
        [LocalGet(0), I32Const(9), I32Ne, If(BlockType::Empty)],
    );
    for offset in [0, 4] {
        call(
            &mut body,
            2,
            [
                LocalGet(2),
                I64Const(offset),
                I32Const(960 + i32::try_from(offset).unwrap()),
                I32Const(4),
            ],
        );
        require_ok(&mut body);
    }
    instructions(&mut body, [End]);
    mode(&mut body, 2);
    instructions(&mut body, [Unreachable, End]);
    call(&mut body, 5, [LocalGet(2)]);
    require_ok(&mut body);
    // The result's reference record is aligned at byte 8; open has >4 flat
    // async parameters and therefore consumes a pointer to that record.
    call(&mut body, 1, [I32Const(RESULT + 8)]);
    require_ok(&mut body);
    instructions(&mut body, [I32Const(RESULT), I64Load(mem(8)), LocalSet(3)]);
    call(
        &mut body,
        3,
        [
            LocalGet(3),
            I64Const(0),
            I64Const(4),
            LocalGet(0),
            I32Const(9),
            I32Eq,
            Select,
            I32Const(0),
            I32Const(4),
            LocalGet(0),
            I32Const(9),
            I32Eq,
            Select,
        ],
    );
    require_ok(&mut body);
    instructions(&mut body, [I32Const(RESULT), I32Load(mem(4)), LocalSet(4)]);
    mode(&mut body, 8);
    instructions(&mut body, [Unreachable, End]);
    mode(&mut body, 7);
    call(&mut body, 4, [I32Const(-1)]);
    instructions(&mut body, [Unreachable, End]);
    call(&mut body, 4, [LocalGet(4)]);
    require_ok(&mut body);
    instructions(&mut body, [I32Const(RESULT), I32Load(mem(8)), LocalSet(5)]);
    instructions(
        &mut body,
        [
            LocalGet(5),
            If(BlockType::Empty),
            LocalGet(5),
            I32Const(1000),
            I32Mul,
            I32Const(RESULT),
            I32Load(mem(4)),
            I32Load8U(MemArg { align: 0, ..mem(0) }),
            I32Add,
            LocalSet(5),
            End,
        ],
    );
    call(&mut body, 4, [LocalGet(4)]);
    expect_error(&mut body);
    instructions(&mut body, [LocalGet(4), Call(7)]);
    call(&mut body, 6, [LocalGet(3)]);
    require_ok(&mut body);
    call(&mut body, 6, [LocalGet(2)]);
    expect_error(&mut body);
    instructions(&mut body, [LocalGet(5), I64ExtendI32U, End]);
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
            Instruction::Call(8),
            Instruction::LocalSet(1),
            Instruction::LocalGet(0),
            Instruction::LocalGet(1),
            Instruction::Call(9),
            Instruction::LocalGet(1),
            Instruction::I32Const(768),
            Instruction::Call(10),
            Instruction::Drop,
            Instruction::LocalGet(0),
            Instruction::Call(11),
            Instruction::LocalGet(1),
            Instruction::Call(12),
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

//! Maintained canonical-async HTTP guest; generated from the frozen host WIT.
use wasm_encoder::*;
#[path = "../../../latent-packaging/tests/fixtures/host.rs"]
mod host;
pub const CONTRACT: &str = "tests:http/api@1.0.0";
pub const CAP: &str = latent_capabilities::broker::http::HTTP_CAPABILITY;
const ARGS: i32 = 128;
const RESULT: i32 = 512;

pub fn bytes(url: &str) -> Vec<u8> {
    let mut component = Component::new();
    let spec = latent_core::PHASE3_HOST_ABI_V2.interface(CAP).unwrap();
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
        name: "send",
    });
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
    canonical.waitable_set_wait(0);
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
    bytes[base + 20] = 1;
    string(&mut bytes, &mut cursor, base + 24, "payload");
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
    for instruction in [
        Instruction::LocalGet(0),
        Instruction::I32Const(7),
        Instruction::I32LtU,
        Instruction::If(BlockType::Empty),
        Instruction::I32Const(ARGS),
        Instruction::LocalGet(0),
        Instruction::I32Store8(MemArg { align: 0, ..mem(0) }),
        Instruction::End,
        Instruction::I32Const(ARGS),
        Instruction::I32Const(RESULT),
        Instruction::Call(0),
        Instruction::Call(7),
        Instruction::LocalGet(0),
        Instruction::I32Const(8),
        Instruction::I32Eq,
        Instruction::If(BlockType::Empty),
        Instruction::Unreachable,
        Instruction::End,
        Instruction::I32Const(RESULT),
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
    let mut read = Function::new([]);
    for instruction in [
        Instruction::LocalGet(0),
        Instruction::I32Load8U(MemArg { align: 0, ..mem(0) }),
        Instruction::I32Eqz,
        Instruction::If(BlockType::Result(ValType::I32)),
        Instruction::LocalGet(0),
        Instruction::I32Load16U(MemArg { align: 1, ..mem(4) }),
        Instruction::LocalGet(0),
        Instruction::I32Load(mem(20)),
        Instruction::I32Const(1000),
        Instruction::I32Mul,
        Instruction::I32Add,
        Instruction::Else,
        Instruction::I32Const(1000),
        Instruction::LocalGet(0),
        Instruction::I32Load8U(MemArg { align: 0, ..mem(4) }),
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

/// A finite real canonical string-return component; no WAT or guest allocator.
pub fn utf8_view_bytes() -> Vec<u8> {
    let forms = [
        ("utf8", None, 64u32, 7u32),
        ("utf16", Some(CanonicalOption::UTF16), 80, 3),
        ("latin1", Some(CanonicalOption::CompactUTF16), 96, 2),
        (
            "tagged-utf16",
            Some(CanonicalOption::CompactUTF16),
            80,
            (1 << 31) | 3,
        ),
        ("empty", None, 65536, 0),
        ("malformed", Some(CanonicalOption::UTF16), 112, 1),
        ("unaligned", Some(CanonicalOption::UTF16), 81, 1),
        ("out-of-bounds", None, 65535, 8),
    ];
    let mut payload = [0u8; 128];
    for (index, (_, _, pointer, length)) in forms.iter().enumerate() {
        payload[index * 8..index * 8 + 4].copy_from_slice(&pointer.to_le_bytes());
        payload[index * 8 + 4..index * 8 + 8].copy_from_slice(&length.to_le_bytes());
    }
    payload[64..71].copy_from_slice(b"a\xc3\xa9\xf0\x9d\x84\x9e");
    payload[80..86].copy_from_slice(&[0xe9, 0, 0x34, 0xd8, 0x1e, 0xdd]);
    payload[96..98].copy_from_slice(&[0xe9, 0xff]);
    payload[112..114].copy_from_slice(&[0, 0xd8]);
    let mut module = Module::new();
    let mut types = TypeSection::new();
    types.ty().function([], [ValType::I32]);
    module.section(&types);
    let mut functions = FunctionSection::new();
    for _ in forms {
        functions.function(0);
    }
    module.section(&functions);
    let mut memories = MemorySection::new();
    memories.memory(MemoryType {
        minimum: 1,
        maximum: Some(1),
        memory64: false,
        shared: false,
        page_size_log2: None,
    });
    module.section(&memories);
    let mut exports = ExportSection::new();
    exports.export("memory", ExportKind::Memory, 0);
    for (index, (name, _, _, _)) in forms.iter().enumerate() {
        exports.export(name, ExportKind::Func, u32::try_from(index).unwrap());
    }
    module.section(&exports);
    let mut code = CodeSection::new();
    for index in 0..forms.len() {
        let mut function = Function::new([]);
        function.instruction(&Instruction::I32Const(i32::try_from(index * 8).unwrap()));
        function.instruction(&Instruction::End);
        code.function(&function);
    }
    module.section(&code);
    let mut data = DataSection::new();
    data.active(0, &ConstExpr::i32_const(0), payload);
    module.section(&data);
    let mut component = Component::new();
    let mut types = ComponentTypeSection::new();
    types
        .function()
        .params([] as [(&str, PrimitiveValType); 0])
        .result(Some(PrimitiveValType::String.into()));
    component.section(&types);
    component.section(&ModuleSection(&module));
    let mut instances = InstanceSection::new();
    instances.instantiate(0, [] as [(&str, ModuleArg); 0]);
    component.section(&instances);
    let mut aliases = ComponentAliasSection::new();
    aliases.alias(Alias::CoreInstanceExport {
        instance: 0,
        kind: ExportKind::Memory,
        name: "memory",
    });
    for (name, _, _, _) in forms {
        aliases.alias(Alias::CoreInstanceExport {
            instance: 0,
            kind: ExportKind::Func,
            name,
        });
    }
    component.section(&aliases);
    let mut functions = CanonicalFunctionSection::new();
    for (index, (_, encoding, _, _)) in forms.iter().enumerate() {
        let mut options = vec![CanonicalOption::Memory(0)];
        if let Some(encoding) = encoding {
            options.push(*encoding);
        }
        functions.lift(u32::try_from(index).unwrap(), 0, options);
    }
    component.section(&functions);
    let mut exports = ComponentExportSection::new();
    for (index, (name, _, _, _)) in forms.iter().enumerate() {
        exports.export(
            name,
            ComponentExportKind::Func,
            u32::try_from(index).unwrap(),
            None,
        );
    }
    component.section(&exports);
    component.finish()
}

//! Actual sync-WIT publisher: return sequence/duplicate marker or typed error.
use wasm_encoder::*;
#[path = "../../../latent-packaging/tests/fixtures/host.rs"]
mod host;
pub const CONTRACT: &str = "tests:nats-events/api@1.0.0";
pub const CAP: &str = latent_capabilities::broker::events::EVENTS_CAPABILITY;

pub fn bytes() -> Vec<u8> {
    let mut component = Component::new();
    let specification = latent_core::PHASE3_HOST_ABI_CURRENT.interface(CAP).unwrap();
    let mut types = ComponentTypeSection::new();
    types.instance(&host::interface(specification.wit, CAP, None));
    types
        .function()
        .params([("which", PrimitiveValType::U32)])
        .result(Some(PrimitiveValType::U64.into()));
    component.section(&types);
    let mut imports = ComponentImportSection::new();
    imports.import(CAP, ComponentTypeRef::Instance(0));
    component.section(&imports);
    let mut aliases = ComponentAliasSection::new();
    aliases.alias(Alias::InstanceExport {
        instance: 0,
        kind: ComponentExportKind::Func,
        name: "publish",
    });
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
    canonical.lower(0, [CanonicalOption::Memory(0), CanonicalOption::Realloc(0)]);
    component.section(&canonical);
    component.section(&ModuleSection(&caller()));
    let mut instances = InstanceSection::new();
    instances.export_items([("publish", ExportKind::Func, 1)]);
    instances.instantiate(
        1,
        [
            ("event", ModuleArg::Instance(1)),
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
    canonical.lift(2, 1, []);
    component.section(&canonical);
    let mut instances = ComponentInstanceSection::new();
    instances.export_items([("run", ComponentExportKind::Func, 1)]);
    component.section(&instances);
    let mut exports = ComponentExportSection::new();
    exports.export(CONTRACT, ComponentExportKind::Instance, 1, None);
    component.section(&exports);
    component.finish()
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
    memories.memory(MemoryType {
        minimum: 2,
        maximum: Some(4),
        memory64: false,
        shared: false,
        page_size_log2: None,
    });
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
    let mut data = DataSection::new();
    for (index, name) in [
        "allowed",
        "broker-denied",
        "denied",
        "tenant-only",
        "allowed",
    ]
    .iter()
    .enumerate()
    {
        data.active(
            0,
            &ConstExpr::i32_const(128 + i32::try_from(index).unwrap() * 32),
            name.as_bytes().iter().copied(),
        );
    }
    data.active(
        0,
        &ConstExpr::i32_const(320),
        b"synthetic-event".iter().copied(),
    );
    data.active(0, &ConstExpr::i32_const(352), b"text/plain".iter().copied());
    data.active(0, &ConstExpr::i32_const(448), b"guest-key".iter().copied());
    let mut attributes = Vec::new();
    for n in [420_u32, 6, 432, 7] {
        attributes.extend_from_slice(&n.to_le_bytes());
    }
    data.active(0, &ConstExpr::i32_const(400), attributes);
    data.active(0, &ConstExpr::i32_const(420), b"source".iter().copied());
    data.active(0, &ConstExpr::i32_const(432), b"fixture".iter().copied());
    module.section(&data);
    module
}
#[expect(
    clippy::too_many_lines,
    reason = "finite canonical ABI guest instructions remain in execution order"
)]
fn caller() -> Module {
    let mut module = Module::new();
    let mut types = TypeSection::new();
    types.ty().function([ValType::I32; 14], []);
    types.ty().function([ValType::I32], [ValType::I64]);
    module.section(&types);
    let mut imports = ImportSection::new();
    imports.import("event", "publish", EntityType::Function(0));
    imports.import(
        "memory",
        "memory",
        EntityType::Memory(MemoryType {
            minimum: 2,
            maximum: Some(4),
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
    exports.export("run", ExportKind::Func, 1);
    module.section(&exports);
    let mut f = Function::new([(2, ValType::I32)]);
    f.instruction(&Instruction::I32Const(128));
    f.instruction(&Instruction::LocalSet(1));
    f.instruction(&Instruction::I32Const(7));
    f.instruction(&Instruction::LocalSet(2));
    for (which, length) in [(1, 13), (2, 6), (3, 11), (4, 7)] {
        for i in [
            Instruction::LocalGet(0),
            Instruction::I32Const(which),
            Instruction::I32Eq,
            Instruction::If(BlockType::Empty),
            Instruction::I32Const(128 + which * 32),
            Instruction::LocalSet(1),
            Instruction::I32Const(length),
            Instruction::LocalSet(2),
            Instruction::End,
        ] {
            f.instruction(&i);
        }
    }
    for i in [
        Instruction::LocalGet(1),
        Instruction::LocalGet(2),
        Instruction::I32Const(0),
        Instruction::I32Const(0),
        Instruction::I32Const(0),
        Instruction::I32Const(320),
        Instruction::I32Const(15),
        Instruction::I32Const(352),
        Instruction::I32Const(10),
        Instruction::I32Const(400),
        Instruction::I32Const(1),
        Instruction::I32Const(448),
        Instruction::I32Const(9),
        Instruction::I32Const(512),
        Instruction::Call(0),
    ] {
        f.instruction(&i);
    }
    for i in [
        Instruction::LocalGet(0),
        Instruction::I32Const(6),
        Instruction::I32Eq,
        Instruction::If(BlockType::Empty),
        Instruction::Unreachable,
        Instruction::End,
    ] {
        f.instruction(&i);
    }
    for i in [
        Instruction::LocalGet(0),
        Instruction::I32Const(5),
        Instruction::I32Eq,
        Instruction::If(BlockType::Empty),
        Instruction::LocalGet(1),
        Instruction::LocalGet(2),
        Instruction::I32Const(0),
        Instruction::I32Const(0),
        Instruction::I32Const(0),
        Instruction::I32Const(320),
        Instruction::I32Const(15),
        Instruction::I32Const(352),
        Instruction::I32Const(10),
        Instruction::I32Const(400),
        Instruction::I32Const(1),
        Instruction::I32Const(448),
        Instruction::I32Const(9),
        Instruction::I32Const(512),
        Instruction::Call(0),
        Instruction::End,
    ] {
        f.instruction(&i);
    }
    let load = |offset| MemArg {
        offset,
        align: 0,
        memory_index: 0,
    };
    for i in [
        Instruction::I32Const(512),
        Instruction::I32Load8U(load(0)),
        Instruction::If(BlockType::Result(ValType::I64)),
        Instruction::I32Const(512),
        Instruction::I32Load8U(load(8)),
        Instruction::I64ExtendI32U,
        Instruction::I64Const(1000),
        Instruction::I64Add,
        Instruction::Else,
        Instruction::I32Const(512),
        Instruction::I64Load(load(32)),
        Instruction::I64Const(1),
        Instruction::I64Shl,
        Instruction::I32Const(512),
        Instruction::I32Load8U(load(40)),
        Instruction::I64ExtendI32U,
        Instruction::I64Or,
        Instruction::End,
        Instruction::End,
    ] {
        f.instruction(&i);
    }
    let mut code = CodeSection::new();
    code.function(&f);
    module.section(&code);
    module
}

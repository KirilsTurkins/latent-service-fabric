//! The real versioned ABI, canonical async subtasks and one bounded guest
//! memory. This fixture owns its small logical scheduler; it does not qualify
//! a Java, Rust or other language scheduler.
use wasm_encoder::*;
#[path = "../../../../latent-packaging/tests/fixtures/host.rs"]
mod host;

const REGISTER: u32 = 0;
const PARK: u32 = 1;
const WAKE: u32 = 2;
const SETTLE: u32 = 3;
const CLOSE: u32 = 4;
const OBSERVE: u32 = 5;
const WAIT_FOR: u32 = 6;
const WAIT_UNTIL: u32 = 7;
const TIMER_START: u32 = 8;
const TIMER_NEXT: u32 = 9;
const TIMER_STOP: u32 = 10;
const NEW_SET: u32 = 11;
const JOIN: u32 = 12;
const WAIT: u32 = 13;
const DROP_SUBTASK: u32 = 14;
const DROP_SET: u32 = 15;
const PRIMARY: i32 = 64;
const SECOND: i32 = 96;
const THIRD: i32 = 128;
const FOURTH: i32 = 160;
const UNIT: i32 = 192;
const ASYNC_RESULT: i32 = 224;
const OBSERVATION: i32 = 256;

pub fn bytes() -> Vec<u8> {
    let spec = latent_core::PHASE3_HOST_ABI_CURRENT
        .interface(super::super::packages::ACTIVATION)
        .unwrap();
    let mut component = Component::new();
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
    let names = [
        "register",
        "park",
        "wake",
        "settle",
        "close",
        "observe",
        "wait-for",
        "wait-until",
        "timer-start",
        "timer-next",
        "timer-stop",
    ];
    let mut aliases = ComponentAliasSection::new();
    for name in names {
        aliases.alias(Alias::InstanceExport {
            instance: 0,
            kind: ComponentExportKind::Func,
            name,
        });
    }
    component.section(&aliases);
    let mut memory = Module::new();
    let mut memories = MemorySection::new();
    memories.memory(memory_type());
    memory.section(&memories);
    let mut exports = ExportSection::new();
    exports.export("memory", ExportKind::Memory, 0);
    memory.section(&exports);
    component.section(&ModuleSection(&memory));
    let mut instances = InstanceSection::new();
    instances.instantiate(0, [] as [(&str, ModuleArg); 0]);
    component.section(&instances);
    let mut aliases = ComponentAliasSection::new();
    aliases.alias(Alias::CoreInstanceExport {
        instance: 0,
        kind: ExportKind::Memory,
        name: "memory",
    });
    component.section(&aliases);
    let mut canonical = CanonicalFunctionSection::new();
    for function in 0..11 {
        if [6, 7, 9].contains(&function) {
            canonical.lower(
                function,
                [CanonicalOption::Async, CanonicalOption::Memory(0)],
            );
        } else {
            canonical.lower(function, [CanonicalOption::Memory(0)]);
        }
    }
    canonical.waitable_set_new();
    canonical.waitable_join();
    canonical.waitable_set_wait(0);
    canonical.subtask_drop();
    canonical.waitable_set_drop();
    component.section(&canonical);
    component.section(&ModuleSection(&guest()));
    let mut instances = InstanceSection::new();
    instances.export_items(
        names
            .into_iter()
            .enumerate()
            .map(|(index, name)| (name, ExportKind::Func, u32::try_from(index).unwrap()))
            .chain([
                ("new", ExportKind::Func, NEW_SET),
                ("join", ExportKind::Func, JOIN),
                ("wait", ExportKind::Func, WAIT),
                ("subtask-drop", ExportKind::Func, DROP_SUBTASK),
                ("set-drop", ExportKind::Func, DROP_SET),
            ])
            .collect::<Vec<_>>(),
    );
    instances.instantiate(
        1,
        [
            ("runtime", ModuleArg::Instance(1)),
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
    instances.export_items([("run", ComponentExportKind::Func, 11)]);
    component.section(&instances);
    let mut exports = ComponentExportSection::new();
    exports.export(
        super::super::component::CALLER,
        ComponentExportKind::Instance,
        1,
        None,
    );
    component.section(&exports);
    component.finish()
}

const fn memory_type() -> MemoryType {
    MemoryType {
        minimum: 4,
        maximum: Some(64),
        memory64: false,
        shared: false,
        page_size_log2: None,
    }
}
fn emit(body: &mut Function, instructions: impl IntoIterator<Item = Instruction<'static>>) {
    for instruction in instructions {
        body.instruction(&instruction);
    }
}
fn load(body: &mut Function, address: i32, width: u8) {
    body.instruction(&Instruction::I32Const(address));
    let memory = MemArg {
        offset: 0,
        align: if width == 8 {
            3
        } else if width == 4 {
            2
        } else {
            0
        },
        memory_index: 0,
    };
    body.instruction(&match width {
        8 => Instruction::I64Load(memory),
        4 => Instruction::I32Load(memory),
        _ => Instruction::I32Load8U(memory),
    });
}
fn require(body: &mut Function) {
    emit(
        body,
        [
            Instruction::I32Eqz,
            Instruction::If(BlockType::Empty),
            Instruction::Unreachable,
            Instruction::End,
        ],
    );
}
fn success(body: &mut Function, address: i32) {
    load(body, address, 1);
    body.instruction(&Instruction::I32Eqz);
    require(body);
}
fn error(body: &mut Function, address: i32, offset: i32, expected: i32) {
    load(body, address, 1);
    emit(body, [Instruction::I32Const(1), Instruction::I32Eq]);
    require(body);
    load(body, address + offset, 1);
    emit(body, [Instruction::I32Const(expected), Instruction::I32Eq]);
    require(body);
}
fn register(body: &mut Function, kind: i32, continuation: bool, address: i32) {
    emit(
        body,
        [
            Instruction::I32Const(kind),
            Instruction::I32Const(i32::from(continuation)),
        ],
    );
    if continuation {
        emit(body, [Instruction::LocalGet(1), Instruction::LocalGet(2)]);
    } else {
        emit(body, [Instruction::I64Const(0), Instruction::I64Const(0)]);
    }
    emit(
        body,
        [Instruction::I32Const(address), Instruction::Call(REGISTER)],
    );
}
fn token(body: &mut Function, function: u32, address: Option<i32>) {
    if let Some(address) = address {
        load(body, address + 8, 8);
        load(body, address + 16, 8);
    } else {
        emit(body, [Instruction::LocalGet(1), Instruction::LocalGet(2)]);
    }
    emit(
        body,
        [Instruction::I32Const(UNIT), Instruction::Call(function)],
    );
}
fn settled(body: &mut Function, address: Option<i32>) {
    token(body, SETTLE, address);
    success(body, UNIT);
}
fn remember(body: &mut Function, address: i32) {
    load(body, address + 8, 8);
    body.instruction(&Instruction::LocalSet(1));
    load(body, address + 16, 8);
    body.instruction(&Instruction::LocalSet(2));
}
fn case(body: &mut Function, which: i32, action: impl FnOnce(&mut Function)) {
    emit(
        body,
        [
            Instruction::LocalGet(0),
            Instruction::I32Const(which),
            Instruction::I32Eq,
            Instruction::If(BlockType::Empty),
        ],
    );
    action(body);
    body.instruction(&Instruction::End);
}
fn timer(body: &mut Function, delay: i64, period: Option<i64>, address: i32) {
    emit(
        body,
        [
            Instruction::I64Const(delay),
            Instruction::I32Const(i32::from(period.is_some())),
            Instruction::I64Const(period.unwrap_or(0)),
            Instruction::I32Const(1),
            Instruction::LocalGet(1),
            Instruction::LocalGet(2),
            Instruction::I32Const(address),
            Instruction::Call(TIMER_START),
        ],
    );
}
fn stop_timer(body: &mut Function, address: i32) {
    token(body, TIMER_STOP, Some(address));
    success(body, UNIT);
}
fn begin_next(body: &mut Function, address: i32) {
    load(body, address + 8, 8);
    load(body, address + 16, 8);
    emit(
        body,
        [
            Instruction::I32Const(ASYNC_RESULT),
            Instruction::Call(TIMER_NEXT),
            Instruction::LocalSet(3),
        ],
    );
}
fn finish_wait(body: &mut Function) {
    emit(
        body,
        [
            Instruction::LocalGet(3),
            Instruction::I32Const(15),
            Instruction::I32And,
            Instruction::I32Const(1),
            Instruction::I32Eq,
            Instruction::If(BlockType::Empty),
            Instruction::LocalGet(3),
            Instruction::I32Const(4),
            Instruction::I32ShrU,
            Instruction::LocalSet(4),
            Instruction::Call(NEW_SET),
            Instruction::LocalSet(5),
            Instruction::LocalGet(4),
            Instruction::LocalGet(5),
            Instruction::Call(JOIN),
            Instruction::LocalGet(5),
            Instruction::I32Const(0),
            Instruction::Call(WAIT),
            Instruction::Drop,
            Instruction::LocalGet(4),
            Instruction::Call(DROP_SUBTASK),
            Instruction::LocalGet(5),
            Instruction::Call(DROP_SET),
            Instruction::Else,
            Instruction::LocalGet(3),
            Instruction::I32Const(15),
            Instruction::I32And,
            Instruction::I32Const(2),
            Instruction::I32Eq,
        ],
    );
    require(body);
    body.instruction(&Instruction::End);
}

#[expect(
    clippy::too_many_lines,
    reason = "small explicit ABI cases share one checked binary component"
)]
fn guest() -> Module {
    let mut module = Module::new();
    let mut types = TypeSection::new();
    types.ty().function(
        [
            ValType::I32,
            ValType::I32,
            ValType::I64,
            ValType::I64,
            ValType::I32,
        ],
        [],
    ); // register
    types
        .ty()
        .function([ValType::I64, ValType::I64, ValType::I32], []); // token
    types.ty().function([ValType::I32], []); // unit result
    types.ty().function(
        [
            ValType::I64,
            ValType::I32,
            ValType::I64,
            ValType::I64,
            ValType::I32,
        ],
        [ValType::I32],
    ); // async wait
    types.ty().function(
        [
            ValType::I64,
            ValType::I32,
            ValType::I64,
            ValType::I32,
            ValType::I64,
            ValType::I64,
            ValType::I32,
        ],
        [],
    ); // timer
    types
        .ty()
        .function([ValType::I64, ValType::I64, ValType::I32], [ValType::I32]); // timer next
    types.ty().function([], [ValType::I32]);
    types.ty().function([ValType::I32, ValType::I32], []);
    types
        .ty()
        .function([ValType::I32, ValType::I32], [ValType::I32]);
    types.ty().function([ValType::I32], []);
    types.ty().function([ValType::I32], [ValType::I32]);
    module.section(&types);
    let mut imports = ImportSection::new();
    for (name, ty) in [
        ("register", 0),
        ("park", 1),
        ("wake", 1),
        ("settle", 1),
        ("close", 2),
        ("observe", 2),
        ("wait-for", 3),
        ("wait-until", 3),
        ("timer-start", 4),
        ("timer-next", 5),
        ("timer-stop", 1),
        ("new", 6),
        ("join", 7),
        ("wait", 8),
        ("subtask-drop", 9),
        ("set-drop", 9),
    ] {
        imports.import("runtime", name, EntityType::Function(ty));
    }
    imports.import("memory", "memory", EntityType::Memory(memory_type()));
    module.section(&imports);
    let mut functions = FunctionSection::new();
    functions.function(10);
    module.section(&functions);
    let mut exports = ExportSection::new();
    exports.export("run", ExportKind::Func, 16);
    module.section(&exports);
    let mut body = Function::new([(2, ValType::I64), (4, ValType::I32)]);
    case(&mut body, 15, |b| {
        emit(b, [Instruction::I32Const(0), Instruction::Return])
    });
    case(&mut body, 23, |b| {
        register(b, 0, false, PRIMARY);
        error(b, PRIMARY, 8, 2);
        emit(b, [Instruction::I32Const(42), Instruction::Return]);
    });
    // Managed idle status is descriptive only; it cannot settle accepted work.
    emit(
        &mut body,
        [
            Instruction::LocalGet(0),
            Instruction::I32Const(2),
            Instruction::I32Eq,
            Instruction::If(BlockType::Result(ValType::I32)),
            Instruction::I32Const(1),
            Instruction::Else,
            Instruction::I32Const(0),
            Instruction::End,
            Instruction::I32Const(0),
            Instruction::I64Const(0),
            Instruction::I64Const(0),
            Instruction::I32Const(PRIMARY),
            Instruction::Call(REGISTER),
        ],
    );
    success(&mut body, PRIMARY);
    remember(&mut body, PRIMARY);
    for mode in [1, 2] {
        case(&mut body, mode, |b| {
            emit(b, [Instruction::I32Const(42), Instruction::Return])
        });
    }
    case(&mut body, 3, |b| {
        b.instruction(&Instruction::Unreachable);
    });
    case(&mut body, 0, |b| {
        token(b, PARK, None);
        success(b, UNIT);
        token(b, WAKE, None);
        success(b, UNIT);
    });
    case(&mut body, 4, |b| {
        register(b, 0, false, SECOND);
        success(b, SECOND);
        register(b, 0, false, THIRD);
        error(b, THIRD, 8, 2);
        settled(b, Some(SECOND));
    });
    case(&mut body, 5, |b| {
        emit(b, [Instruction::I32Const(UNIT), Instruction::Call(CLOSE)]);
        success(b, UNIT);
        register(b, 0, false, SECOND);
        error(b, SECOND, 8, 3);
        register(b, 3, true, SECOND);
        success(b, SECOND);
        settled(b, Some(SECOND));
    });
    case(&mut body, 6, |b| {
        settled(b, None);
        register(b, 0, false, SECOND);
        success(b, SECOND);
        token(b, WAKE, None);
        error(b, UNIT, 1, 6);
        remember(b, SECOND);
    });
    case(&mut body, 7, |b| {
        emit(
            b,
            [
                Instruction::Loop(BlockType::Empty),
                Instruction::Br(0),
                Instruction::End,
            ],
        )
    });
    for mode in [8, 11] {
        case(&mut body, mode, |b| {
            token(b, PARK, None);
            success(b, UNIT);
            emit(
                b,
                [
                    Instruction::I64Const(if mode == 8 {
                        50_000_000
                    } else {
                        60_000_000_000
                    }),
                    Instruction::I32Const(1),
                    Instruction::LocalGet(1),
                    Instruction::LocalGet(2),
                    Instruction::I32Const(ASYNC_RESULT),
                    Instruction::Call(WAIT_FOR),
                    Instruction::LocalSet(3),
                ],
            );
            // Same Store performs runnable sibling work before awaiting the parked
            // task. The async host timer cannot retain an exclusive Store borrow.
            register(b, 0, false, SECOND);
            success(b, SECOND);
            emit(
                b,
                [
                    Instruction::I32Const(OBSERVATION),
                    Instruction::Call(OBSERVE),
                ],
            );
            success(b, OBSERVATION);
            load(b, OBSERVATION + 12, 4);
            emit(b, [Instruction::I32Const(2), Instruction::I32Eq]);
            require(b);
            load(b, OBSERVATION + 40, 4);
            emit(b, [Instruction::I32Const(1), Instruction::I32Eq]);
            require(b);
            settled(b, Some(SECOND));
            finish_wait(b);
            success(b, ASYNC_RESULT);
            token(b, WAKE, None);
            success(b, UNIT);
        });
    }
    case(&mut body, 9, |b| {
        timer(b, 0, Some(1), SECOND);
        success(b, SECOND);
        begin_next(b, SECOND);
        finish_wait(b);
        success(b, ASYNC_RESULT);
        load(b, ASYNC_RESULT + 8, 8);
        emit(b, [Instruction::I64Const(0), Instruction::I64GtU]);
        require(b);
        stop_timer(b, SECOND);
    });
    case(&mut body, 10, |b| {
        timer(b, 60_000_000_000, None, SECOND);
        success(b, SECOND);
        begin_next(b, SECOND);
        stop_timer(b, SECOND);
        finish_wait(b);
        error(b, ASYNC_RESULT, 8, 3);
    });
    case(&mut body, 12, |b| {
        timer(b, 60_000_000_000, None, SECOND);
        success(b, SECOND);
        timer(b, 60_000_000_000, None, THIRD);
        success(b, THIRD);
        timer(b, 60_000_000_000, None, FOURTH);
        error(b, FOURTH, 8, 2);
        stop_timer(b, SECOND);
        stop_timer(b, THIRD);
    });
    case(&mut body, 13, |b| {
        // An already elapsed wall instant is sampled once and succeeds under
        // the same original monotonic deadline, without a sleeping worker.
        emit(
            b,
            [
                Instruction::I64Const(1),
                Instruction::I32Const(1),
                Instruction::LocalGet(1),
                Instruction::LocalGet(2),
                Instruction::I32Const(ASYNC_RESULT),
                Instruction::Call(WAIT_UNTIL),
                Instruction::LocalSet(3),
            ],
        );
        finish_wait(b);
        success(b, ASYNC_RESULT);
    });
    case(&mut body, 25, |b| {
        // A policy may bound this accepted wait more tightly than the root.
        // Its deadline is a WIT result, and settling the task remains possible.
        emit(
            b,
            [
                Instruction::I64Const(1_000_000_000),
                Instruction::I32Const(1),
                Instruction::LocalGet(1),
                Instruction::LocalGet(2),
                Instruction::I32Const(ASYNC_RESULT),
                Instruction::Call(WAIT_FOR),
                Instruction::LocalSet(3),
            ],
        );
        finish_wait(b);
        error(b, ASYNC_RESULT, 1, 4);
    });
    for (mode, kind) in [(16, 2), (17, 3), (18, 4), (19, 5), (20, 6), (21, 7)] {
        case(&mut body, mode, |b| {
            register(b, kind, false, SECOND);
            success(b, SECOND);
            register(b, kind, false, THIRD);
            success(b, THIRD);
            register(b, kind, false, FOURTH);
            error(b, FOURTH, 8, 2);
            settled(b, Some(SECOND));
            settled(b, Some(THIRD));
        });
    }
    case(&mut body, 22, |b| {
        register(b, 1, false, SECOND);
        success(b, SECOND);
        register(b, 1, false, THIRD);
        error(b, THIRD, 8, 2);
        settled(b, Some(SECOND));
    });
    case(&mut body, 24, |b| {
        // Even the module's admitted maximum cannot exceed the original
        // activation ledger once linear memory and native owners are combined.
        emit(
            b,
            [
                Instruction::I32Const(60),
                Instruction::MemoryGrow(0),
                Instruction::Drop,
            ],
        );
    });
    settled(&mut body, None);
    emit(
        &mut body,
        [Instruction::I32Const(UNIT), Instruction::Call(CLOSE)],
    );
    success(&mut body, UNIT);
    emit(
        &mut body,
        [
            Instruction::LocalGet(0),
            Instruction::I32Const(14),
            Instruction::I32Eq,
            Instruction::If(BlockType::Result(ValType::I32)),
            Instruction::LocalGet(1),
            Instruction::I32WrapI64,
            Instruction::Else,
            Instruction::I32Const(42),
            Instruction::End,
            Instruction::End,
        ],
    );
    let mut code = CodeSection::new();
    code.function(&body);
    module.section(&code);
    module
}

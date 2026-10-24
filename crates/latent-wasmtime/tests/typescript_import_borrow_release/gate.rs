//! Source-only finite P3 borrow-release fixture; not a production stream adapter.
//!
//! Encode with the workspace wasm-encoder/wasmparser 0.261.0. The imported
//! PHASE3_HOST_ABI_V5 streams instance supplies every original resource/type
//! identity. Seven functions are reexported directly; only `read` is lifted
//! through an async callback. An outer composition must import CAP once and
//! pass this gate's two instances to the compiler-built TypeScript guest.
//!
//! Maintained Wasmtime 48.0.7, runtime/component/concurrent.rs at development
//! 5e465f8c534ee31d407dbb9720fdec35cb9da71d (SHA256
//! 3247651c36757d21ab1e5e5609bcdf0f11152fa724f3991d7b3ace6161c46b6e):
//! - 2491..2605 / 3058..3082: callback WAIT=(set<<4)|2; (event,handle,status).
//! - 4015..4170: async cancellation returns BLOCKED until task return/cancel.
//! - 3389..3495: task return/cancel validates and ends the actual borrow scope.
//! - 3585..3634: actual resolved subtask drop consumes its original handle.
//! - 2706..2743 / 916..969: the instance exits before parking a callback, so a
//!   pure synchronous diagnostic can read state between callbacks (no backpressure).
//!
//! Bounds: ONE read for the lifetime of this instance, no resets; ONE child
//! subtask and ONE waitable set; THREE i32 globals; ONE fixed 64-KiB page, one
//! fixed 16-byte result at offset64, no memory growth or successful realloc.
//! The read result has no strings/lists: result<option<own<chunk>>,stream-error>
//! flattens to four i32 values for async task.return (MAX_FLAT_PARAMS). The
//! canonical memory discriminants are byte loads, not padding-dependent words.
//! Original connection/chunk ownership is never replaced by numeric adoption.
//!
//! Protocol: the actual peer withholds bytes/EOF, the caller yields through its
//! bounded admitted scheduler until entered()==1, then cancels. Callback event6
//! records2 but deliberately keeps the real inner read alive. Only a real
//! write-after-logical-rejection handshake allows the peer to release that read.
//! Its terminal callback drops any owned chunk when cancelling, drops the actual
//! child and set, then task.cancel/EXIT. Normal completion task.returns the exact
//! real result. State3 means this finite child cleanup ran; it proves neither
//! provider IoCall/IoTransfer/socket retirement nor kernel final free. Errors,
//! unexpected events/statuses, second reads and deadline expiry are failures.
//! This file has not been compiled or executed; signed qualification is separate.
use wasm_encoder::*;

#[path = "../../../latent-packaging/tests/fixtures/host.rs"]
mod host;

pub const CAP: &str = latent_capabilities::broker::network::STREAM_CAPABILITY;
pub const GATE_CONTRACT: &str = "tests:typescript-import-borrow-gate/streams@1.0.0";
pub const DIAGNOSTIC_CONTRACT: &str = "tests:typescript-import-borrow-gate/diagnostic@1.0.0";
const OPS: [&str; 8] = ["connect", "read", "write", "ready", "inspect", "shutdown", "close", "chunk-bytes"];
// Named exports of the exact original WIT, including all non-resource aliases.
const TYPES: [&str; 11] = ["connection", "chunk", "transport", "state", "interest",
    "shutdown-mode", "error-code", "stream-error", "observation", "connect-request", "readiness"];
const RESULT: i32 = 64;
const PHASE: u32 = 0;
const CHILD: u32 = 1;
const SET: u32 = 2;

/// Unexecuted until a separate owning native control invokes this encoder.
pub fn bytes() -> Vec<u8> {
    let mut component = Component::new();
    let spec = latent_core::PHASE3_HOST_ABI_V5.interface(CAP).unwrap();
    let mut types = ComponentTypeSection::new();
    types.instance(&host::interface(spec.wit, spec.interface, None)); // type0
    component.section(&types);
    let mut imports = ComponentImportSection::new();
    imports.import(CAP, ComponentTypeRef::Instance(0)); // instance0
    component.section(&imports);
    let mut aliases = ComponentAliasSection::new();
    for name in OPS {
        aliases.alias(Alias::InstanceExport { instance: 0, kind: ComponentExportKind::Func, name });
    } // functions0..7
    for name in TYPES {
        aliases.alias(Alias::InstanceExport { instance: 0, kind: ComponentExportKind::Type, name });
    } // types1..11; connection1, chunk2, stream-error8
    component.section(&aliases);
    let mut types = ComponentTypeSection::new();
    types.defined_type().borrow(1); // 12
    types.defined_type().own(2); // 13
    types.defined_type().option(ComponentValType::Type(13)); // 14
    types.defined_type().option(PrimitiveValType::U32); // 15
    types.defined_type().result(Some(ComponentValType::Type(14)), Some(ComponentValType::Type(8))); // 16
    types.function().async_(true).params([
        ("source", ComponentValType::Type(12)),
        ("maximum-bytes", PrimitiveValType::U32.into()),
        ("timeout-millis", ComponentValType::Type(15)),
    ]).result(Some(ComponentValType::Type(16))); // 17
    types.function().params([] as [(&str, ComponentValType); 0])
        .result(Some(PrimitiveValType::U32.into())); // 18
    types.function().params([] as [(&str, ComponentValType); 0]).result(None); // 19
    component.section(&types);
    component.section(&ModuleSection(&memory())); // module0
    let mut instances = InstanceSection::new();
    instances.instantiate(0, [] as [(&str, ModuleArg); 0]); // core instance0
    component.section(&instances);
    let mut aliases = ComponentAliasSection::new();
    aliases.alias(Alias::CoreInstanceExport { instance: 0, kind: ExportKind::Memory, name: "memory" });
    aliases.alias(Alias::CoreInstanceExport { instance: 0, kind: ExportKind::Func, name: "realloc" }); // corefunc0
    component.section(&aliases);
    let mut canon = CanonicalFunctionSection::new();
    canon.lower(1, [CanonicalOption::Memory(0), CanonicalOption::Realloc(0), CanonicalOption::Async]); // 1
    canon.resource_drop(2); // 2
    canon.waitable_set_new(); // 3
    canon.waitable_join(); // 4
    canon.subtask_drop(); // 5
    canon.waitable_set_drop(); // 6
    canon.task_return(Some(ComponentValType::Type(16)), [CanonicalOption::Memory(0)]); // 7
    canon.task_cancel(); // 8
    component.section(&canon);
    component.section(&ModuleSection(&worker())); // module1
    let mut instances = InstanceSection::new();
    instances.export_items(["read", "drop-chunk", "new", "join", "drop-child", "drop-set", "return", "cancel"]
        .into_iter().enumerate().map(|(i, name)| (name, ExportKind::Func, u32::try_from(i + 1).unwrap())));
    instances.instantiate(1, [("io", ModuleArg::Instance(1)), ("memory", ModuleArg::Instance(0))]); // core instance2
    component.section(&instances);
    let mut aliases = ComponentAliasSection::new();
    for name in ["read", "callback", "entered", "intentional-trap"] {
        aliases.alias(Alias::CoreInstanceExport { instance: 2, kind: ExportKind::Func, name });
    } // corefunc9,10,11,12
    component.section(&aliases);
    let mut canon = CanonicalFunctionSection::new();
    canon.lift(9, 17, [CanonicalOption::Memory(0), CanonicalOption::Realloc(0),
        CanonicalOption::Async, CanonicalOption::Callback(10)]); // componentfunc8
    canon.lift(11, 18, []); // componentfunc9
    canon.lift(12, 19, []); // componentfunc10
    component.section(&canon);
    let mut instances = ComponentInstanceSection::new();
    let exports = TYPES.into_iter().enumerate().map(|(i, name)|
        (name, ComponentExportKind::Type, u32::try_from(i + 1).unwrap()))
        .chain(OPS.into_iter().enumerate().map(|(i, name)|
            (name, ComponentExportKind::Func, if i == 1 { 8 } else { u32::try_from(i).unwrap() })));
    instances.export_items(exports.collect::<Vec<_>>()); // component instance1
    instances.export_items([("entered", ComponentExportKind::Func, 9),
        ("intentional-trap", ComponentExportKind::Func, 10)]); // component instance2
    component.section(&instances);
    let mut exports = ComponentExportSection::new();
    exports.export(GATE_CONTRACT, ComponentExportKind::Instance, 1, None);
    exports.export(DIAGNOSTIC_CONTRACT, ComponentExportKind::Instance, 2, None);
    component.section(&exports);
    let bytes = component.finish();
    wasmparser::Validator::new_with_features(wasmparser::WasmFeatures::all())
        .validate_all(&bytes).unwrap();
    bytes
}

fn memory_type() -> MemoryType {
    MemoryType { minimum: 1, maximum: Some(1), memory64: false, shared: false, page_size_log2: None }
}
fn emit(body: &mut Function, instructions: impl IntoIterator<Item = Instruction<'static>>) {
    for instruction in instructions { body.instruction(&instruction); }
}
fn mem(offset: u64) -> MemArg { MemArg { offset, align: 2, memory_index: 0 } }
fn load_byte(offset: u64) -> [Instruction<'static>; 2] {
    [Instruction::I32Const(RESULT), Instruction::I32Load8U(MemArg { align: 0, ..mem(offset) })]
}
fn insist(body: &mut Function, condition: impl IntoIterator<Item = Instruction<'static>>) {
    emit(body, condition);
    emit(body, [Instruction::I32Eqz, Instruction::If(BlockType::Empty), Instruction::Unreachable, Instruction::End]);
}
fn waiting(body: &mut Function) {
    emit(body, [Instruction::GlobalGet(SET), Instruction::I32Const(4), Instruction::I32Shl,
        Instruction::I32Const(2), Instruction::I32Or]);
}
fn memory() -> Module {
    let mut module = Module::new();
    let mut types = TypeSection::new();
    types.ty().function([ValType::I32; 4], [ValType::I32]);
    module.section(&types);
    let mut functions = FunctionSection::new(); functions.function(0); module.section(&functions);
    let mut memories = MemorySection::new(); memories.memory(memory_type()); module.section(&memories);
    let mut exports = ExportSection::new();
    exports.export("memory", ExportKind::Memory, 0); exports.export("realloc", ExportKind::Func, 0);
    module.section(&exports);
    let mut body = Function::new([]); // This result contains no allocating values.
    emit(&mut body, [Instruction::Unreachable, Instruction::End]);
    let mut code = CodeSection::new(); code.function(&body); module.section(&code);
    module
}

fn worker() -> Module {
    let mut module = Module::new();
    let mut types = TypeSection::new();
    for (params, results) in [(5, 1), (1, 0), (0, 1), (2, 0), (4, 0), (0, 0), (4, 1), (3, 1)] {
        types.ty().function(vec![ValType::I32; params], vec![ValType::I32; results]);
    }
    module.section(&types);
    let mut imports = ImportSection::new();
    for (name, ty) in [("read", 0), ("drop-chunk", 1), ("new", 2), ("join", 3),
        ("drop-child", 1), ("drop-set", 1), ("return", 4), ("cancel", 5)] {
        imports.import("io", name, EntityType::Function(ty));
    }
    imports.import("memory", "memory", EntityType::Memory(memory_type()));
    module.section(&imports);
    let mut functions = FunctionSection::new();
    for ty in [6, 7, 2, 2, 5] { functions.function(ty); } // prefix8, callback9, entered10, finish11, trap12
    module.section(&functions);
    let mut globals = GlobalSection::new();
    for _ in 0..3 {
        globals.global(GlobalType { val_type: ValType::I32, mutable: true, shared: false }, &ConstExpr::i32_const(0));
    }
    module.section(&globals);
    let mut exports = ExportSection::new();
    for (name, index) in [("read", 8), ("callback", 9), ("entered", 10), ("intentional-trap", 12)] { exports.export(name, ExportKind::Func, index); }
    module.section(&exports);
    let mut code = CodeSection::new();
    code.function(&prefix()); code.function(&callback());
    let mut entered = Function::new([]);
    emit(&mut entered, [Instruction::GlobalGet(PHASE), Instruction::End]);
    code.function(&entered); code.function(&finish());
    let mut intentional_trap = Function::new([]);
    // Wrong phase is ordinary Unreachable and must fail the distinct host check.
    insist(&mut intentional_trap, [Instruction::GlobalGet(PHASE), Instruction::I32Const(2), Instruction::I32Eq]);
    // Only the exact intentional JS error catch calls this pure diagnostic.
    // No destructor runs here; the same real inner read remains outstanding.
    emit(&mut intentional_trap, [Instruction::I32Const(1), Instruction::I32Const(0),
        Instruction::I32DivS, Instruction::Drop, Instruction::Unreachable, Instruction::End]);
    code.function(&intentional_trap); module.section(&code);
    module
}

fn prefix() -> Function {
    let mut body = Function::new([(1, ValType::I32)]); // local4 is packed status
    insist(&mut body, [Instruction::GlobalGet(PHASE), Instruction::I32Eqz]);
    emit(&mut body, [Instruction::LocalGet(0), Instruction::LocalGet(1), Instruction::LocalGet(2),
        Instruction::LocalGet(3), Instruction::I32Const(RESULT), Instruction::Call(0), Instruction::LocalSet(4)]);
    // Immediate normal completion is forwarded but cannot establish entered1.
    emit(&mut body, [Instruction::LocalGet(4), Instruction::I32Const(2), Instruction::I32Eq,
        Instruction::If(BlockType::Empty), Instruction::Call(11), Instruction::Return, Instruction::End]);
    insist(&mut body, [Instruction::LocalGet(4), Instruction::I32Const(15), Instruction::I32And,
        Instruction::I32Const(1), Instruction::I32Eq]);
    emit(&mut body, [Instruction::LocalGet(4), Instruction::I32Const(4), Instruction::I32ShrU, Instruction::GlobalSet(CHILD)]);
    insist(&mut body, [Instruction::GlobalGet(CHILD)]);
    emit(&mut body, [Instruction::Call(2), Instruction::GlobalSet(SET)]);
    insist(&mut body, [Instruction::GlobalGet(SET)]);
    insist(&mut body, [Instruction::GlobalGet(SET), Instruction::I32Const(1 << 28), Instruction::I32LtU]);
    emit(&mut body, [Instruction::GlobalGet(CHILD), Instruction::GlobalGet(SET), Instruction::Call(3),
        Instruction::I32Const(1), Instruction::GlobalSet(PHASE)]);
    // A diagnostic cannot enter until this prefix returned and do_not_enter cleared.
    waiting(&mut body); emit(&mut body, [Instruction::End]); body
}

fn callback() -> Function {
    let mut body = Function::new([]);
    insist(&mut body, [Instruction::GlobalGet(PHASE), Instruction::I32Const(1), Instruction::I32Eq,
        Instruction::GlobalGet(PHASE), Instruction::I32Const(2), Instruction::I32Eq, Instruction::I32Or]);
    emit(&mut body, [Instruction::LocalGet(0), Instruction::I32Const(6), Instruction::I32Eq, Instruction::If(BlockType::Empty)]);
    insist(&mut body, [Instruction::GlobalGet(PHASE), Instruction::I32Const(1), Instruction::I32Eq]);
    insist(&mut body, [Instruction::LocalGet(1), Instruction::I32Eqz]);
    insist(&mut body, [Instruction::LocalGet(2), Instruction::I32Eqz]);
    emit(&mut body, [Instruction::I32Const(2), Instruction::GlobalSet(PHASE)]);
    waiting(&mut body); emit(&mut body, [Instruction::Return, Instruction::End]);
    insist(&mut body, [Instruction::LocalGet(0), Instruction::I32Const(1), Instruction::I32Eq]);
    insist(&mut body, [Instruction::LocalGet(1), Instruction::GlobalGet(CHILD), Instruction::I32Eq]);
    insist(&mut body, [Instruction::LocalGet(2), Instruction::I32Const(2), Instruction::I32Eq]);
    emit(&mut body, [Instruction::Call(11), Instruction::End]); body
}

fn finish() -> Function {
    let mut body = Function::new([(1, ValType::I32)]); // local0 cancellation copy
    emit(&mut body, [Instruction::GlobalGet(PHASE), Instruction::I32Const(2), Instruction::I32Eq, Instruction::LocalSet(0)]);
    // On cancelled late success consume the real owned chunk in THIS component.
    emit(&mut body, [Instruction::LocalGet(0), Instruction::If(BlockType::Empty)]);
    emit(&mut body, load_byte(0)); emit(&mut body, [Instruction::I32Eqz, Instruction::If(BlockType::Empty)]);
    emit(&mut body, load_byte(4)); emit(&mut body, [Instruction::If(BlockType::Empty),
        Instruction::I32Const(RESULT), Instruction::I32Load(mem(8)), Instruction::Call(1),
        Instruction::End, Instruction::End, Instruction::End]);
    emit(&mut body, [Instruction::GlobalGet(CHILD), Instruction::If(BlockType::Empty),
        Instruction::GlobalGet(CHILD), Instruction::I32Const(0), Instruction::Call(3),
        Instruction::GlobalGet(CHILD), Instruction::Call(4),
        Instruction::GlobalGet(SET), Instruction::Call(5), Instruction::End,
        Instruction::I32Const(3), Instruction::GlobalSet(PHASE),
        Instruction::LocalGet(0), Instruction::If(BlockType::Empty), Instruction::Call(7), Instruction::Else]);
    // Original flat result: discriminant; option tag or error code; chunk handle
    // or accepted-prefix; zero padding arm or may-have-applied boolean.
    emit(&mut body, load_byte(0)); emit(&mut body, load_byte(4));
    emit(&mut body, [Instruction::I32Const(RESULT), Instruction::I32Load(mem(8))]);
    emit(&mut body, load_byte(0)); emit(&mut body, [Instruction::If(BlockType::Result(ValType::I32))]);
    emit(&mut body, load_byte(12)); emit(&mut body, [Instruction::Else, Instruction::I32Const(0), Instruction::End,
        Instruction::Call(6), Instruction::End, Instruction::I32Const(0), Instruction::End]);
    body
}

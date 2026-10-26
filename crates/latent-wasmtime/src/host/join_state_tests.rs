//! Actual canonical async import admission on the original activation budget.
//! Native-only control: no JavaScript/SDK build or signed guest claim.
use super::TrackingLimiter;
use latent_core::{
    ActivationBudget, BudgetProfile, ClockSample, EffectiveActivationBudget, HostMemoryReservation,
    PlatformError, PlatformErrorCode, ResourceBudget,
};
use std::future::Future;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use std::task::Poll;
use std::time::Instant;
use wasmtime::component::{Component, Linker};
use wasmtime::{Config, Engine, NativeAllocation, NativeMemory, NativeMemoryBinding, Store};

#[derive(Debug)]
struct OriginalAdmission(PlatformError);
impl std::fmt::Display for OriginalAdmission {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.0.message.fmt(f)
    }
}
impl std::error::Error for OriginalAdmission {}
fn admission(error: latent_core::BudgetError) -> wasmtime::Error {
    wasmtime::Error::new(OriginalAdmission(error.to_platform_error()))
}
#[derive(Default)]
struct Probe {
    armed: bool,
    refusal_request: usize,
    requests: Vec<usize>, // test observation only; never an admission oracle
    contention: Option<HostMemoryReservation>,
}
struct Memory {
    budget: ActivationBudget,
    probe: Arc<Mutex<Probe>>,
}
struct Allocation(HostMemoryReservation);
impl NativeAllocation for Allocation {
    fn allocated(&mut self) {
        self.0.confirm();
    }
}
impl NativeMemory for Memory {
    fn reserve(&self, bytes: usize) -> wasmtime::Result<Box<dyn NativeAllocation>> {
        let mut probe = self.probe.lock().unwrap();
        if probe.armed {
            assert!(
                probe.requests.len() < probe.refusal_request,
                "refusal must stop the closed allocation path"
            );
            probe.requests.push(bytes);
            if probe.requests.len() == probe.refusal_request {
                // Actual contention consumes the SAME original budget, after
                // the callback-Future Box and before the selected allocation.
                let remaining = self.budget.remaining_at(Instant::now()).memory_bytes;
                probe.contention = Some(
                    self.budget
                        .reserve_host_memory(remaining)
                        .map_err(admission)?,
                );
            }
        }
        drop(probe);
        let total = bytes
            .checked_add(crate::native_tables::OWNER_ESCROW)
            .unwrap();
        let mut memory = self
            .budget
            .reserve_host_memory(total as u64)
            .map_err(admission)?;
        memory.confirm_bytes(crate::native_tables::OWNER_ESCROW as u64);
        Ok(Box::new(Allocation(memory)))
    }
}
fn binding(budget: &ActivationBudget, probe: &Arc<Mutex<Probe>>) -> NativeMemoryBinding {
    let size = NativeMemoryBinding::allocation_size::<Memory>();
    let allocation = crate::native_tables::reserve(budget, size)
        .unwrap()
        .unwrap();
    NativeMemoryBinding::new(
        Memory {
            budget: budget.clone(),
            probe: probe.clone(),
        },
        allocation,
    )
}
struct Data {
    limiter: TrackingLimiter,
}
fn budget() -> ActivationBudget {
    let limits = ResourceBudget {
        cpu_fuel: 1_000_000_000,
        memory_bytes: 64 * 1024 * 1024,
        wall_time_limit_millis: Some(120_000),
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 0,
        effect_count: 0,
    };
    let grant = EffectiveActivationBudget::admit_profile_at(
        BudgetProfile::Phase3,
        &limits,
        &limits,
        &limits,
        None,
        ClockSample::new(1000, Instant::now()),
    )
    .unwrap();
    ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap()
}

// One real callback-style async canonical import, one scalar result, one fixed
// page and one child/set. No realloc, memory growth, resource or provider API.
fn component() -> Vec<u8> {
    use wasm_encoder::*;
    let memory_type = MemoryType {
        minimum: 1,
        maximum: Some(1),
        memory64: false,
        shared: false,
        page_size_log2: None,
    };
    let mut component = wasm_encoder::Component::new();
    let mut types = ComponentTypeSection::new();
    types
        .function()
        .async_(true)
        .params([] as [(&str, ComponentValType); 0])
        .result(Some(PrimitiveValType::U32.into()));
    component.section(&types);
    let mut imports = ComponentImportSection::new();
    imports.import("wait", ComponentTypeRef::Func(0));
    component.section(&imports);
    let mut memory = Module::new();
    let mut memories = MemorySection::new();
    memories.memory(memory_type);
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
    let mut canon = CanonicalFunctionSection::new();
    canon.lower(0, [CanonicalOption::Memory(0), CanonicalOption::Async]); // corefunc0
    canon.waitable_set_new(); //1
    canon.waitable_join(); //2
    canon.subtask_drop(); //3
    canon.waitable_set_drop(); //4
    canon.task_return(
        Some(PrimitiveValType::U32.into()),
        [CanonicalOption::Memory(0)],
    ); //5
    component.section(&canon);
    let mut worker = Module::new();
    let mut types = TypeSection::new();
    for (params, results) in [(1, 1), (0, 1), (2, 0), (1, 0), (3, 1)] {
        types
            .ty()
            .function(vec![ValType::I32; params], vec![ValType::I32; results]);
    }
    worker.section(&types);
    let mut imports = ImportSection::new();
    for (name, ty) in [
        ("wait", 0),
        ("new", 1),
        ("join", 2),
        ("drop-child", 3),
        ("drop-set", 3),
        ("return", 3),
    ] {
        imports.import("io", name, EntityType::Function(ty));
    }
    imports.import("memory", "memory", EntityType::Memory(memory_type));
    worker.section(&imports);
    let mut funcs = FunctionSection::new();
    funcs.function(1);
    funcs.function(4);
    worker.section(&funcs);
    let mut globals = GlobalSection::new();
    for _ in 0..2 {
        globals.global(
            GlobalType {
                val_type: ValType::I32,
                mutable: true,
                shared: false,
            },
            &ConstExpr::i32_const(0),
        );
    }
    worker.section(&globals);
    let mut exports = ExportSection::new();
    exports.export("run", ExportKind::Func, 6);
    exports.export("callback", ExportKind::Func, 7);
    worker.section(&exports);
    let mut start = Function::new([(1, ValType::I32)]);
    for i in [
        Instruction::I32Const(64),
        Instruction::Call(0),
        Instruction::LocalTee(0),
        Instruction::I32Const(15),
        Instruction::I32And,
        Instruction::I32Const(2),
        Instruction::I32Eq,
        Instruction::If(BlockType::Empty),
        Instruction::I32Const(64),
        Instruction::I32Load(MemArg {
            offset: 0,
            align: 2,
            memory_index: 0,
        }),
        Instruction::Call(5),
        Instruction::I32Const(0),
        Instruction::Return,
        Instruction::End,
        Instruction::LocalGet(0),
        Instruction::I32Const(15),
        Instruction::I32And,
        Instruction::I32Const(1),
        Instruction::I32Ne,
        Instruction::If(BlockType::Empty),
        Instruction::Unreachable,
        Instruction::End,
        Instruction::LocalGet(0),
        Instruction::I32Const(4),
        Instruction::I32ShrU,
        Instruction::GlobalSet(0),
        Instruction::Call(1),
        Instruction::GlobalSet(1),
        Instruction::GlobalGet(0),
        Instruction::GlobalGet(1),
        Instruction::Call(2),
        Instruction::GlobalGet(1),
        Instruction::I32Const(4),
        Instruction::I32Shl,
        Instruction::I32Const(2),
        Instruction::I32Or,
        Instruction::End,
    ] {
        start.instruction(&i);
    }
    let mut callback = Function::new([]);
    for i in [
        Instruction::LocalGet(0),
        Instruction::I32Const(1),
        Instruction::I32Ne,
        Instruction::LocalGet(1),
        Instruction::GlobalGet(0),
        Instruction::I32Ne,
        Instruction::I32Or,
        Instruction::LocalGet(2),
        Instruction::I32Const(2),
        Instruction::I32Ne,
        Instruction::I32Or,
        Instruction::If(BlockType::Empty),
        Instruction::Unreachable,
        Instruction::End,
        Instruction::GlobalGet(0),
        Instruction::Call(3),
        Instruction::GlobalGet(1),
        Instruction::Call(4),
        Instruction::I32Const(64),
        Instruction::I32Load(MemArg {
            offset: 0,
            align: 2,
            memory_index: 0,
        }),
        Instruction::Call(5),
        Instruction::I32Const(0),
        Instruction::End,
    ] {
        callback.instruction(&i);
    }
    let mut code = CodeSection::new();
    code.function(&start);
    code.function(&callback);
    worker.section(&code);
    component.section(&ModuleSection(&worker));
    let mut instances = InstanceSection::new();
    instances.export_items([
        ("wait", ExportKind::Func, 0),
        ("new", ExportKind::Func, 1),
        ("join", ExportKind::Func, 2),
        ("drop-child", ExportKind::Func, 3),
        ("drop-set", ExportKind::Func, 4),
        ("return", ExportKind::Func, 5),
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
    }); //6
    aliases.alias(Alias::CoreInstanceExport {
        instance: 2,
        kind: ExportKind::Func,
        name: "callback",
    }); //7
    component.section(&aliases);
    let mut canon = CanonicalFunctionSection::new();
    canon.lift(
        6,
        0,
        [
            CanonicalOption::Memory(0),
            CanonicalOption::Async,
            CanonicalOption::Callback(7),
        ],
    );
    component.section(&canon);
    let mut exports = ComponentExportSection::new();
    exports.export("run", ComponentExportKind::Func, 1, None);
    component.section(&exports);
    let bytes = component.finish();
    wasmparser::Validator::new_with_features(wasmparser::WasmFeatures::all())
        .validate_all(&bytes)
        .unwrap();
    bytes
}

#[tokio::test]
#[ignore = "requires compiled private JoinState layout from the paired owning controls"]
async fn canonical_join_state_first_poll_refusal_and_same_budget_fresh_store() {
    canonical_backing_refusal_and_same_budget_fresh_store(2).await;
}

#[tokio::test]
#[ignore = "requires focused actual async-import future backing qualification"]
async fn canonical_call_future_first_poll_refusal_and_same_budget_fresh_store() {
    canonical_backing_refusal_and_same_budget_fresh_store(3).await;
}

#[tokio::test]
#[ignore = "requires focused actual prepared pending-continuation qualification"]
async fn canonical_pending_future_first_poll_refusal_and_same_budget_fresh_store() {
    canonical_backing_refusal_and_same_budget_fresh_store(4).await;
}

async fn canonical_backing_refusal_and_same_budget_fresh_store(refusal_request: usize) {
    assert!(matches!(refusal_request, 2..=4));
    let expected = (refusal_request == 2).then(|| {
        let layout: usize = std::env::var("LSF_TEST_JOIN_STATE_LAYOUT")
            .expect("owning layout witness")
            .parse()
            .expect("typed compiled layout");
        assert!((1..=4096).contains(&layout)); // assertion only; never grants capacity
        layout
    });
    let original = budget();
    let mut config = Config::new();
    config
        .wasm_component_model(true)
        .wasm_component_model_async(true)
        .concurrency_support(true)
        .consume_fuel(true);
    let engine = Engine::new(&config).unwrap();
    let component = Component::new(&engine, component()).unwrap();
    for refuse in [true, false] {
        let probe = Arc::new(Mutex::new(Probe::default()));
        let entered = Arc::new(AtomicBool::new(false));
        let polled = Arc::new(AtomicBool::new(false));
        let (send, receive) = tokio::sync::oneshot::channel::<u32>();
        let receive = Arc::new(Mutex::new(Some(receive)));
        let mut linker = Linker::<Data>::new(&engine);
        let (entry, first, source) = (entered.clone(), polled.clone(), receive.clone());
        linker
            .root()
            .func_wrap_concurrent("wait", move |_, (): ()| {
                entry.store(true, Ordering::SeqCst);
                let receive = source.lock().unwrap().take().unwrap();
                let first = first.clone();
                Box::pin(async move {
                    first.store(true, Ordering::SeqCst);
                    Ok((receive.await.unwrap(),))
                })
            })
            .unwrap();
        let mut limiter = TrackingLimiter::new(original.granted().memory_bytes as usize);
        limiter.budget = Some(original.clone());
        let mut store = Store::try_new_with_memory_binding(
            &engine,
            Data { limiter },
            binding(&original, &probe),
        )
        .unwrap();
        store.limiter(|data| &mut data.limiter);
        store.set_fuel(1_000_000_000).unwrap();
        store.set_hostcall_fuel(128 * 1024);
        let instance = linker
            .instantiate_async(&mut store, &component)
            .await
            .unwrap();
        let function = instance
            .get_typed_func::<(), (u32,)>(&mut store, "run")
            .unwrap();
        {
            let mut probe = probe.lock().unwrap();
            probe.armed = refuse;
            probe.refusal_request = refusal_request;
        }
        let initial_fuel = original.remaining_at(Instant::now()).cpu_fuel;
        store.set_fuel(initial_fuel).unwrap();
        let mut call = Box::pin(function.call_async(&mut store, ()));
        if refuse {
            let error = call.await.unwrap_err();
            let admitted = error
                .chain()
                .find_map(|cause| cause.downcast_ref::<OriginalAdmission>())
                .expect("original typed budget error");
            assert_eq!(admitted.0.code, PlatformErrorCode::ResourceExhausted);
            assert!(admitted.0.details.iter().any(|d| d
                .fields
                .get("dimension")
                .map(String::as_str)
                == Some("memory-bytes")));
            assert!(!entered.load(Ordering::SeqCst) && !polled.load(Ordering::SeqCst));
            let observed = probe.lock().unwrap();
            assert_eq!(observed.requests.len(), refusal_request);
            if let Some(expected) = expected {
                assert_eq!(
                    observed.requests[1], expected,
                    "actual private cell admission, not an earlier allocation"
                );
            }
            assert!(observed.contention.is_some());
            if refusal_request == 3 {
                // The closed path is callback box, JoinState, then the
                // abortable call future Box before any user code is polled.
                // Order and the unentered closure identify this admission;
                // the byte count alone is not treated as allocation identity.
                assert!((1..=4096).contains(&observed.requests[2]));
            }
            if refusal_request == 4 {
                // The unchanged first three admissions are callback Box,
                // JoinState, and inner CallFuture Box. The fourth reserves
                // the exact continuation output before the SAME first poll.
                // No user code, continuation factory, or completion worker
                // can have run on this closed path before that refusal.
                assert!((1..=4096).contains(&observed.requests[2]));
                assert!((1..=4096).contains(&observed.requests[3]));
            }
            drop(observed);
            drop(error);
            drop(send);
        } else {
            std::future::poll_fn(|cx| {
                assert!(call.as_mut().poll(cx).is_pending());
                Poll::Ready(())
            })
            .await;
            assert!(entered.load(Ordering::SeqCst) && polled.load(Ordering::SeqCst));
            assert!(original.host_memory_bytes() > 0);
            send.send(42).unwrap();
            assert_eq!(call.await.unwrap(), (42,));
        }
        original
            .consume_cpu_fuel(initial_fuel - store.get_fuel().unwrap())
            .unwrap();
        drop(store); // the failed instance is never reentered; actual owner dies
        let held = probe.lock().unwrap().contention.take();
        drop(held);
        drop(probe);
        assert_eq!(original.host_memory_bytes(), 0);
        assert_eq!(original.outstanding_reservations(), 0);
    }
    if refusal_request == 3 {
        println!(
            "LSF_CALL_FUTURE_V1 refusal=memory-bytes requests=3 before-poll=true fresh=42 stores=2"
        );
    }
    if refusal_request == 4 {
        println!(
            "LSF_PENDING_FUTURE_V1 refusal=memory-bytes requests=4 before-poll=true fresh=42 stores=2"
        );
    }
}

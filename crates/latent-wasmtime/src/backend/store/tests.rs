//! Real pinned Wasmtime allocation callbacks and original runtime owner counts.
//! This is not signed guest qualification or failed-decommit quarantine proof.
use super::{RuntimeRetirement, StoreCustody};
use latent_core::{
    activation_runtime::{ActivationRuntime, OwnerKind, RuntimeLimits, RuntimeOwner},
    ActivationBudget, BudgetCancellationProbe, DelegationLimits,
};
use std::{
    future::Future,
    panic::{catch_unwind, AssertUnwindSafe},
    sync::{
        atomic::{AtomicBool, AtomicU32, Ordering},
        Arc,
    },
    task::{Context, Poll, Waker},
};
use wasmtime::{Engine, Ref, ResourceLimiter, Store};

struct Signal;
impl BudgetCancellationProbe for Signal {
    fn is_cancelled(&self) -> bool {
        false
    }
    fn cancelled(&self) -> latent_core::BoxFuture<'_, ()> {
        Box::pin(std::future::pending())
    }
    fn mark_terminal(&self) {}
}

#[derive(Default)]
struct Observation {
    allocation_drops: AtomicU32,
    native_at_allocation_drop: AtomicU32,
    panic_at_allocation_drop: AtomicBool,
}

struct Allocation {
    runtime: ActivationRuntime,
    observation: Arc<Observation>,
    // Delegate the actual byte charge; do not replace it with a model counter.
    _memory: Box<dyn wasmtime::TableAllocation>,
}
impl wasmtime::TableAllocation for Allocation {
    fn allocated(&mut self) {
        self._memory.allocated();
    }
}
impl Drop for Allocation {
    fn drop(&mut self) {
        self.observation
            .native_at_allocation_drop
            .store(self.runtime.snapshot().owners[6], Ordering::SeqCst);
        self.observation
            .allocation_drops
            .fetch_add(1, Ordering::SeqCst);
        if self
            .observation
            .panic_at_allocation_drop
            .swap(false, Ordering::SeqCst)
        {
            panic!("injected physical allocation retirement panic");
        }
    }
}
struct Limiter {
    budget: ActivationBudget,
    runtime: ActivationRuntime,
    observation: Arc<Observation>,
}
impl ResourceLimiter for Limiter {
    fn memory_growing(
        &mut self,
        _current: usize,
        _desired: usize,
        _maximum: Option<usize>,
    ) -> wasmtime::Result<bool> {
        Ok(true)
    }
    fn table_growing(
        &mut self,
        _current: usize,
        _desired: usize,
        _maximum: Option<usize>,
    ) -> wasmtime::Result<bool> {
        Ok(true)
    }
    fn table_allocating(
        &mut self,
        bytes: usize,
    ) -> wasmtime::Result<Option<Box<dyn wasmtime::TableAllocation>>> {
        Ok(
            crate::native_tables::reserve(&self.budget, bytes)?.map(|memory| {
                Box::new(Allocation {
                    runtime: self.runtime.clone(),
                    observation: self.observation.clone(),
                    _memory: memory,
                }) as Box<dyn wasmtime::TableAllocation>
            }),
        )
    }
}
struct Data {
    _owner: Option<RuntimeOwner>,
    limiter: Limiter,
}

fn engine(pooled: bool) -> Engine {
    let mut config = wasmtime::Config::new();
    if pooled {
        let mut pool = wasmtime::PoolingAllocationConfig::new();
        pool.total_component_instances(0)
            .total_core_instances(1)
            .total_memories(0)
            .total_tables(1)
            .table_elements(16)
            .decommit_batch_size(1)
            .table_keep_resident(0)
            .max_unused_warm_slots(0);
        config.allocation_strategy(pool);
    }
    Engine::new(&config).unwrap()
}

fn table_and_trap(engine: &Engine) -> wasmtime::Module {
    let mut module = wasm_encoder::Module::new();
    let mut types = wasm_encoder::TypeSection::new();
    types.ty().function([], []);
    module.section(&types);
    let mut functions = wasm_encoder::FunctionSection::new();
    functions.function(0);
    module.section(&functions);
    let mut tables = wasm_encoder::TableSection::new();
    tables.table(wasm_encoder::TableType {
        element_type: wasm_encoder::RefType::FUNCREF,
        table64: false,
        minimum: 2,
        maximum: Some(8),
        shared: false,
    });
    module.section(&tables);
    let mut exports = wasm_encoder::ExportSection::new();
    exports.export("table", wasm_encoder::ExportKind::Table, 0);
    exports.export("trap", wasm_encoder::ExportKind::Func, 0);
    module.section(&exports);
    let mut code = wasm_encoder::CodeSection::new();
    let mut function = wasm_encoder::Function::new([]);
    function.instruction(&wasm_encoder::Instruction::Unreachable);
    function.instruction(&wasm_encoder::Instruction::End);
    code.function(&function);
    module.section(&code);
    wasmtime::Module::new(engine, module.finish()).unwrap()
}

fn store(
    engine: &Engine,
) -> (
    Store<Data>,
    ActivationRuntime,
    Arc<Observation>,
    u64,
    wasmtime::TypedFunc<(), ()>,
) {
    let limits = latent_core::ResourceBudget {
        cpu_fuel: 1_000_000_000,
        memory_bytes: 1024 * 1024,
        wall_time_limit_millis: Some(5000),
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 0,
        effect_count: 0,
    };
    let grant = latent_core::EffectiveActivationBudget::admit_profile_at(
        latent_core::BudgetProfile::Phase3,
        &limits,
        &limits,
        &limits,
        None,
        latent_core::ClockSample::system_now(),
    )
    .unwrap();
    let budget = ActivationBudget::with_profile(grant, latent_core::BudgetProfile::Phase3).unwrap();
    budget
        .enable_descendants(DelegationLimits::default(), Arc::new(Signal))
        .unwrap();
    let runtime = ActivationRuntime::new(
        budget.clone(),
        RuntimeLimits {
            tasks: 0,
            executors: 0,
            queued_work: 0,
            waits: 0,
            timers: 0,
            results: 0,
            native_owners: 1,
        },
    )
    .unwrap();
    let observation = Arc::new(Observation::default());
    let owner = runtime.register(OwnerKind::Native, None).unwrap();
    let baseline = budget.host_memory_bytes();
    let mut store = Store::new(
        engine,
        Data {
            _owner: Some(owner),
            limiter: Limiter {
                budget: budget.clone(),
                runtime: runtime.clone(),
                observation: observation.clone(),
            },
        },
    );
    store.limiter(|data| &mut data.limiter);
    let module = table_and_trap(engine);
    let instance = wasmtime::Instance::new(&mut store, &module, &[]).unwrap();
    let table = instance.get_table(&mut store, "table").unwrap();
    let function = wasmtime::Func::wrap(&mut store, || 42i32);
    table.set(&mut store, 0, Ref::Func(Some(function))).unwrap();
    let trap = instance
        .get_typed_func::<(), ()>(&mut store, "trap")
        .unwrap();
    assert!(budget.host_memory_bytes() > baseline);
    assert_eq!(runtime.snapshot().owners[6], 1);
    (store, runtime, observation, baseline, trap)
}

#[test]
fn ordinary_store_drop_reproduces_early_logical_owner_release() {
    for pooled in [false, true] {
        let (store, runtime, observed, _, _) = store(&engine(pooled));
        drop(store);
        assert_eq!(observed.allocation_drops.load(Ordering::SeqCst), 1);
        assert_eq!(observed.native_at_allocation_drop.load(Ordering::SeqCst), 0);
        assert_eq!(runtime.snapshot().owners[6], 0);
    }
}

#[test]
fn custody_survives_return_trap_future_cancellation_and_outer_unwind() {
    for pooled in [false, true] {
        for exit in ["return", "trap", "cancel", "unwind"] {
            let (store, runtime, observed, baseline, trap) = store(&engine(pooled));
            let budget = store.data().limiter.budget.clone();
            let mut retirement = RuntimeRetirement::default();
            let mut custody = StoreCustody::new(store, &mut retirement);
            match exit {
                "return" => drop(custody),
                "trap" => {
                    let error = trap.call(&mut *custody, ()).unwrap_err();
                    assert_eq!(
                        error.downcast_ref::<wasmtime::Trap>(),
                        Some(&wasmtime::Trap::UnreachableCodeReached)
                    );
                    drop(error);
                    drop(custody);
                }
                "cancel" => {
                    let mut future = Box::pin(async move {
                        std::future::pending::<()>().await;
                        drop(custody);
                    });
                    assert!(matches!(
                        future
                            .as_mut()
                            .poll(&mut Context::from_waker(Waker::noop())),
                        Poll::Pending
                    ));
                    assert_eq!(observed.allocation_drops.load(Ordering::SeqCst), 0);
                    assert_eq!(runtime.snapshot().owners[6], 1);
                    drop(future);
                }
                "unwind" => {
                    assert!(catch_unwind(AssertUnwindSafe(move || {
                        let _custody = custody;
                        panic!("outer invocation unwind");
                    }))
                    .is_err());
                }
                _ => unreachable!(),
            }
            assert_eq!(
                observed.allocation_drops.load(Ordering::SeqCst),
                1,
                "{pooled}/{exit}"
            );
            assert_eq!(
                observed.native_at_allocation_drop.load(Ordering::SeqCst),
                1,
                "{pooled}/{exit}"
            );
            assert_eq!(runtime.snapshot().owners[6], 0, "{pooled}/{exit}");
            assert_eq!(budget.host_memory_bytes(), baseline, "{pooled}/{exit}");
            drop(runtime);
            assert_eq!(budget.host_memory_bytes(), 0);
        }
    }
}

fn failure_report(code: &str) -> latent_executor::ExecutionReport {
    use latent_core::{BudgetConsumption, Metadata};
    use latent_executor::{ExecutionReport, GuestOutcome, GuestTrap, HostResultDisposition};
    let mut report = ExecutionReport::reusable(Ok(GuestOutcome::Trapped {
        trap: GuestTrap {
            code: code.into(),
            message: "original winner".into(),
            metadata: Metadata::from([("source".into(), "original".into())]),
            guest_backtrace: Vec::new(),
            diagnostic: None,
        },
        consumption: BudgetConsumption {
            cpu_fuel: 41,
            peak_memory_bytes: 1024,
            ..Default::default()
        },
    }));
    report.host_result = HostResultDisposition::UnavailableAfterReturn;
    report
}

#[test]
fn reuse_requires_logical_finalization_and_completed_store_destruction() {
    use latent_executor::ExecutionCleanup;
    for logical in [false, true] {
        for destroyed in [false, true] {
            let mut state = RuntimeRetirement::default();
            state.enter();
            state.finalized(logical);
            state.store_destroyed = destroyed;
            let original = failure_report("not-a-lifecycle-trap");
            let report = state.apply(original.clone());
            assert_eq!(report.outcome, original.outcome);
            assert_eq!(report.host_result, original.host_result);
            assert_eq!(
                report.cleanup,
                if logical && destroyed {
                    ExecutionCleanup::Reusable
                } else {
                    ExecutionCleanup::Quarantine {
                        reason: "runtime-retirement-unproven".into(),
                    }
                }
            );
        }
    }
}

#[test]
fn trap_text_cannot_select_reuse_and_existing_quarantine_is_preserved() {
    use latent_executor::ExecutionCleanup;
    for code in ["runtime-lifecycle-unproven", "guest-trap", "arbitrary"] {
        let original = failure_report(code);
        // No Store was created; a diagnostic cannot manufacture a cleanup fault.
        assert_eq!(
            RuntimeRetirement::default().apply(original.clone()),
            original
        );
        let mut state = RuntimeRetirement::default();
        state.enter();
        let mut quarantined = original.clone();
        quarantined.cleanup = ExecutionCleanup::Quarantine {
            reason: "original-capability-refusal".into(),
        };
        assert_eq!(state.apply(quarantined.clone()), quarantined);
        state.finalized(true);
        state.store_destroyed = true;
        assert_eq!(state.apply(original.clone()), original);
        assert_eq!(state.apply(quarantined.clone()), quarantined);
    }
}

#[test]
fn failed_real_runtime_finalization_cannot_be_erased_by_store_cleanup() {
    use latent_executor::ExecutionCleanup;
    for pooled in [false, true] {
        let (store, runtime, observed, _, _) = store(&engine(pooled));
        let mut retirement = RuntimeRetirement::default();
        {
            let custody = StoreCustody::new(store, &mut retirement);
            // Actual original ledger refuses while its native capture is live.
            let result = runtime.retire();
            assert!(result.is_err());
            custody.retirement.finalized(result.is_ok());
        }
        assert_eq!(observed.native_at_allocation_drop.load(Ordering::SeqCst), 1);
        assert_eq!(runtime.snapshot().owners[6], 0);
        // Destructor cleanup and a later success are not the original proof.
        runtime.retire().unwrap();
        retirement.finalized(true);
        assert!(matches!(
            retirement.apply(failure_report("original-trap")).cleanup,
            ExecutionCleanup::Quarantine { .. }
        ));
    }
}

#[test]
fn early_return_and_a_second_store_cannot_reuse_an_earlier_proof() {
    use latent_executor::ExecutionCleanup;
    let mut state = RuntimeRetirement::default();
    state.enter();
    state.store_destroyed = true;
    assert!(matches!(
        state.apply(failure_report("early-return")).cleanup,
        ExecutionCleanup::Quarantine { .. }
    ));
    state.finalized(true);
    assert_eq!(
        state.apply(failure_report("first")).cleanup,
        ExecutionCleanup::Reusable
    );
    state.enter();
    state.finalized(true);
    state.store_destroyed = true;
    assert!(matches!(
        state.apply(failure_report("second")).cleanup,
        ExecutionCleanup::Quarantine { .. }
    ));
}

#[test]
fn failed_store_setup_keeps_custody_and_cannot_claim_reuse() {
    use latent_executor::ExecutionCleanup;
    for pooled in [false, true] {
        let (store, runtime, observed, _, _) = store(&engine(pooled));
        let mut retirement = RuntimeRetirement::default();
        {
            let mut custody = StoreCustody::new(store, &mut retirement);
            // This actual engine has fuel disabled. Its setup API refuses,
            // after allocation and before any logical-finalization witness.
            assert!(custody.set_fuel(1).is_err());
            assert_eq!(runtime.snapshot().owners[6], 1);
        }
        assert_eq!(observed.native_at_allocation_drop.load(Ordering::SeqCst), 1);
        assert_eq!(runtime.snapshot().owners[6], 0);
        assert!(matches!(
            retirement.apply(failure_report("setup-failed")).cleanup,
            ExecutionCleanup::Quarantine { .. }
        ));
    }
}

mod failure;
mod physical;

//! Actual engine table allocation and original-owner controls; no guest build.
use super::*;
use latent_core::{
    ActivationBudget, BudgetDimension, BudgetError, BudgetProfile, ClockSample,
    EffectiveActivationBudget, ResourceBudget,
};
use std::sync::atomic::{AtomicU64, Ordering};
use wasmtime::{Engine, Ref, RefType, Store, Table, TableType};

const OVERHEAD: u64 = crate::native_tables::OWNER_ESCROW as u64;
const POINTER: u64 = size_of::<usize>() as u64;

pub(super) fn budget(memory: u64) -> ActivationBudget {
    let limits = ResourceBudget {
        cpu_fuel: 1_000_000_000,
        memory_bytes: memory,
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
    let grant = EffectiveActivationBudget::admit_profile_at(
        BudgetProfile::Phase3,
        &limits,
        &limits,
        &limits,
        None,
        ClockSample::system_now(),
    )
    .unwrap();
    ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap()
}

struct Data {
    limiter: Option<TrackingLimiter>,
    budget: ActivationBudget,
    after_limiter_destruction: Arc<AtomicU64>,
}
impl Drop for Data {
    fn drop(&mut self) {
        // The public Store destroys user data before real instance tables. A
        // guard only in its limiter would already be gone at this observation.
        drop(self.limiter.take());
        self.after_limiter_destruction
            .store(self.budget.host_memory_bytes(), Ordering::SeqCst);
    }
}
fn store(engine: &Engine, budget: &ActivationBudget) -> (Store<Data>, Arc<AtomicU64>) {
    let observed = Arc::new(AtomicU64::new(u64::MAX));
    let mut limiter = TrackingLimiter::with_config(
        budget.granted().memory_bytes as usize,
        &WasmtimeConfig::default(),
    );
    limiter.budget = Some(budget.clone());
    let mut store = Store::new(
        engine,
        Data {
            limiter: Some(limiter),
            budget: budget.clone(),
            after_limiter_destruction: observed.clone(),
        },
    );
    store.limiter(|data| data.limiter.as_mut().unwrap());
    (store, observed)
}
fn peak(budget: &ActivationBudget) -> u64 {
    budget.snapshot_at(Instant::now()).peak_memory_bytes
}
pub(super) fn denial(error: &wasmtime::Error, limit: u64, consumed: u64, requested: u64) {
    let error = error
        .chain()
        .find_map(|cause| cause.downcast_ref::<BudgetError>())
        .unwrap();
    assert!(matches!(error, BudgetError::Exhausted {
        dimension: BudgetDimension::MemoryBytes, limit: l, consumed: c, requested: r,
    } if (*l,*c,*r)==(limit,consumed,requested)));
}
fn fixed(store: &mut Store<Data>, size: u32) -> wasmtime::Result<Table> {
    Table::new(
        store,
        TableType::new(RefType::FUNCREF, size, Some(size)),
        Ref::Func(None),
    )
}

#[test]
fn actual_typescript_fixed_tables_debit_original_memory_and_outlive_limiter_destruction() {
    let engine = Engine::default();
    let budget = budget(64 * 1024 * 1024);
    let (mut store, observed) = store(&engine, &budget);
    fixed(&mut store, 7375).unwrap();
    fixed(&mut store, 17).unwrap();
    let retained = (7375 + 17) * POINTER + 2 * OVERHEAD;
    assert_eq!(budget.host_memory_bytes(), retained);
    assert_eq!(peak(&budget), retained);
    drop(store);
    assert_eq!(observed.load(Ordering::SeqCst), retained);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(peak(&budget), retained);
}

#[test]
fn actual_table_refusal_keeps_exact_original_memory_error_and_no_retained_owner() {
    let requested = 7375 * POINTER + OVERHEAD;
    let budget = budget(requested - 1);
    let (mut store, _) = store(&Engine::default(), &budget);
    let error = fixed(&mut store, 7375).unwrap_err();
    denial(&error, requested - 1, 0, requested);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(peak(&budget), 0);
}

fn populated(store: &mut Store<Data>) -> Table {
    let function = wasmtime::Func::wrap(&mut *store, || 42i32);
    Table::new(
        store,
        TableType::new(RefType::FUNCREF, 2, Some(6)),
        Ref::Func(Some(function)),
    )
    .unwrap()
}
fn values(store: &mut Store<Data>, table: Table, count: u64) {
    for index in 0..count {
        let Some(Ref::Func(Some(function))) = table.get(&mut *store, index) else {
            panic!("function lost")
        };
        assert_eq!(
            function
                .typed::<(), i32>(&*store)
                .unwrap()
                .call(&mut *store, ())
                .unwrap(),
            42
        );
    }
}

#[test]
fn actual_dynamic_table_growth_pays_exact_old_new_overlap_and_keeps_function_cells() {
    let budget = budget(4096);
    let (mut store, _) = store(&Engine::default(), &budget);
    let table = populated(&mut store);
    let old = 2 * POINTER + OVERHEAD;
    let new = 6 * POINTER + OVERHEAD;
    assert_eq!(budget.host_memory_bytes(), old);
    let Some(Ref::Func(Some(function))) = table.get(&mut store, 0) else {
        panic!("function lost")
    };
    assert_eq!(
        table
            .grow(&mut store, 4, Ref::Func(Some(function)))
            .unwrap(),
        2
    );
    values(&mut store, table, 6);
    assert_eq!(budget.host_memory_bytes(), new);
    assert_eq!(peak(&budget), old + new);
    drop(store);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn actual_dynamic_table_refused_replacement_keeps_original_cells_capacity_and_owner() {
    let old = 2 * POINTER + OVERHEAD;
    let new = 6 * POINTER + OVERHEAD;
    let limit = old + new - 1;
    let budget = budget(limit);
    let (mut store, _) = store(&Engine::default(), &budget);
    let table = populated(&mut store);
    let error = table.grow(&mut store, 4, Ref::Func(None)).unwrap_err();
    denial(&error, limit, old, new);
    assert_eq!(table.size(&store), 2);
    values(&mut store, table, 2);
    assert_eq!(budget.host_memory_bytes(), old);
    assert_eq!(peak(&budget), old);
    drop(store);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn actual_tiny_and_zero_tables_do_not_reserve_declared_maximum_capacity() {
    let budget = budget(POINTER + OVERHEAD);
    let (mut store, _) = store(&Engine::default(), &budget);
    Table::new(
        &mut store,
        TableType::new(RefType::FUNCREF, 0, Some(12_000)),
        Ref::Func(None),
    )
    .unwrap();
    assert_eq!(budget.host_memory_bytes(), 0);
    Table::new(
        &mut store,
        TableType::new(RefType::FUNCREF, 1, Some(12_000)),
        Ref::Func(None),
    )
    .unwrap();
    assert_eq!(budget.host_memory_bytes(), POINTER + OVERHEAD);
    drop(store);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn actual_preceding_linear_allocation_is_confirmed_before_table_memory_admission() {
    let page = 64 * 1024;
    let requested = POINTER + OVERHEAD;
    let limit = page + requested - 1;
    let budget = budget(limit);
    let (mut store, _) = store(&Engine::default(), &budget);
    wasmtime::Memory::new(&mut store, wasmtime::MemoryType::new(1, Some(1))).unwrap();
    let error = fixed(&mut store, 1).unwrap_err();
    denial(&error, limit, page, requested);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(peak(&budget), page);
}

#[test]
fn actual_original_element_and_table_count_caps_still_refuse_without_extra_owners() {
    let budget = budget(4096);
    let (mut store, _) = store(&Engine::default(), &budget);
    store.data_mut().limiter.as_mut().unwrap().limits = StoreLimitsBuilder::new()
        .table_elements(4)
        .tables(1)
        .trap_on_grow_failure(true)
        .build();
    // Instance/table counts are cached when the limiter is installed.
    store.limiter(|data| data.limiter.as_mut().unwrap());
    assert!(fixed(&mut store, 5).is_err());
    assert_eq!(budget.host_memory_bytes(), 0);
    // A failed instance can consume Wasmtime's original count allowance; use a
    // fresh Store rather than changing its lifetime/count semantics.
    drop(store);
    let (mut store, _) = self::store(&Engine::default(), &budget);
    store.data_mut().limiter.as_mut().unwrap().limits = StoreLimitsBuilder::new()
        .table_elements(4)
        .tables(1)
        .trap_on_grow_failure(true)
        .build();
    // Instance/table counts are cached when the limiter is installed.
    store.limiter(|data| data.limiter.as_mut().unwrap());
    // The original count cap applies to module instantiation. Host-created
    // Table::new values use dummy instances and do not bump those counters.
    let module = table_module(store.engine());
    wasmtime::Instance::new(&mut store, &module, &[]).unwrap();
    let retained = 2 * POINTER + OVERHEAD;
    let error = wasmtime::Instance::new(&mut store, &module, &[]).unwrap_err();
    assert!(error.to_string().contains("table count too high at 2"));
    assert_eq!(budget.host_memory_bytes(), retained);
    drop(store);
    assert_eq!(budget.host_memory_bytes(), 0);
}

fn pool(batch: usize) -> Engine {
    let mut pooling = wasmtime::PoolingAllocationConfig::new();
    pooling
        .total_component_instances(0)
        .total_core_instances(1)
        .total_memories(0)
        .total_tables(1)
        .table_elements(16)
        .decommit_batch_size(batch)
        .table_keep_resident(0)
        .max_unused_warm_slots(0);
    let mut config = wasmtime::Config::new();
    config.allocation_strategy(pooling);
    Engine::new(&config).unwrap()
}
fn table_module(engine: &Engine) -> wasmtime::Module {
    let mut module = wasm_encoder::Module::new();
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
    module.section(&exports);
    wasmtime::Module::new(engine, module.finish()).unwrap()
}

#[test]
fn actual_pooled_table_slot_keeps_owner_through_user_data_then_real_flush() {
    let engine = pool(1);
    let module = table_module(&engine);
    let budget = budget(64 * 1024);
    let (mut store, observed) = store(&engine, &budget);
    let instance = wasmtime::Instance::new(&mut store, &module, &[]).unwrap();
    let table = instance.get_table(&mut store, "table").unwrap();
    let function = wasmtime::Func::wrap(&mut store, || 42i32);
    // Make the actual pool page resident and nonzero; an untouched sparse page
    // could otherwise take the allocator's immediate-clear/no-decommit path.
    table.set(&mut store, 0, Ref::Func(Some(function))).unwrap();
    let retained = budget.host_memory_bytes();
    // A complete page-aligned pool slot is retained, not just 2 visible cells.
    assert!(retained >= 4096 + OVERHEAD);
    drop(store);
    assert_eq!(observed.load(Ordering::SeqCst), retained);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[test]
fn actual_batched_pool_table_keeps_original_owner_until_decommit_queue_destruction() {
    let engine = pool(64);
    let module = table_module(&engine);
    let budget = budget(64 * 1024);
    let (mut store, observed) = store(&engine, &budget);
    let instance = wasmtime::Instance::new(&mut store, &module, &[]).unwrap();
    let table = instance.get_table(&mut store, "table").unwrap();
    let function = wasmtime::Func::wrap(&mut store, || 42i32);
    // Make the actual pool page resident and nonzero; an untouched sparse page
    // could otherwise take the allocator's immediate-clear/no-decommit path.
    table.set(&mut store, 0, Ref::Func(Some(function))).unwrap();
    let retained = budget.host_memory_bytes();
    assert!(retained >= 4096 + OVERHEAD);
    drop(store);
    assert_eq!(observed.load(Ordering::SeqCst), retained);
    assert_eq!(budget.host_memory_bytes(), retained);
    drop(module);
    drop(engine);
    assert_eq!(budget.host_memory_bytes(), 0);
}

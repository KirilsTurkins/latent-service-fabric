//! Actual memory-only engine instances; no later table callback or terminal
//! accounting call can stand in for allocator success/failure notification.
use super::native_table_tests::budget;
use super::TrackingLimiter;
use latent_core::ActivationBudget;
use std::sync::{Arc, Mutex};
use std::time::Instant;
use wasmtime::{Config, Engine, Instance, Module, NativeMemoryBinding, Store};

const MIB: u64 = 1024 * 1024;
const PAGE: u64 = 64 * 1024;
const CORE: &[u8] = include_bytes!("native-linear-memory.wasm");

// Explicit controller storage is outside the invocation allocation claim.
struct Factory {
    budget: ActivationBudget,
    peaks: Arc<Mutex<Vec<u64>>>,
}
impl wasmtime::NativeMemory for Factory {
    fn reserve(&self, bytes: usize) -> wasmtime::Result<Box<dyn wasmtime::NativeAllocation>> {
        self.peaks
            .lock()
            .unwrap()
            .push(self.budget.snapshot_at(Instant::now()).peak_memory_bytes);
        Ok(crate::native_tables::reserve(&self.budget, bytes)?.unwrap())
    }
}
fn store(
    engine: &Engine,
    original: &ActivationBudget,
    peaks: Arc<Mutex<Vec<u64>>>,
) -> Store<TrackingLimiter> {
    let owner =
        crate::native_tables::reserve(original, NativeMemoryBinding::allocation_size::<Factory>())
            .unwrap()
            .unwrap();
    let binding = NativeMemoryBinding::new(
        Factory {
            budget: original.clone(),
            peaks,
        },
        owner,
    );
    let mut limiter = TrackingLimiter::new(MIB as usize);
    limiter.budget = Some(original.clone());
    let mut store = Store::try_new_with_memory_binding(engine, limiter, binding).unwrap();
    store.limiter(|limiter| limiter);
    store.set_fuel(1_000_000_000).unwrap();
    store
}
fn engine() -> Engine {
    Engine::new(Config::new().consume_fuel(true)).unwrap()
}

#[test]
fn actual_linear_memory_is_confirmed_before_subsequent_native_instance_allocations() {
    let engine = engine();
    let module = Module::new(&engine, CORE).unwrap();
    let original = budget(MIB);
    let peaks = Arc::new(Mutex::new(Vec::new()));
    let mut store = store(&engine, &original, peaks.clone());
    assert!(peaks.lock().unwrap().iter().all(|peak| *peak < 4 * PAGE));
    let instance = Instance::new(&mut store, &module, &[]).unwrap();
    // This module has no table. Native instance allocation after creating the
    // actual memory must already observe its four accessible pages.
    assert!(peaks.lock().unwrap().iter().any(|peak| *peak >= 4 * PAGE));
    assert!(store.data().pending_memory_growth.is_none());
    assert_eq!(store.data().peak_memory_bytes(), 4 * PAGE);
    assert_eq!(
        instance
            .get_typed_func::<(), i32>(&mut store, "answer")
            .unwrap()
            .call(&mut store, ())
            .unwrap(),
        42
    );
    drop(store);
    assert_eq!(original.host_memory_bytes(), 0);
}

struct RefusingCreator;
// No memory or pointer escapes: the creator always returns its original error.
unsafe impl wasmtime::MemoryCreator for RefusingCreator {
    fn new_memory(
        &self,
        _: wasmtime::MemoryType,
        _: usize,
        _: Option<usize>,
        _: Option<usize>,
        _: usize,
    ) -> Result<Box<dyn wasmtime::LinearMemory>, String> {
        Err("native-linear-original-creator-refusal".into())
    }
}

#[test]
fn actual_linear_creator_failure_rolls_back_without_confirming_unallocated_pages() {
    let engine = Engine::new(
        Config::new()
            .consume_fuel(true)
            .with_host_memory(Arc::new(RefusingCreator)),
    )
    .unwrap();
    let module = Module::new(&engine, CORE).unwrap();
    let original = budget(MIB);
    let mut store = store(&engine, &original, Arc::new(Mutex::new(Vec::new())));
    let error = Instance::new(&mut store, &module, &[]).unwrap_err();
    assert!(format!("{error:#}").contains("native-linear-original-creator-refusal"));
    assert!(store.data().pending_memory_growth.is_none());
    assert_eq!(store.data().current_memory_bytes(), 0);
    assert_eq!(store.data().peak_memory_bytes(), 0);
    assert!(original.snapshot_at(Instant::now()).peak_memory_bytes < 4 * PAGE);
    // A failed creator leaves no pending reservation in the original ledger.
    drop(original.reserve_runtime_memory(4 * PAGE).unwrap());
    drop(store);
    assert_eq!(original.host_memory_bytes(), 0);
}

#[test]
fn actual_linear_growth_confirms_success_and_failed_growth_preserves_prior_peak() {
    let engine = engine();
    let module = Module::new(&engine, CORE).unwrap();
    let original = budget(MIB);
    let mut store = store(&engine, &original, Arc::new(Mutex::new(Vec::new())));
    let instance = Instance::new(&mut store, &module, &[]).unwrap();
    let memory = instance.get_memory(&mut store, "memory").unwrap();
    assert_eq!(memory.grow(&mut store, 1).unwrap(), 4);
    assert_eq!(memory.size(&store), 5);
    assert!(store.data().pending_memory_growth.is_none());
    assert_eq!(store.data().peak_memory_bytes(), 5 * PAGE);
    let peak = original.snapshot_at(Instant::now()).peak_memory_bytes;
    assert!(peak >= 5 * PAGE);
    assert!(memory.grow(&mut store, 1).is_err());
    assert!(store.data().pending_memory_growth.is_none());
    assert_eq!(memory.size(&store), 5);
    assert_eq!(store.data().peak_memory_bytes(), 5 * PAGE);
    assert_eq!(original.snapshot_at(Instant::now()).peak_memory_bytes, peak);
    drop(store);
    assert_eq!(original.host_memory_bytes(), 0);
}

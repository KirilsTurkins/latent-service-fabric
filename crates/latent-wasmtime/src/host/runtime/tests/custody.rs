//! Actual Store control for the original runtime Table's retirement order.
//!
//! The observation wrapper is test-owned; its reservation delegates to the
//! same original budget as the production binding. It does not observe OS
//! unmap success or execute the TypeScript guest.

use super::*;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use wasmtime::{Engine, Instance, Module, NativeMemoryBinding, Store};

struct Observation {
    runtime: ActivationRuntime,
    active: Arc<crate::cache::ActiveInstanceGate>,
    observed: AtomicBool,
    native_owners: AtomicUsize,
    permits: AtomicUsize,
    panic_once: AtomicBool,
}

struct ObservedAllocation {
    original: Box<dyn wasmtime::NativeAllocation>,
    observation: Arc<Observation>,
}

impl wasmtime::NativeAllocation for ObservedAllocation {
    fn allocated(&mut self) {
        self.original.allocated();
    }
}

impl Drop for ObservedAllocation {
    fn drop(&mut self) {
        let snapshot = self.observation.runtime.snapshot();
        // Only HostState/Table destruction cancels this test runtime. Ignore
        // any earlier manual-cleanup allocation, before user data is dropped.
        if snapshot.phase == RuntimePhase::Cancelling
            && !self.observation.observed.swap(true, Ordering::SeqCst)
        {
            self.observation
                .native_owners
                .store(snapshot.owners[6] as usize, Ordering::SeqCst);
            self.observation
                .permits
                .store(self.observation.active.active(), Ordering::SeqCst);
            if self.observation.panic_once.swap(false, Ordering::SeqCst) {
                panic!("single test-injected StoreInner allocation destructor panic");
            }
        }
    }
}

struct ObservedFactory {
    budget: ActivationBudget,
    observation: Arc<Observation>,
    // Like the production factory, retain only the cell, not another factory
    // Arc that could outlive NativeMemoryBinding's original reservation.
    _custody: Option<crate::store_custody::Custody>,
}

impl wasmtime::NativeMemory for ObservedFactory {
    fn reserve(&self, bytes: usize) -> wasmtime::Result<Box<dyn wasmtime::NativeAllocation>> {
        let original = crate::native_tables::reserve(&self.budget, bytes)?
            .expect("the native factory requests nonzero backing");
        Ok(Box::new(ObservedAllocation {
            original,
            observation: Arc::clone(&self.observation),
        }))
    }
}

fn binding(
    budget: &ActivationBudget,
    observation: Arc<Observation>,
    custody: Option<crate::store_custody::Custody>,
) -> NativeMemoryBinding {
    let bytes = NativeMemoryBinding::allocation_size::<ObservedFactory>();
    let original = crate::native_tables::reserve(budget, bytes)
        .unwrap()
        .unwrap();
    NativeMemoryBinding::new(
        ObservedFactory {
            budget: budget.clone(),
            observation,
            _custody: custody,
        },
        original,
    )
}

fn instantiate_with_linear_memory(store: &mut Store<HostState>, module: &Module) {
    const PAGE: u64 = 64 * 1024;
    store.limiter(|state| &mut state.limiter);
    let instance = Instance::new(&mut *store, module, &[]).unwrap();
    let memory = instance.get_memory(&mut *store, "memory").unwrap();
    assert_eq!(memory.data_size(&*store), (4 * PAGE) as usize);
    let mut bytes = [0; 13];
    memory.read(&*store, 0, &mut bytes).unwrap();
    assert_eq!(&bytes, b"actual-memory");
    let answer = instance
        .get_typed_func::<(), i32>(&mut *store, "answer")
        .unwrap();
    assert_eq!(answer.call(&mut *store, ()).unwrap(), 42);
    assert_eq!(store.data().limiter.peak_memory_bytes(), 4 * PAGE);
    assert!(
        store
            .data()
            .accounting
            .budget()
            .snapshot_at(Instant::now())
            .peak_memory_bytes
            >= 4 * PAGE
    );
}

#[test]
fn actual_store_destruction_keeps_the_original_native_owner_until_inner_retires() {
    let engine = Engine::default();
    let module = Module::new(&engine, include_bytes!("../../native-linear-memory.wasm")).unwrap();

    for selected in [false, true] {
        let budget = budget(64 * 1024 * 1024);
        let mut state = crate::host::native_context_reply_tests::state(&budget, true);
        let limits = RuntimeLimits {
            native_owners: 1,
            ..limits(0)
        };
        state.runtime_limits = Some(limits);
        let table = table(&mut state).unwrap();
        let runtime = table.runtime.clone();
        let owner = runtime.register(OwnerKind::Native, None).unwrap();
        table.owners.push(owner);

        let active = Arc::new(crate::cache::ActiveInstanceGate::new(1).unwrap());
        let mut permit = Some(active.try_acquire().unwrap());
        let custody = selected.then(|| {
            crate::store_custody::Custody::prepare(&budget)
                .unwrap()
                .attach(Arc::new(()), permit.take().unwrap())
        });
        state.store_custody = custody.clone();
        let observation = Arc::new(Observation {
            runtime: runtime.clone(),
            active: Arc::clone(&active),
            observed: AtomicBool::new(false),
            native_owners: AtomicUsize::new(usize::MAX),
            permits: AtomicUsize::new(usize::MAX),
            panic_once: AtomicBool::new(false),
        });
        let mut store = Store::try_new_with_memory_binding(
            &engine,
            state,
            binding(&budget, Arc::clone(&observation), custody.clone()),
        )
        .unwrap();
        instantiate_with_linear_memory(&mut store, &module);
        assert_eq!(runtime.snapshot().owners[6], 1);

        drop(store);
        assert!(observation.observed.load(Ordering::SeqCst));
        assert_eq!(observation.permits.load(Ordering::SeqCst), 1);
        assert_eq!(
            observation.native_owners.load(Ordering::SeqCst),
            usize::from(selected),
            "the original path drops the Native owner before StoreInner"
        );
        assert_eq!(runtime.snapshot().owners[6], u32::from(selected));

        if let Some(custody) = &custody {
            custody.verified();
        }
        drop(custody);
        drop(permit);
        assert_eq!(active.active(), 0);
        assert_eq!(runtime.snapshot().owners[6], 0);
        drop(observation);
        drop(runtime);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
    }
}

#[test]
fn single_injected_store_inner_panic_retains_owner_and_poisons_only_test_cohort() {
    let engine = Engine::default();
    let module = Module::new(&engine, include_bytes!("../../native-linear-memory.wasm")).unwrap();
    let budget = budget(64 * 1024 * 1024);
    let mut state = crate::host::native_context_reply_tests::state(&budget, true);
    state.runtime_limits = Some(RuntimeLimits {
        native_owners: 1,
        ..limits(0)
    });
    let table = table(&mut state).unwrap();
    let runtime = table.runtime.clone();
    let owner = runtime.register(OwnerKind::Native, None).unwrap();
    table.owners.push(owner);

    let active = Arc::new(crate::cache::ActiveInstanceGate::new(1).unwrap());
    let custody = crate::store_custody::Custody::prepare(&budget)
        .unwrap()
        .attach(Arc::new(()), active.try_acquire().unwrap());
    state.store_custody = Some(custody.clone());
    let observation = Arc::new(Observation {
        runtime: runtime.clone(),
        active: Arc::clone(&active),
        observed: AtomicBool::new(false),
        native_owners: AtomicUsize::new(usize::MAX),
        permits: AtomicUsize::new(usize::MAX),
        panic_once: AtomicBool::new(true),
    });
    let mut store = Store::try_new_with_memory_binding(
        &engine,
        state,
        binding(&budget, Arc::clone(&observation), Some(custody.clone())),
    )
    .unwrap();
    instantiate_with_linear_memory(&mut store, &module);

    // The production static is never touched by this injected panic. The
    // local state and deliberately quarantined owners live only in this test
    // process. No operating-system unmap failure is being simulated.
    let cohort: &'static AtomicUsize = Box::leak(Box::new(AtomicUsize::new(0)));
    let admission = crate::store_custody::Admission::enter_with_test_state(cohort).unwrap();
    let wrapped = crate::backend::custody_test_wrap_store(store, admission, custody.clone());
    let failure = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(wrapped)));
    assert!(failure.is_err());
    assert!(observation.observed.load(Ordering::SeqCst));
    assert!(!observation.panic_once.load(Ordering::SeqCst));
    assert_eq!(observation.native_owners.load(Ordering::SeqCst), 1);
    assert_eq!(observation.permits.load(Ordering::SeqCst), 1);
    assert!(crate::store_custody::Admission::enter_with_test_state(cohort).is_err());
    drop(custody);
    assert_eq!(runtime.snapshot().owners[6], 1);
    assert_eq!(active.active(), 1);
    assert!(budget.host_memory_bytes() > 0);
}

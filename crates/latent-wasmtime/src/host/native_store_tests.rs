//! Planned actual engine Store/instance ownership controls; no guest build.
use super::native_table_tests::{budget, denial};
use latent_core::ActivationBudget;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use wasmtime::{Engine, Instance, Module, NativeMemoryBinding, Store};

pub(super) const OWNER: u64 = crate::native_tables::OWNER_ESCROW as u64;
pub(super) const MIB: u64 = 1024 * 1024;
pub(super) const CORE: &[u8] = include_bytes!("native-store-core.wasm");
const COMPONENT: &[u8] = include_bytes!("native-store-component.wasm");

// Test-controller observations are outside the invocation allocation claim.
#[derive(Default)]
pub(super) struct Observations {
    requests: Mutex<Vec<usize>>,
    allocations: Mutex<Vec<AllocationRow>>,
    before_request: Mutex<Option<(usize, Box<dyn FnOnce(usize) + Send>)>>,
    data_drops: AtomicUsize,
    pub(super) factory_drops: AtomicUsize,
    pub(super) data_charge: AtomicU64,
    factory_charge: AtomicU64,
}
// This test-controller record observes the ORIGINAL admission and ticket;
// it neither changes the byte request nor supplies another payer/credit ledger.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct AllocationRow {
    pub(super) bytes: usize,
    pub(super) admitted: bool,
    pub(super) confirmed: bool,
    pub(super) released: bool,
}
struct ObservedAllocation {
    allocation: Option<Box<dyn wasmtime::NativeAllocation>>,
    observations: Arc<Observations>,
    ordinal: usize,
}
impl wasmtime::NativeAllocation for ObservedAllocation {
    fn allocated(&mut self) {
        self.allocation.as_mut().unwrap().allocated();
        self.observations.allocations.lock().unwrap()[self.ordinal].confirmed = true;
    }
}
impl Drop for ObservedAllocation {
    fn drop(&mut self) {
        // Observe release AFTER the real original ticket has actually dropped.
        drop(self.allocation.take());
        self.observations.allocations.lock().unwrap()[self.ordinal].released = true;
    }
}
pub(super) fn allocation_rows(observations: &Observations) -> Vec<AllocationRow> {
    observations.allocations.lock().unwrap().clone()
}

impl Observations {
    // Test-controller seam: run once immediately before an actual native
    // reservation. The callback cannot replace or fabricate the admission.
    pub(super) fn before_request(
        &self,
        ordinal: usize,
        callback: impl FnOnce(usize) + Send + 'static,
    ) {
        assert!(ordinal > self.requests.lock().unwrap().len());
        let mut before = self.before_request.lock().unwrap();
        assert!(before.is_none());
        *before = Some((ordinal, Box::new(callback)));
    }
}
struct Factory {
    budget: ActivationBudget,
    observations: Arc<Observations>,
}
impl wasmtime::NativeMemory for Factory {
    fn reserve(&self, bytes: usize) -> wasmtime::Result<Box<dyn wasmtime::NativeAllocation>> {
        let ordinal = {
            let mut requests = self.observations.requests.lock().unwrap();
            self.observations
                .allocations
                .lock()
                .unwrap()
                .push(AllocationRow {
                    bytes,
                    admitted: false,
                    confirmed: false,
                    released: false,
                });
            requests.push(bytes);
            requests.len()
        };
        let callback = {
            let mut before = self.observations.before_request.lock().unwrap();
            if before
                .as_ref()
                .is_some_and(|(target, _)| *target == ordinal)
            {
                before.take()
            } else {
                None
            }
        };
        if let Some((_, callback)) = callback {
            callback(bytes);
        }
        let allocation = crate::native_tables::reserve(&self.budget, bytes)?.unwrap();
        self.observations.allocations.lock().unwrap()[ordinal - 1].admitted = true;
        Ok(Box::new(ObservedAllocation {
            allocation: Some(allocation),
            observations: self.observations.clone(),
            ordinal: ordinal - 1,
        }))
    }
}
impl Drop for Factory {
    fn drop(&mut self) {
        self.observations
            .factory_charge
            .store(self.budget.host_memory_bytes(), Ordering::SeqCst);
        self.observations
            .factory_drops
            .fetch_add(1, Ordering::SeqCst);
    }
}
pub(super) struct Data {
    budget: ActivationBudget,
    observations: Arc<Observations>,
}
impl Drop for Data {
    fn drop(&mut self) {
        self.observations
            .data_charge
            .store(self.budget.host_memory_bytes(), Ordering::SeqCst);
        self.observations.data_drops.fetch_add(1, Ordering::SeqCst);
    }
}
fn factory_bytes() -> u64 {
    NativeMemoryBinding::allocation_size::<Factory>() as u64 + OWNER
}
pub(super) fn store(
    engine: &Engine,
    budget: &ActivationBudget,
    observations: &Arc<Observations>,
) -> wasmtime::Result<Store<Data>> {
    let binding = binding(budget, observations)?;
    Store::try_new_with_memory_binding(
        engine,
        Data {
            budget: budget.clone(),
            observations: observations.clone(),
        },
        binding,
    )
}
pub(super) fn binding(
    budget: &ActivationBudget,
    observations: &Arc<Observations>,
) -> wasmtime::Result<NativeMemoryBinding> {
    let owner =
        crate::native_tables::reserve(budget, NativeMemoryBinding::allocation_size::<Factory>())?
            .unwrap();
    Ok(NativeMemoryBinding::new(
        Factory {
            budget: budget.clone(),
            observations: observations.clone(),
        },
        owner,
    ))
}
pub(super) fn requests(observations: &Observations) -> Vec<usize> {
    observations.requests.lock().unwrap().clone()
}
pub(super) fn core_answer(instance: Instance, store: &mut Store<Data>) -> i32 {
    instance
        .get_typed_func::<(), i32>(&mut *store, "answer")
        .unwrap()
        .call(store, ())
        .unwrap()
}

#[test]
fn actual_store_box_refusal_preserves_original_error_and_exactly_once_data_drop() {
    let engine = Engine::default();
    let budget = budget(factory_bytes());
    let observed = Arc::new(Observations::default());
    let error = store(&engine, &budget, &observed).err().unwrap();
    let allocations = requests(&observed);
    assert_eq!(allocations.len(), 1);
    denial(
        &error,
        factory_bytes(),
        factory_bytes(),
        allocations[0] as u64 + OWNER,
    );
    assert_eq!(observed.data_drops.load(Ordering::SeqCst), 1);
    assert_eq!(observed.factory_drops.load(Ordering::SeqCst), 1);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn actual_dummy_instance_refusal_rolls_back_box_map_factory_and_user_data() {
    let engine = Engine::default();
    let baseline = budget(64 * MIB);
    let baseline_observed = Arc::new(Observations::default());
    let initial = store(&engine, &baseline, &baseline_observed).unwrap();
    let allocations = requests(&baseline_observed);
    // StoreInner, initial instance-owner map, then exact dummy+VMContext Layout.
    assert_eq!(allocations.len(), 3);
    drop(initial);
    assert_eq!(baseline.host_memory_bytes(), 0);
    let consumed = factory_bytes()
        + allocations[..2]
            .iter()
            .map(|n| *n as u64 + OWNER)
            .sum::<u64>();
    let requested = allocations[2] as u64 + OWNER;
    let limit = consumed + requested - 1;
    let budget = budget(limit);
    let observed = Arc::new(Observations::default());
    let error = store(&engine, &budget, &observed).err().unwrap();
    denial(&error, limit, consumed, requested);
    assert_eq!(requests(&observed), allocations);
    assert_eq!(observed.data_drops.load(Ordering::SeqCst), 1);
    assert_eq!(observed.factory_drops.load(Ordering::SeqCst), 1);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn actual_store_core_and_component_owners_outlive_user_data_until_physical_cleanup() {
    let engine = Engine::default();
    let module = Module::new(&engine, CORE).unwrap();
    let component = wasmtime::component::Component::new(&engine, COMPONENT).unwrap();
    let budget = budget(64 * MIB);
    let observed = Arc::new(Observations::default());
    let mut store = store(&engine, &budget, &observed).unwrap();
    let before_instances = budget.host_memory_bytes();
    let instance = Instance::new(&mut store, &module, &[]).unwrap();
    assert_eq!(core_answer(instance, &mut store), 42);
    let after_core = budget.host_memory_bytes();
    assert!(after_core > before_instances);
    let linker = wasmtime::component::Linker::new(&engine);
    linker.instantiate(&mut store, &component).unwrap();
    let retained = budget.host_memory_bytes();
    assert!(retained > after_core);
    let store_box = requests(&observed)[0] as u64 + OWNER;
    drop(store);
    assert_eq!(observed.data_charge.load(Ordering::SeqCst), retained);
    // All engine buffers/instances are gone before the sole factory Arc; its
    // own backing and the physically freed Store Box remain conservatively paid
    // until their outer affine owners are discharged in order.
    assert_eq!(
        observed.factory_charge.load(Ordering::SeqCst),
        factory_bytes() + store_box
    );
    assert_eq!(observed.data_drops.load(Ordering::SeqCst), 1);
    assert_eq!(observed.factory_drops.load(Ordering::SeqCst), 1);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn actual_into_data_frees_inner_and_factory_before_returning_once_owned_data() {
    let engine = Engine::default();
    let module = Module::new(&engine, CORE).unwrap();
    let budget = budget(MIB);
    let observed = Arc::new(Observations::default());
    let mut store = store(&engine, &budget, &observed).unwrap();
    Instance::new(&mut store, &module, &[]).unwrap();
    let data = store.into_data();
    assert_eq!(observed.factory_drops.load(Ordering::SeqCst), 1);
    assert_eq!(observed.data_drops.load(Ordering::SeqCst), 0);
    assert_eq!(budget.host_memory_bytes(), 0);
    drop(data);
    assert_eq!(observed.data_drops.load(Ordering::SeqCst), 1);
}

#[test]
fn actual_user_data_unwind_cannot_refund_the_still_allocated_store() {
    struct Panics(Arc<AtomicUsize>);
    impl Drop for Panics {
        fn drop(&mut self) {
            self.0.fetch_add(1, Ordering::SeqCst);
            panic!("bounded user-data destructor unwind");
        }
    }
    let engine = Engine::default();
    let original = budget(MIB);
    let observed = Arc::new(Observations::default());
    let drops = Arc::new(AtomicUsize::new(0));
    let store = Store::try_new_with_memory_binding(
        &engine,
        Panics(drops.clone()),
        binding(&original, &observed).unwrap(),
    )
    .unwrap();
    let retained = original.host_memory_bytes();
    assert!(retained > factory_bytes());
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(store)));
    assert!(result.is_err());
    assert_eq!(drops.load(Ordering::SeqCst), 1);
    // Existing Wasmtime cannot finish the manual Box destruction after T
    // panics. This one bounded test intentionally leaves that real allocation
    // and its owners charged; do not invent a refund or invoke T twice.
    assert_eq!(original.host_memory_bytes(), retained);
    assert_eq!(observed.factory_drops.load(Ordering::SeqCst), 0);
    let requested = MIB - retained + 1;
    let error = original.reserve_host_memory(requested).unwrap_err();
    denial(&wasmtime::Error::new(error), MIB, retained, requested);
    let independent = budget(MIB);
    let fresh = self::store(&engine, &independent, &observed).unwrap();
    drop(fresh);
    assert_eq!(independent.host_memory_bytes(), 0);
    assert_eq!(original.host_memory_bytes(), retained);
}

#[test]
fn actual_instance_map_overlap_refusal_preserves_prior_instance_and_fresh_reuse() {
    let engine = Engine::default();
    let module = Module::new(&engine, CORE).unwrap();
    let baseline = budget(64 * MIB);
    let baseline_observed = Arc::new(Observations::default());
    let mut initial = store(&engine, &baseline, &baseline_observed).unwrap();
    Instance::new(&mut initial, &module, &[]).unwrap();
    let retained = baseline.host_memory_bytes();
    let before_second = requests(&baseline_observed).len();
    Instance::new(&mut initial, &module, &[]).unwrap();
    let all = requests(&baseline_observed);
    // Reusing the same registered module needs only the instance-owner map
    // replacement and its new VMContext. Measure their actual layouts rather
    // than depending on the number of earlier registry allocations.
    assert_eq!(all.len() - before_second, 2);
    let replacement = all[before_second] as u64 + OWNER;
    drop(initial);
    assert_eq!(baseline.host_memory_bytes(), 0);
    let limit = retained + replacement - 1;
    let budget = budget(limit);
    let observed = Arc::new(Observations::default());
    let mut store = store(&engine, &budget, &observed).unwrap();
    let instance = Instance::new(&mut store, &module, &[]).unwrap();
    assert_eq!(budget.host_memory_bytes(), retained);
    let error = Instance::new(&mut store, &module, &[]).err().unwrap();
    denial(&error, limit, retained, replacement);
    assert_eq!(budget.host_memory_bytes(), retained);
    assert_eq!(core_answer(instance, &mut store), 42);
    drop(store);
    assert_eq!(budget.host_memory_bytes(), 0);
    let mut fresh = self::store(&engine, &budget, &observed).unwrap();
    let instance = Instance::new(&mut fresh, &module, &[]).unwrap();
    assert_eq!(core_answer(instance, &mut fresh), 42);
    drop(fresh);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn actual_passive_segment_backing_remains_owned_until_guest_elem_drop() {
    let engine = Engine::default();
    let module = Module::new(&engine, include_bytes!("native-store-passive.wasm")).unwrap();
    let budget = budget(MIB);
    let observed = Arc::new(Observations::default());
    let mut store = store(&engine, &budget, &observed).unwrap();
    let instance = Instance::new(&mut store, &module, &[]).unwrap();
    let retained = budget.host_memory_bytes();
    instance
        .get_typed_func::<(), ()>(&mut store, "clear")
        .unwrap()
        .call(&mut store, ())
        .unwrap();
    assert_eq!(
        retained - budget.host_memory_bytes(),
        3 * size_of::<wasmtime::ValRaw>() as u64 + OWNER
    );
    drop(store);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn actual_tiny_component_still_fits_original_one_mib_and_one_billion_fuel() {
    let mut config = wasmtime::Config::new();
    config.wasm_component_model(true).consume_fuel(true);
    let engine = Engine::new(&config).unwrap();
    let component = wasmtime::component::Component::new(&engine, COMPONENT).unwrap();
    let budget = budget(MIB);
    let observed = Arc::new(Observations::default());
    let mut store = store(&engine, &budget, &observed).unwrap();
    let fuel = budget.granted().cpu_fuel;
    store.set_fuel(fuel).unwrap();
    let linker = wasmtime::component::Linker::new(&engine);
    let instance = linker.instantiate(&mut store, &component).unwrap();
    let function = instance
        .get_typed_func::<(), (u32,)>(&mut store, "answer")
        .unwrap();
    // TypedFunc::call completes the pinned engine's post_return_impl itself.
    assert_eq!(function.call(&mut store, ()).unwrap(), (42,));
    assert!(store.get_fuel().unwrap() < fuel);
    assert_eq!(budget.granted().memory_bytes, MIB);
    assert_eq!(budget.granted().cpu_fuel, 1_000_000_000);
    assert!(budget.host_memory_bytes() < MIB);
    drop(store);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[tokio::test]
async fn actual_cancelled_lift_preserves_store_owners_and_cannot_credit_another_live_store() {
    use std::future::Future;
    use std::task::{Context, Poll, Wake, Waker};
    struct Noop;
    impl Wake for Noop {
        fn wake(self: Arc<Self>) {}
    }
    let mut config = wasmtime::Config::new();
    config
        .wasm_component_model(true)
        .wasm_component_model_async(true)
        .concurrency_support(true)
        .consume_fuel(true);
    let engine = Engine::new(&config).unwrap();
    let component = wasmtime::component::Component::new(
        &engine,
        include_bytes!("../values/host-memory-accounted.wasm"),
    )
    .unwrap();
    let entered = Arc::new(std::sync::atomic::AtomicBool::new(false));
    let called = entered.clone();
    let mut linker = wasmtime::component::Linker::<Data>::new(&engine);
    linker
        .root()
        .func_wrap_async("wait", move |_, (): ()| {
            // The committed fixture's selected post-return uses a legal Core
            // fuel-yield loop; this forbidden import must never be entered.
            called.store(true, Ordering::SeqCst);
            Box::new(async { Ok(()) })
        })
        .unwrap();
    let budget = budget(MIB);
    let observed = Arc::new(Observations::default());
    let mut first = store(&engine, &budget, &observed).unwrap();
    first.set_fuel(1_000_000).unwrap();
    first.fuel_async_yield_interval(Some(1000)).unwrap();
    first.set_hostcall_fuel(128 * 1024);
    let instance = linker
        .instantiate_async(&mut first, &component)
        .await
        .unwrap();
    let function = instance.get_func(&mut first, "echo-post").unwrap();
    // Initialize the SAME paid set without calling the guest. The lazy stub
    // and ready headers belong to this Store until it is actually destroyed;
    // they must be in the original post-cancellation Store baseline below.
    let before_shared = requests(&observed).len();
    let before_shared_bytes = budget.host_memory_bytes();
    let before_shared_fuel = first.get_fuel().unwrap();
    first.run_concurrent(async |_| ()).await.unwrap();
    assert_eq!(first.get_fuel().unwrap(), before_shared_fuel);
    assert!(!entered.load(Ordering::SeqCst));
    let allocated = requests(&observed);
    let shared = &allocated[before_shared..];
    assert_eq!(shared.len(), 2);
    assert!(shared.iter().all(|bytes| *bytes > 0));
    let shared_bytes = shared
        .iter()
        .map(|bytes| *bytes as u64 + OWNER)
        .sum::<u64>();
    assert_eq!(
        budget.host_memory_bytes(),
        before_shared_bytes + shared_bytes
    );
    println!(
        "LSF_CANCELLED_LIFT_SHARED_BASELINE_V1 headers=2 bytes={} fuel-unchanged=true",
        shared_bytes
    );
    // Instantiation already left three free table slots with retained paid backing.
    let store_bytes = budget.host_memory_bytes();
    let before_call = allocation_rows(&observed);
    let live_bytes = |rows: &[AllocationRow]| {
        rows.iter()
            .filter(|row| row.admitted && !row.released)
            .map(|row| row.bytes as u64 + OWNER)
            .sum::<u64>()
    };
    assert_eq!(store_bytes, factory_bytes() + live_bytes(&before_call));
    let json = serde_json::to_vec(&vec!["x".repeat(8192)]).unwrap();
    let input = crate::values::decode_params_accounted(
        &[wasmtime::component::Type::String],
        &json,
        crate::values::MEDIA_TYPE,
        crate::ValueCodecLimits::default(),
        &budget,
    )
    .unwrap();
    let mut output = crate::values::OwnedValues::output_accounted(1, &budget).unwrap();
    let scope = output.lift_memory().unwrap();
    let caller_bytes = budget.host_memory_bytes();
    let mut call = Box::pin(function.call_async_with_memory(
        &mut first,
        input.as_slice(),
        output.as_mut_slice(),
        scope,
    ));
    let waker = Waker::from(Arc::new(Noop));
    let state = call.as_mut().poll(&mut Context::from_waker(&waker));
    assert!(
        matches!(state, Poll::Pending),
        "legal post-return yielded {state:?}"
    );
    assert!(!entered.load(Ordering::SeqCst));
    assert!(budget.host_memory_bytes() > caller_bytes);
    drop(call);
    assert!(matches!(
        output.as_slice(),
        [wasmtime::component::Val::Bool(false)]
    ));
    drop(input);
    drop(output);
    // The legal post-return is still suspended: GuestTask/GuestThread and
    // ResourceTable's exact entry backing remain owned by this Store. Their
    // previously unpaid Boxes are now charged. Temporary call headers retire;
    // cancellation does not pretend the guest completed or delete its owners.
    let cancelled = allocation_rows(&observed);
    assert_eq!(&cancelled[..before_call.len()], before_call.as_slice());
    let call_rows = &cancelled[before_call.len()..];
    // prepare_call reserves channel/lower/lift, then GuestTask::new pushes
    // GuestTask/WaitableSet/GuestThread into the THREE already-free table slots.
    // queue_call adds its queue owner afterwards. The exact fixture has no
    // callback/import call: at suspended post-return, lower/lift were consumed,
    // but task_complete (and its sender send) has NOT run. These four owners,
    // and ONLY these owners, therefore remain with the original Store.
    let retained_roles = [
        (0, "call-result channel sender"),
        (3, "GuestTask"),
        (4, "implicit sync WaitableSet"),
        (5, "GuestThread"),
    ];
    assert!(
        call_rows.len() >= 7,
        "three prepare, three resources, then queue"
    );
    for (index, row) in call_rows.iter().enumerate() {
        let retained = retained_roles.iter().any(|(slot, _)| *slot == index);
        assert!(row.admitted && (row.confirmed || row.released));
        assert_eq!(row.released, !retained, "source call admission {index}");
    }
    assert!(call_rows[1].confirmed && call_rows[2].confirmed);
    let retained_bytes = retained_roles
        .iter()
        .map(|(slot, _)| call_rows[*slot].bytes as u64 + OWNER)
        .sum::<u64>();
    let cancelled_store_bytes = store_bytes + retained_bytes;
    assert_eq!(budget.host_memory_bytes(), cancelled_store_bytes);
    assert!(cancelled_store_bytes > store_bytes);
    let second = store(&engine, &budget, &observed).unwrap();
    let both = budget.host_memory_bytes();
    assert!(both > cancelled_store_bytes);
    drop(first);
    assert!(allocation_rows(&observed)[..cancelled.len()]
        .iter()
        .all(|row| !row.admitted || row.released));
    assert_eq!(budget.host_memory_bytes(), both - cancelled_store_bytes);
    drop(second);
    assert!(allocation_rows(&observed)
        .iter()
        .all(|row| !row.admitted || row.released));
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

#[test]
fn actual_factory_arc_layout_includes_overalignment_and_both_pinned_counters() {
    // The C ABI carries transparent context references to StoreInner, not the
    // now-expanded owning Store wrapper. Moving the wrapper must preserve them.
    assert_eq!(
        size_of::<wasmtime::StoreContext<'_, ()>>(),
        size_of::<usize>()
    );
    assert_eq!(
        size_of::<wasmtime::StoreContextMut<'_, ()>>(),
        size_of::<usize>()
    );
    assert!(size_of::<Store<()>>() > size_of::<usize>());
    let engine = Engine::default();
    let budget = budget(MIB);
    let observed = Arc::new(Observations::default());
    let store = store(&engine, &budget, &observed).unwrap();
    let data = core::ptr::from_ref(store.data());
    let moved = Box::new(store);
    assert_eq!(core::ptr::from_ref(moved.data()), data);
    drop(moved);
    assert_eq!(budget.host_memory_bytes(), 0);
    #[repr(align(64))]
    struct AlignedFactory;
    impl wasmtime::NativeMemory for AlignedFactory {
        fn reserve(&self, _: usize) -> wasmtime::Result<Box<dyn wasmtime::NativeAllocation>> {
            unreachable!("layout-only factory is never installed")
        }
    }
    #[repr(C, align(2))]
    struct PinnedArcInner<T> {
        strong: AtomicUsize,
        weak: AtomicUsize,
        data: T,
    }
    assert_eq!(
        NativeMemoryBinding::allocation_size::<Factory>(),
        size_of::<PinnedArcInner<Factory>>()
    );
    assert_eq!(
        NativeMemoryBinding::allocation_size::<AlignedFactory>(),
        size_of::<PinnedArcInner<AlignedFactory>>()
    );
    assert_eq!(NativeMemoryBinding::allocation_size::<AlignedFactory>(), 64);
}

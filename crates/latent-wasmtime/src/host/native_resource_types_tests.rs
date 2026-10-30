//! Planned engine controls for resource metadata that can escape its Store.
use super::native_store_tests::{requests, store, Data, Observations, MIB, OWNER};
use super::native_table_tests::{budget, denial};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Barrier, Mutex};
use wasmtime::component::{Component, Instance, Linker, ResourceType, Type};
use wasmtime::{Config, Engine, Store};

const COMPONENT: &[u8] = include_bytes!("native-resource-types.wasm");

fn linker(engine: &Engine) -> Linker<Data> {
    let mut linker = Linker::new(engine);
    linker
        .root()
        .resource("host-resource", ResourceType::host::<u32>(), |_, _| Ok(()))
        .unwrap();
    linker
}

fn answer(instance: Instance, store: &mut Store<Data>) -> u32 {
    instance
        .get_typed_func::<(), (u32,)>(&mut *store, "answer")
        .unwrap()
        .call(store, ())
        .unwrap()
        .0
}

fn host_type(function: &wasmtime::component::types::ComponentFunc) {
    let params: Vec<_> = function.params().collect();
    assert_eq!(params, [("value", Type::Own(ResourceType::host::<u32>()))]);
    assert_eq!(
        function.results().collect::<Vec<_>>(),
        [Type::Own(ResourceType::host::<u32>())]
    );
}

#[test]
fn actual_resource_types_pre_and_function_metadata_outlive_store_and_factory() {
    let engine = Engine::default();
    let component = Component::new(&engine, COMPONENT).unwrap();
    let budget = budget(MIB);
    let observed = Arc::new(Observations::default());
    let mut store = store(&engine, &budget, &observed).unwrap();
    let linker = linker(&engine);
    let instance = linker.instantiate(&mut store, &component).unwrap();
    assert_eq!(answer(instance, &mut store), 42);
    let guest = instance.get_resource(&mut store, "guest-resource").unwrap();
    let pre = instance.instance_pre(&store);
    let function = instance
        .get_func(&mut store, "host-pass")
        .unwrap()
        .ty(&store);
    host_type(&function);
    let types: Vec<_> = pre
        .instance_type()
        .resources
        .unwrap()
        .iter()
        .map(|(_, ty)| *ty)
        .collect();
    assert_eq!(types, [ResourceType::host::<u32>(), guest]);
    drop(linker);
    drop(store);
    assert_eq!(observed.factory_drops.load(Ordering::SeqCst), 1);
    let escaped = budget.host_memory_bytes();
    assert!(escaped > 0);
    assert_eq!(pre.instance_type().resources.unwrap().len(), 2);
    host_type(&function);
    drop(pre);
    assert_eq!(budget.host_memory_bytes(), escaped);
    host_type(&function);
    drop(function);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

struct Padding {
    // The actual allocation is destroyed before its original-budget owner.
    _bytes: Vec<u8>,
    _owner: Box<dyn wasmtime::NativeAllocation>,
}

#[test]
fn actual_resource_types_both_admission_refusals_preserve_prior_instance_and_retry() {
    let engine = Engine::default();
    let component = Component::new(&engine, COMPONENT).unwrap();
    let linker = linker(&engine);
    for refused in 0..2 {
        let budget = budget(MIB);
        let observed = Arc::new(Observations::default());
        let mut store = store(&engine, &budget, &observed).unwrap();
        let first = linker.instantiate(&mut store, &component).unwrap();
        let call = first
            .get_typed_func::<(), (u32,)>(&mut store, "answer")
            .unwrap();
        assert_eq!(call.call(&mut store, ()).unwrap(), (42,));
        let retained = budget.host_memory_bytes();
        let before = requests(&observed).len();
        let padding = Arc::new(Mutex::new(None::<Padding>));
        let consumed = Arc::new(AtomicU64::new(0));
        let requested = Arc::new(AtomicU64::new(0));
        let owned_padding = padding.clone();
        let owned_consumed = consumed.clone();
        let owned_requested = requested.clone();
        let original = budget.clone();
        // Module registration is deduplicated. ResourceTypes first admits the
        // exact two-slot map, then its Arc. Observe the actual target request;
        // do not estimate current usage by summing old allocation requests.
        observed.before_request(before + refused + 1, move |bytes| {
            let request = bytes as u64 + OWNER;
            let bytes = MIB - original.host_memory_bytes() - request + 1 - OWNER;
            let mut owner = crate::native_tables::reserve(&original, bytes as usize)
                .unwrap()
                .unwrap();
            let allocation = vec![0u8; bytes as usize];
            assert_eq!(allocation.capacity(), bytes as usize);
            owner.allocated();
            *owned_padding.lock().unwrap() = Some(Padding {
                _bytes: allocation,
                _owner: owner,
            });
            owned_consumed.store(original.host_memory_bytes(), Ordering::SeqCst);
            owned_requested.store(request, Ordering::SeqCst);
        });
        let error = linker.instantiate(&mut store, &component).unwrap_err();
        denial(
            &error,
            MIB,
            consumed.load(Ordering::SeqCst),
            requested.load(Ordering::SeqCst),
        );
        let actual = requests(&observed);
        assert_eq!(actual.len() - before, refused + 1);
        assert_eq!(actual[before], 2 * size_of::<ResourceType>());
        assert_eq!(
            consumed.load(Ordering::SeqCst) + requested.load(Ordering::SeqCst),
            MIB + 1
        );
        assert!(budget.host_memory_bytes() > retained);
        drop(error);
        drop(padding.lock().unwrap().take());
        assert_eq!(budget.host_memory_bytes(), retained);
        // A new call now legitimately prepays its channel/closures/task. Only
        // actual padding retirement restores that headroom; no larger grant.
        // The SAME preexisting function/instance must remain usable afterward.
        assert_eq!(call.call(&mut store, ()).unwrap(), (42,));
        let fresh = linker.instantiate(&mut store, &component).unwrap();
        assert_eq!(answer(fresh, &mut store), 42);
        assert_eq!(call.call(&mut store, ()).unwrap(), (42,));
        drop(store);
        assert_eq!(observed.factory_drops.load(Ordering::SeqCst), 1);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
    }
}

#[test]
fn actual_resource_types_independent_stores_cannot_refund_live_foreign_metadata() {
    let engine = Engine::default();
    let component = Component::new(&engine, COMPONENT).unwrap();
    let linker = linker(&engine);
    let first_budget = budget(MIB);
    let first_observed = Arc::new(Observations::default());
    let mut first = store(&engine, &first_budget, &first_observed).unwrap();
    let first_instance = linker.instantiate(&mut first, &component).unwrap();
    let first_pre = first_instance.instance_pre(&first);
    let second_budget = budget(MIB);
    let second_observed = Arc::new(Observations::default());
    let mut second = store(&engine, &second_budget, &second_observed).unwrap();
    let second_instance = linker.instantiate(&mut second, &component).unwrap();
    let second_pre = second_instance.instance_pre(&second);
    let second_function = second_instance
        .get_func(&mut second, "host-pass")
        .unwrap()
        .ty(&second);
    assert_eq!(answer(second_instance, &mut second), 42);
    drop(first);
    drop(second);
    let second_retained = second_budget.host_memory_bytes();
    assert!(first_budget.host_memory_bytes() > 0 && second_retained > 0);
    assert_eq!(first_observed.factory_drops.load(Ordering::SeqCst), 1);
    assert_eq!(second_observed.factory_drops.load(Ordering::SeqCst), 1);
    drop(first_pre);
    assert_eq!(first_budget.host_memory_bytes(), 0);
    assert_eq!(second_budget.host_memory_bytes(), second_retained);
    host_type(&second_function);
    drop(second_pre);
    assert_eq!(second_budget.host_memory_bytes(), second_retained);
    drop(second_function);
    assert_eq!(second_budget.host_memory_bytes(), 0);
    assert_eq!(first_budget.outstanding_reservations(), 0);
    assert_eq!(second_budget.outstanding_reservations(), 0);
}

#[test]
fn actual_resource_types_concurrent_metadata_clones_release_original_owner_once() {
    let engine = Engine::default();
    let component = Component::new(&engine, COMPONENT).unwrap();
    let budget = budget(MIB);
    let observed = Arc::new(Observations::default());
    let mut store = store(&engine, &budget, &observed).unwrap();
    let instance = linker(&engine).instantiate(&mut store, &component).unwrap();
    let function = instance
        .get_func(&mut store, "host-pass")
        .unwrap()
        .ty(&store);
    drop(store);
    assert_eq!(observed.factory_drops.load(Ordering::SeqCst), 1);
    assert!(budget.host_memory_bytes() > 0);
    let barrier = Arc::new(Barrier::new(8));
    let mut threads = Vec::new();
    for _ in 0..8 {
        let metadata = function.clone();
        let gate = barrier.clone();
        threads.push(std::thread::spawn(move || {
            host_type(&metadata);
            gate.wait();
            drop(metadata);
        }));
    }
    drop(function);
    for thread in threads {
        thread.join().unwrap();
    }
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
    assert_eq!(observed.factory_drops.load(Ordering::SeqCst), 1);
}

#[test]
fn actual_resource_types_zero_resource_tiny_call_keeps_original_one_mib_and_billion_fuel() {
    let mut config = Config::new();
    config.wasm_component_model(true);
    config.consume_fuel(true);
    let engine = Engine::new(&config).unwrap();
    let component = Component::new(&engine, include_bytes!("native-store-component.wasm")).unwrap();
    let budget = budget(MIB);
    assert_eq!(budget.granted().memory_bytes, MIB);
    assert_eq!(budget.granted().cpu_fuel, 1_000_000_000);
    let observed = Arc::new(Observations::default());
    let mut store = store(&engine, &budget, &observed).unwrap();
    // Store construction is still lazy: box, initial owner map, dummy instance.
    assert_eq!(requests(&observed).len(), 3);
    store.set_fuel(budget.granted().cpu_fuel).unwrap();
    let linker = Linker::new(&engine);
    let instance = linker.instantiate(&mut store, &component).unwrap();
    assert_eq!(answer(instance, &mut store), 42);
    assert!(store.get_fuel().unwrap() < budget.granted().cpu_fuel);
    let pre = instance.instance_pre(&store);
    assert_eq!(pre.instance_type().resources.unwrap().len(), 0);
    drop(store);
    assert_eq!(observed.factory_drops.load(Ordering::SeqCst), 1);
    assert!(budget.host_memory_bytes() > 0);
    drop(pre);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

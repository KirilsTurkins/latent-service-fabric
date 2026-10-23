//! Planned actual registry allocation controls; no execution claim.
use super::native_store_tests::{core_answer, requests, store, Observations, CORE, MIB, OWNER};
use super::native_table_tests::{budget, denial};
use std::sync::atomic::Ordering;
use std::sync::Arc;
use wasmtime::{Engine, Instance, Module};

#[test]
fn actual_registry_all_four_preparation_refusals_preserve_prior_modules_and_fresh_retry() {
    let engine = Engine::default();
    let modules = [
        Module::new(&engine, CORE).unwrap(),
        Module::new(&engine, include_bytes!("native-registry-next.wasm")).unwrap(),
        Module::new(&engine, include_bytes!("native-registry-third.wasm")).unwrap(),
    ];
    let baseline = budget(MIB);
    let baseline_observed = Arc::new(Observations::default());
    let mut initial = store(&engine, &baseline, &baseline_observed).unwrap();
    for (index, module) in modules[..2].iter().enumerate() {
        let instance = Instance::new(&mut initial, module, &[]).unwrap();
        assert_eq!(core_answer(instance, &mut initial), 42 + index as i32);
    }
    let retained = baseline.host_memory_bytes();
    let before_third = requests(&baseline_observed).len();
    let third = Instance::new(&mut initial, &modules[2], &[]).unwrap();
    assert_eq!(core_answer(third, &mut initial), 44);
    let all = requests(&baseline_observed);
    // Three ordered maps and one secondary buffer precede the usual
    // instance-owner map and VMContext. All four are staged before any edge.
    assert_eq!(all.len() - before_third, 6);
    let registry = all[before_third..before_third + 4].to_vec();
    drop(initial);
    assert_eq!(baseline.host_memory_bytes(), 0);

    for refused in 0..registry.len() {
        let budget = budget(MIB);
        let observed = Arc::new(Observations::default());
        let mut store = store(&engine, &budget, &observed).unwrap();
        let first = Instance::new(&mut store, &modules[0], &[]).unwrap();
        let second = Instance::new(&mut store, &modules[1], &[]).unwrap();
        assert_eq!(core_answer(first, &mut store), 42);
        assert_eq!(core_answer(second, &mut store), 43);
        assert_eq!(budget.host_memory_bytes(), retained);
        let before = requests(&observed).len();
        let earlier: u64 = registry[..refused]
            .iter()
            .map(|bytes| *bytes as u64 + OWNER)
            .sum();
        let requested = registry[refused] as u64 + OWNER;
        let padding_bytes = MIB - retained - earlier - requested + 1 - OWNER;
        let mut padding_owner = crate::native_tables::reserve(&budget, padding_bytes as usize)
            .unwrap()
            .unwrap();
        let padding = vec![0u8; padding_bytes as usize];
        assert_eq!(padding.capacity(), padding_bytes as usize);
        padding_owner.allocated();
        let charged = budget.host_memory_bytes();
        assert_eq!(charged, retained + padding_bytes + OWNER);
        let error = Instance::new(&mut store, &modules[2], &[]).unwrap_err();
        denial(&error, MIB, charged + earlier, requested);
        assert_eq!(&requests(&observed)[before..], &registry[..=refused]);
        assert_eq!(budget.host_memory_bytes(), charged);
        assert_eq!(core_answer(first, &mut store), 42);
        assert_eq!(core_answer(second, &mut store), 43);
        drop(padding);
        drop(padding_owner);
        assert_eq!(budget.host_memory_bytes(), retained);
        let third = Instance::new(&mut store, &modules[2], &[]).unwrap();
        assert_eq!(core_answer(third, &mut store), 44);
        drop(store);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
    }
}

#[test]
fn actual_registry_duplicate_module_has_no_new_registry_backing() {
    let engine = Engine::default();
    let module = Module::new(&engine, CORE).unwrap();
    let budget = budget(MIB);
    let observed = Arc::new(Observations::default());
    let mut store = store(&engine, &budget, &observed).unwrap();
    let first = Instance::new(&mut store, &module, &[]).unwrap();
    assert_eq!(core_answer(first, &mut store), 42);
    let before = requests(&observed).len();
    let second = Instance::new(&mut store, &module, &[]).unwrap();
    assert_eq!(core_answer(second, &mut store), 42);
    assert_eq!(requests(&observed).len() - before, 2);
    assert_eq!(core_answer(first, &mut store), 42);
    drop(store);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn actual_registry_foreign_engine_refusal_precedes_all_registry_admission() {
    let engine = Engine::default();
    let other = Engine::default();
    let module = Module::new(&engine, CORE).unwrap();
    let foreign = Module::new(&other, CORE).unwrap();
    let budget = budget(MIB);
    let observed = Arc::new(Observations::default());
    let mut store = store(&engine, &budget, &observed).unwrap();
    let instance = Instance::new(&mut store, &module, &[]).unwrap();
    assert_eq!(core_answer(instance, &mut store), 42);
    let before = requests(&observed);
    let retained = budget.host_memory_bytes();
    let peak = budget
        .snapshot_at(std::time::Instant::now())
        .peak_memory_bytes;
    let error = Instance::new(&mut store, &foreign, &[]).unwrap_err();
    assert!(error.to_string().contains("cross-`Engine`"));
    assert_eq!(requests(&observed), before);
    assert_eq!(budget.host_memory_bytes(), retained);
    assert_eq!(
        budget
            .snapshot_at(std::time::Instant::now())
            .peak_memory_bytes,
        peak
    );
    assert_eq!(core_answer(instance, &mut store), 42);
    drop(store);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn actual_registry_component_sparse_module_indices_preserve_both_original_results() {
    let engine = Engine::default();
    let component = wasmtime::component::Component::new(
        &engine,
        include_bytes!("native-registry-component.wasm"),
    )
    .unwrap();
    let budget = budget(MIB);
    let observed = Arc::new(Observations::default());
    let mut store = store(&engine, &budget, &observed).unwrap();
    let linker = wasmtime::component::Linker::new(&engine);
    let instance = linker.instantiate(&mut store, &component).unwrap();
    let third = instance
        .get_typed_func::<(), (u32,)>(&mut store, "third")
        .unwrap();
    let first = instance
        .get_typed_func::<(), (u32,)>(&mut store, "first")
        .unwrap();
    assert_eq!(third.call(&mut store, ()).unwrap(), (43,));
    assert_eq!(first.call(&mut store, ()).unwrap(), (42,));
    for (export, function_name) in [
        ("third-fault", "third_fault"),
        ("first-fault", "first_fault"),
    ] {
        // Every real component trap poisons that Store. Each sparse module
        // gets a fresh instance so both checks reach their own Wasm fault.
        let fault_budget = super::native_table_tests::budget(MIB);
        let fault_observed = Arc::new(Observations::default());
        let mut fault_store =
            super::native_store_tests::store(&engine, &fault_budget, &fault_observed).unwrap();
        let fault_instance = linker.instantiate(&mut fault_store, &component).unwrap();
        let fault = fault_instance
            .get_typed_func::<(), ()>(&mut fault_store, export)
            .unwrap();
        let error = fault.call(&mut fault_store, ()).unwrap_err();
        assert_eq!(
            error.downcast_ref::<wasmtime::Trap>(),
            Some(&wasmtime::Trap::UnreachableCodeReached)
        );
        let trace = error.downcast_ref::<wasmtime::WasmBacktrace>().unwrap();
        assert!(trace
            .frames()
            .iter()
            .any(|frame| frame.func_name() == Some(function_name) && frame.func_index() == 1));
        drop(error);
        let fault_retained = fault_budget.host_memory_bytes();
        drop(fault_store);
        assert_eq!(
            fault_observed.data_charge.load(Ordering::SeqCst),
            fault_retained
        );
        assert_eq!(fault_observed.factory_drops.load(Ordering::SeqCst), 1);
        assert_eq!(fault_budget.host_memory_bytes(), 0);
        assert_eq!(fault_budget.outstanding_reservations(), 0);
    }
    let retained = budget.host_memory_bytes();
    drop(store);
    assert_eq!(observed.data_charge.load(Ordering::SeqCst), retained);
    assert_eq!(observed.factory_drops.load(Ordering::SeqCst), 1);
    assert_eq!(budget.host_memory_bytes(), 0);
}

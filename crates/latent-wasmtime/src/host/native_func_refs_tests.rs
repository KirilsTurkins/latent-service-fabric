//! Planned actual engine controls for selected FuncRefs containers only.
//! HostFunc state/context and shared preparation backing are outside the slice.
use super::native_store_tests::{requests, store, Data, Observations, MIB, OWNER};
use super::native_table_tests::{budget, denial};
use latent_core::ActivationBudget;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::sync::Arc;
use wasmtime::{Config, Engine, Func, Instance, Linker, Module, Store};

const CALL: &[u8] = include_bytes!("native-funcrefs-call.wasm");

fn call(instance: Instance, store: &mut Store<Data>, input: i32) -> i32 {
    instance
        .get_typed_func::<i32, i32>(&mut *store, "call")
        .unwrap()
        .call(store, input)
        .unwrap()
}

struct DropProbe {
    budget: ActivationBudget,
    drops: Arc<AtomicUsize>,
    charge: Arc<AtomicU64>,
}
impl Drop for DropProbe {
    fn drop(&mut self) {
        self.charge
            .store(self.budget.host_memory_bytes(), Ordering::SeqCst);
        self.drops.fetch_add(1, Ordering::SeqCst);
    }
}

#[test]
fn actual_funcrefs_growth_preserves_old_guest_calls_at_original_memory_and_fuel_limits() {
    let mut config = Config::new();
    config.consume_fuel(true);
    let engine = Engine::new(&config).unwrap();
    let module = Module::new(&engine, CALL).unwrap();
    let budget = budget(64 * MIB);
    let observed = Arc::new(Observations::default());
    let mut store = store(&engine, &budget, &observed).unwrap();
    store.set_fuel(1_000_000_000).unwrap();
    let initial = budget.host_memory_bytes();
    let before = requests(&observed).len();
    let first = Func::try_wrap(&mut store, |value: i32| value + 1).unwrap();
    // Initially no module trampoline has been registered in this Store:
    // arena directory, hole directory, root directory and stable VMFuncRef.
    assert_eq!(requests(&observed).len() - before, 4);
    assert!(budget.host_memory_bytes() > initial);
    let mut functions = vec![first];
    for add in 2..=9 {
        functions.push(Func::try_wrap(&mut store, move |value: i32| value + add).unwrap());
    }
    let retained = budget.host_memory_bytes();
    assert!(
        budget
            .snapshot_at(std::time::Instant::now())
            .peak_memory_bytes
            > retained
    );
    let old = Instance::new(&mut store, &module, &[first.into()]).unwrap();
    let last = Instance::new(&mut store, &module, &[functions[8].into()]).unwrap();
    assert_eq!(call(old, &mut store, 41), 42);
    assert_eq!(call(last, &mut store, 41), 50);
    assert_eq!(call(old, &mut store, 41), 42);
    assert!(store.get_fuel().unwrap() < 1_000_000_000);
    assert!(budget.host_memory_bytes() >= retained);
    drop(store);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

#[test]
fn actual_funcrefs_all_four_staged_refusals_preserve_roots_fill_and_original_error() {
    let engine = Engine::default();
    let module = Module::new(&engine, CALL).unwrap();
    let baseline = budget(MIB);
    let observed = Arc::new(Observations::default());
    let mut initial = store(&engine, &baseline, &observed).unwrap();
    Func::try_wrap(&mut initial, |value: i32| value + 1).unwrap();
    let retained = baseline.host_memory_bytes();
    let before = requests(&observed).len();
    Func::try_wrap(&mut initial, |value: i32| value + 2).unwrap();
    let growth = requests(&observed)[before..].to_vec();
    assert_eq!(growth.len(), 4);
    drop(initial);
    assert_eq!(baseline.host_memory_bytes(), 0);

    for refused in 0..growth.len() {
        let budget = budget(MIB);
        let observed = Arc::new(Observations::default());
        let mut store = store(&engine, &budget, &observed).unwrap();
        let first = Func::try_wrap(&mut store, |value: i32| value + 1).unwrap();
        assert_eq!(budget.host_memory_bytes(), retained);
        let before = requests(&observed).len();
        let earlier: u64 = growth[..refused].iter().map(|n| *n as u64 + OWNER).sum();
        let requested = growth[refused] as u64 + OWNER;
        let padding_bytes = MIB - retained - earlier - requested + 1 - OWNER;
        let mut padding_owner = crate::native_tables::reserve(&budget, padding_bytes as usize)
            .unwrap()
            .unwrap();
        let padding = vec![0u8; padding_bytes as usize];
        assert_eq!(padding.capacity(), padding_bytes as usize);
        padding_owner.allocated();
        let charged = budget.host_memory_bytes();
        let drops = Arc::new(AtomicUsize::new(0));
        let charge = Arc::new(AtomicU64::new(0));
        let probe = DropProbe {
            budget: budget.clone(),
            drops: drops.clone(),
            charge,
        };
        let error = Func::try_wrap(&mut store, move |value: i32| {
            let _ = &probe;
            value + 2
        })
        .err()
        .unwrap();
        denial(&error, MIB, charged + earlier, requested);
        assert_eq!(&requests(&observed)[before..], &growth[..=refused]);
        assert_eq!(budget.host_memory_bytes(), charged);
        assert_eq!(drops.load(Ordering::SeqCst), 1);
        drop(padding);
        drop(padding_owner);
        assert_eq!(budget.host_memory_bytes(), retained);
        // Registration fills only published live holes. A failed candidate's
        // destroyed vmctx must never have been installed in this directory.
        let old = Instance::new(&mut store, &module, &[first.into()]).unwrap();
        assert_eq!(call(old, &mut store, 41), 42);
        let fresh = Func::try_wrap(&mut store, |value: i32| value + 2).unwrap();
        assert_eq!(
            fresh
                .typed::<i32, i32>(&store)
                .unwrap()
                .call(&mut store, 41)
                .unwrap(),
            43
        );
        assert_eq!(call(old, &mut store, 41), 42);
        drop(store);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
    }
}

#[test]
fn actual_funcrefs_shared_linker_root_survives_linker_drop_until_store_destruction() {
    let engine = Engine::default();
    let module = Module::new(&engine, CALL).unwrap();
    let budget = budget(MIB);
    let observed = Arc::new(Observations::default());
    let mut store = store(&engine, &budget, &observed).unwrap();
    let drops = Arc::new(AtomicUsize::new(0));
    let charge = Arc::new(AtomicU64::new(0));
    let probe = DropProbe {
        budget: budget.clone(),
        drops: drops.clone(),
        charge: charge.clone(),
    };
    let mut linker = Linker::<Data>::new(&engine);
    linker
        .func_wrap("env", "inc", move |value: i32| {
            let _ = &probe;
            value + 1
        })
        .unwrap();
    let before = requests(&observed).len();
    let function = linker
        .get(&mut store, "env", "inc")
        .unwrap()
        .into_func()
        .unwrap();
    assert_eq!(requests(&observed).len() - before, 4);
    drop(linker);
    assert_eq!(drops.load(Ordering::SeqCst), 0);
    let instance = Instance::new(&mut store, &module, &[function.into()]).unwrap();
    assert_eq!(call(instance, &mut store, 41), 42);
    drop(store);
    assert_eq!(drops.load(Ordering::SeqCst), 1);
    assert!(charge.load(Ordering::SeqCst) > 0);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

#[test]
fn actual_funcrefs_instance_pre_pair_refusal_preserves_prior_instance_and_retry() {
    let engine = Engine::default();
    let module = Module::new(&engine, CALL).unwrap();
    let budget = budget(MIB);
    let observed = Arc::new(Observations::default());
    let mut store = store(&engine, &budget, &observed).unwrap();
    let drops = Arc::new(AtomicUsize::new(0));
    let charge = Arc::new(AtomicU64::new(0));
    let probe = DropProbe {
        budget: budget.clone(),
        drops: drops.clone(),
        charge: charge.clone(),
    };
    let mut linker = Linker::<Data>::new(&engine);
    linker
        .func_wrap("env", "inc", move |value: i32| {
            let _ = &probe;
            value + 1
        })
        .unwrap();
    let pre = linker.instantiate_pre(&module).unwrap();
    let first = pre.instantiate(&mut store).unwrap();
    assert_eq!(call(first, &mut store, 41), 42);
    let retained = budget.host_memory_bytes();
    let before = requests(&observed).len();
    let second = pre.instantiate(&mut store).unwrap();
    assert_eq!(call(second, &mut store, 41), 42);
    // Same module: registry dedup; first request grows the two-slot root
    // directory to four slots, before instance-map/VMContext allocation.
    let growth = requests(&observed)[before];
    assert!(growth > 0);
    drop(store);
    assert_eq!(budget.host_memory_bytes(), 0);
    // The prepared shared closure itself is not an activation allocation.
    assert_eq!(drops.load(Ordering::SeqCst), 0);

    let observed = Arc::new(Observations::default());
    let mut store = super::native_store_tests::store(&engine, &budget, &observed).unwrap();
    let first = pre.instantiate(&mut store).unwrap();
    assert_eq!(call(first, &mut store, 41), 42);
    assert_eq!(budget.host_memory_bytes(), retained);
    let before = requests(&observed).len();
    let requested = growth as u64 + OWNER;
    let padding_bytes = MIB - retained - requested + 1 - OWNER;
    let mut padding_owner = crate::native_tables::reserve(&budget, padding_bytes as usize)
        .unwrap()
        .unwrap();
    let padding = vec![0u8; padding_bytes as usize];
    assert_eq!(padding.capacity(), padding_bytes as usize);
    padding_owner.allocated();
    let charged = budget.host_memory_bytes();
    let error = pre.instantiate(&mut store).err().unwrap();
    denial(&error, MIB, charged, requested);
    assert_eq!(&requests(&observed)[before..], &[growth]);
    assert_eq!(budget.host_memory_bytes(), charged);
    drop(padding);
    drop(padding_owner);
    assert_eq!(call(first, &mut store, 41), 42);
    let fresh = pre.instantiate(&mut store).unwrap();
    assert_eq!(call(fresh, &mut store, 41), 42);
    drop(pre);
    drop(linker);
    assert_eq!(drops.load(Ordering::SeqCst), 0);
    drop(store);
    assert_eq!(drops.load(Ordering::SeqCst), 1);
    assert!(charge.load(Ordering::SeqCst) > 0);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

#[test]
fn actual_funcrefs_default_lookup_preserves_original_admission_error() {
    let engine = Engine::default();
    let budget = budget(MIB);
    let observed = Arc::new(Observations::default());
    let mut store = store(&engine, &budget, &observed).unwrap();
    Func::try_wrap(&mut store, |value: i32| value + 1).unwrap();
    let retained = budget.host_memory_bytes();
    let before = requests(&observed).len();
    let mut linker = Linker::<Data>::new(&engine);
    linker.func_wrap("env", "", |value: i32| value + 2).unwrap();
    linker.func_wrap("env", "_start", || {}).unwrap();
    linker.get_default(&mut store, "env").unwrap();
    let growth = requests(&observed)[before];
    drop(store);
    assert_eq!(budget.host_memory_bytes(), 0);

    let observed = Arc::new(Observations::default());
    let mut store = super::native_store_tests::store(&engine, &budget, &observed).unwrap();
    let first = Func::try_wrap(&mut store, |value: i32| value + 1).unwrap();
    assert_eq!(budget.host_memory_bytes(), retained);
    let requested = growth as u64 + OWNER;
    let padding_bytes = MIB - retained - requested + 1 - OWNER;
    let mut padding_owner = crate::native_tables::reserve(&budget, padding_bytes as usize)
        .unwrap()
        .unwrap();
    let padding = vec![0u8; padding_bytes as usize];
    assert_eq!(padding.capacity(), padding_bytes as usize);
    padding_owner.allocated();
    let charged = budget.host_memory_bytes();
    let before = requests(&observed).len();
    let error = linker.get_default(&mut store, "env").err().unwrap();
    denial(&error, MIB, charged, requested);
    assert_eq!(&requests(&observed)[before..], &[growth]);
    assert_eq!(budget.host_memory_bytes(), charged);
    drop(padding);
    drop(padding_owner);
    assert_eq!(
        first
            .typed::<i32, i32>(&store)
            .unwrap()
            .call(&mut store, 41)
            .unwrap(),
        42
    );
    let fresh = linker.get_default(&mut store, "env").unwrap();
    assert_eq!(
        fresh
            .typed::<i32, i32>(&store)
            .unwrap()
            .call(&mut store, 41)
            .unwrap(),
        43
    );
    drop(store);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

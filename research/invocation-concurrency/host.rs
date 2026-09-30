//! Opt-in actual-component experiment. This is not a production LSF provider.
mod memory;

use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use tokio::sync::watch;
use wasmtime::component::{Component, Linker, Val};
use wasmtime::{AsContextMut, Config, Engine, Store, Trap};

const MAX_TASKS: usize = 8;
const FUEL: u64 = 50_000_000;
const STACK_BYTES: usize = 256 * 1024;

#[derive(Clone, Copy, Default)]
struct Signals {
    released: u32,
    cancelled: bool,
}

#[derive(Default)]
struct Facts {
    live: usize,
    peak: usize,
    started: usize,
    cancelled: u32,
    frames: [u32; MAX_TASKS],
    polls: [u32; MAX_TASKS],
    drops: [u32; MAX_TASKS],
    store_dropped: bool,
    pending_witnesses: usize,
    cancellation_witness: bool,
    pending_memory_bytes: usize,
}

struct Shared {
    facts: Mutex<Facts>,
    changed: watch::Sender<()>,
    signals: watch::Sender<Signals>,
}
impl Shared {
    fn new() -> Arc<Self> {
        Arc::new(Self {
            facts: Mutex::new(Facts::default()),
            changed: watch::channel(()).0,
            signals: watch::channel(Signals::default()).0,
        })
    }
    fn update(&self, action: impl FnOnce(&mut Facts)) {
        action(&mut self.facts.lock().unwrap());
        self.changed.send_replace(());
    }
    async fn until(&self, predicate: impl Fn(&Facts) -> bool) {
        let mut changes = self.changed.subscribe();
        loop {
            if predicate(&self.facts.lock().unwrap()) {
                return;
            }
            changes.changed().await.unwrap();
        }
    }
}

struct State {
    shared: Arc<Shared>,
    memory: memory::Memory,
    // The guest supplies neither identity nor authority.
    identity: u64,
    allow: bool,
    fail_first: bool,
}
impl Drop for State {
    fn drop(&mut self) {
        self.shared.update(|facts| facts.store_dropped = true);
    }
}

struct Operation(Arc<Shared>);
impl Drop for Operation {
    fn drop(&mut self) {
        self.0.update(|facts| facts.live -= 1);
    }
}

fn linker(engine: &Engine) -> wasmtime::Result<Linker<State>> {
    let mut linker: Linker<State> = Linker::new(engine);
    let mut host = linker.instance("research:concurrency/host@0.1.0")?;
    host.func_wrap("event", |store, (kind, task): (u32, u32)| {
        let state: &State = store.data();
        assert_eq!(state.identity, 695);
        let id = task as usize;
        if id >= MAX_TASKS {
            return Err(wasmtime::Error::msg("invalid research task id"));
        }
        state.shared.update(|facts| match kind {
            0 => facts.frames[id] += 1,
            1 => facts.polls[id] += 1,
            2 => facts.drops[id] += 1,
            3 => (), // The inline-start counterexample entered its worker.
            _ => panic!("invalid research event"),
        });
        Ok(())
    })?;
    host.func_wrap_concurrent("wait", |access, (task,): (u32,)| {
        Box::pin(async move {
            let (shared, allow, fail_first) = access.with(|mut access| {
                let store = access.as_context_mut();
                assert_eq!(store.data().identity, 695);
                let state = store.data();
                state.shared.update(|facts| facts.pending_memory_bytes = state.memory.current);
                (state.shared.clone(), state.allow, state.fail_first)
            });
            // Denial happens before acquiring a provider-operation owner.
            if !allow {
                return Ok((Err::<u32, u32>(403),));
            }
            if task as usize >= MAX_TASKS {
                return Err(wasmtime::Error::msg("invalid research task id"));
            }
            let mut signals = shared.signals.subscribe();
            shared.update(|facts| {
                facts.live += 1;
                facts.started += 1;
                facts.peak = facts.peak.max(facts.live);
                assert!(facts.live <= MAX_TASKS);
            });
            let operation = Operation(shared.clone());
            if fail_first && task == 0 {
                drop(operation);
                return Ok((Err(422),));
            }
            let bit = 1 << task;
            loop {
                let signal = *signals.borrow_and_update();
                if signal.cancelled {
                    shared.update(|facts| facts.cancelled |= bit);
                }
                if signal.released & bit != 0 {
                    // A cancellation request alone never retired this owner.
                    drop(operation);
                    return Ok((if signal.cancelled { Err(499) } else { Ok(task + 1) },));
                }
                signals.changed().await.map_err(|_| {
                    wasmtime::Error::msg("research controller disappeared")
                })?;
            }
        })
    })?;
    Ok(linker)
}

#[derive(Clone, Copy)]
enum Gate { None, Sequential, Fanout, Cancel, Deadline, PartialError }

async fn control(engine: &Engine, shared: Arc<Shared>, gate: Gate, count: u32) {
    let mask = (1 << count) - 1;
    match gate {
        Gate::None => (),
        Gate::Sequential => {
            for id in 0..count {
                shared.until(|facts| facts.live == 1 && facts.started == (id + 1) as usize).await;
                shared.update(|facts| {
                    assert!(!facts.store_dropped);
                    facts.pending_witnesses += 1;
                });
                shared.signals.send_modify(|signal| signal.released |= 1 << id);
            }
        }
        Gate::Fanout | Gate::Cancel | Gate::Deadline | Gate::PartialError => {
            let expected_live = count as usize - usize::from(matches!(gate, Gate::PartialError));
            shared.until(|facts| facts.started == count as usize && facts.live == expected_live).await;
            shared.update(|facts| {
                assert!(!facts.store_dropped);
                facts.pending_witnesses += 1;
            });
            if matches!(gate, Gate::Cancel | Gate::Deadline) {
                shared.signals.send_modify(|signal| signal.cancelled = true);
                shared.until(|facts| facts.cancelled == mask).await;
                shared.update(|facts| {
                    // All actual host futures accepted cancellation; each still
                    // owns its operation until the separate retirement gate.
                    assert_eq!(facts.live, count as usize);
                    assert!(!facts.store_dropped);
                    facts.cancellation_witness = true;
                });
            }
            shared.signals.send_modify(|signal| signal.released = mask);
            if matches!(gate, Gate::Deadline) {
                // Controlled root epoch expiry, not a sleep-based timing guess.
                engine.increment_epoch();
            }
        }
    }
}

struct Case {
    name: &'static str,
    mode: u32,
    tasks: u32,
    allow: bool,
    gate: Gate,
    expected: Option<u64>,
}

async fn run(engine: &Engine, component: &Component, case: Case) -> wasmtime::Result<Value> {
    let shared = Shared::new();
    let mut store = Store::new(engine, State {
        shared: shared.clone(), memory: memory::Memory::new(), identity: 695, allow: case.allow,
        fail_first: matches!(case.gate, Gate::PartialError),
    });
    store.limiter(|state| &mut state.memory);
    store.set_fuel(FUEL)?;
    store.set_epoch_deadline(1);
    store.epoch_deadline_trap();
    store.fuel_async_yield_interval(Some(10_000))?;
    let linker = linker(engine)?;
    let instance = linker.instantiate_async(&mut store, component).await?;
    let interface = instance.get_export_index(&mut store, None, "research:concurrency/api@0.1.0")
        .ok_or_else(|| wasmtime::Error::msg("missing research interface"))?;
    let index = instance.get_export_index(&mut store, Some(&interface), "run")
        .ok_or_else(|| wasmtime::Error::msg("missing research function"))?;
    let function = instance.get_func(&mut store, index)
        .ok_or_else(|| wasmtime::Error::msg("missing research export"))?;
    let input = [Val::U32(case.mode), Val::U32(case.tasks)];
    let mut output = [Val::U64(0)];
    let started = Instant::now();
    // A watchdog bounds a broken experiment. It is not a cleanup witness.
    let result = tokio::time::timeout(Duration::from_secs(10), async {
        let (result, ()) = tokio::join!(
            function.call_async(&mut store, &input, &mut output),
            control(engine, shared.clone(), case.gate, case.tasks)
        );
        result
    }).await.map_err(|_| wasmtime::Error::msg("research watchdog expired"))?;
    let elapsed = started.elapsed().as_nanos();
    let fuel = FUEL - store.get_fuel()?;
    let peak_memory = store.data().memory.peak;
    let outcome = if let Some(expected) = case.expected {
        result?;
        match output[0] {
            Val::U64(actual) => assert_eq!(actual, expected, "{}", case.name),
            _ => panic!("wrong research result type"),
        }
        "returned"
    } else {
        let error = result.expect_err("unsupported pattern unexpectedly succeeded");
        let trap = error.downcast_ref::<Trap>().expect("expected terminal Wasm trap");
        if case.mode == 3 {
            assert_eq!(*trap, Trap::OutOfFuel);
            "out-of-fuel"
        } else if matches!(case.gate, Gate::Deadline) {
            assert_eq!(*trap, Trap::Interrupt);
            "epoch-deadline-trap"
        } else {
            assert_eq!(*trap, Trap::UnreachableCodeReached);
            "unsupported-thread-trap"
        }
    };
    assert!(peak_memory > 0 && peak_memory <= memory::MEMORY_LIMIT);
    let before_drop = shared.facts.lock().unwrap().live;
    assert_eq!(before_drop, 0, "host operation still owned after call/drain");
    assert!(!shared.facts.lock().unwrap().store_dropped);
    let cleanup = Instant::now();
    drop(store);
    let cleanup_ns = cleanup.elapsed().as_nanos();
    let facts = shared.facts.lock().unwrap();
    assert!(facts.store_dropped);
    assert_eq!(facts.live, 0);
    if case.expected.is_some() {
        assert_eq!(facts.frames, facts.drops, "guest frames not drained exactly once");
    }
    if matches!(case.gate, Gate::Fanout | Gate::Cancel | Gate::Deadline) {
        assert_eq!(facts.peak, case.tasks as usize);
    }
    if matches!(case.gate, Gate::Sequential) { assert_eq!(facts.peak, 1); }
    if !case.allow || case.tasks > MAX_TASKS as u32 { assert_eq!(facts.started, 0); }
    Ok(json!({
        "name": case.name, "outcome": outcome, "expected": case.expected,
        "callNanos": elapsed, "storeDropNanos": cleanup_ns, "fuelUsed": fuel,
        "linearMemoryPeakBytes": peak_memory, "hostOperationsStarted": facts.started,
        "peakHostOperations": facts.peak, "hostOperationsAfterStoreDrop": facts.live,
        "pendingOwnershipWitnesses": facts.pending_witnesses,
        "pendingLinearMemoryBytes": facts.pending_memory_bytes,
        "cancelAcceptedBeforeRetirementWitness": facts.cancellation_witness,
        "storeDataDropped": facts.store_dropped,
        "framesCreated": facts.frames, "framePolls": facts.polls, "framesDropped": facts.drops,
    }))
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> wasmtime::Result<()> {
    let path = std::env::args().nth(1).ok_or_else(|| wasmtime::Error::msg("component path required"))?;
    let mut config = Config::new();
    config.wasm_component_model(true).wasm_component_model_async(true).consume_fuel(true);
    config.max_wasm_stack(STACK_BYTES).epoch_interruption(true);
    let engine = Engine::new(&config)?;
    let compiled = Instant::now();
    let component = Component::from_file(&engine, path)?;
    let compile_ns = compiled.elapsed().as_nanos();
    let cases = [
        Case { name: "sequential-host-waits", mode: 0, tasks: 8, allow: true, gate: Gate::Sequential, expected: Some(36) },
        Case { name: "cooperative-host-fanout", mode: 1, tasks: 8, allow: true, gate: Gate::Fanout, expected: Some(36) },
        Case { name: "cancel-then-drain", mode: 1, tasks: 8, allow: true, gate: Gate::Cancel, expected: Some(255_u64 << 32) },
        Case { name: "denied-before-dispatch", mode: 1, tasks: 2, allow: false, gate: Gate::None, expected: Some(3_u64 << 32) },
        Case { name: "task-limit-before-dispatch", mode: 1, tasks: 9, allow: true, gate: Gate::None, expected: Some(900) },
        Case { name: "empty-scope", mode: 1, tasks: 0, allow: true, gate: Gate::None, expected: Some(0) },
        Case { name: "cooperative-rendezvous", mode: 4, tasks: 2, allow: true, gate: Gate::None, expected: Some(3) },
        Case { name: "std-thread-spawn", mode: 2, tasks: 1, allow: true, gate: Gate::None, expected: None },
        Case { name: "inline-start-deadlock", mode: 3, tasks: 1, allow: true, gate: Gate::None, expected: None },
        Case { name: "epoch-deadline-drain", mode: 1, tasks: 8, allow: true, gate: Gate::Deadline, expected: None },
        Case { name: "partial-error-still-drains", mode: 1, tasks: 8, allow: true, gate: Gate::PartialError, expected: Some((1_u64 << 32) + 35) },
        Case { name: "fresh-store-after-traps", mode: 1, tasks: 2, allow: true, gate: Gate::Fanout, expected: Some(3) },
    ];
    let mut measurements = Vec::new();
    for case in cases { measurements.push(run(&engine, &component, case).await?); }
    // Discard one warmup pair, then retain all seven paired samples. These are
    // bounded descriptive measurements, not a statistically qualified speedup.
    let mut cpu = Vec::new();
    for repetition in 0..8 {
        let mut pair = Vec::new();
        for mode in [5, 6] {
            pair.push(run(&engine, &component, Case {
                name: if mode == 5 { "cpu-sequential" } else { "cpu-cooperative" },
                mode, tasks: 8, allow: true, gate: Gate::None, expected: Some(36 * 256),
            }).await?);
        }
        if repetition > 0 { cpu.push(pair); }
    }
    println!("{}", json!({
        "schemaVersion": "latent.research.invocation-concurrency.v1", "status": "passed",
        "productionQualified": false, "compileNanos": compile_ns,
        "maximumTasks": MAX_TASKS, "maximumLinearMemoryBytes": memory::MEMORY_LIMIT,
        "maximumWasmStackBytes": STACK_BYTES, "sharedFuelPerStore": FUEL,
        "hostOperationStructBytes": std::mem::size_of::<Operation>(),
        "unmeasured": ["native allocator peak", "RSS attribution", "production cell reservations", "signed-node qualification"],
        "measurements": measurements, "cpuPairedSamples": cpu,
    }));
    Ok(())
}

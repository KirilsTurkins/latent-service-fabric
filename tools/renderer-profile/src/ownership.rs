use super::{message, FUEL, HOSTCALL};
use std::{
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc,
    },
    thread::JoinHandle,
    time::Duration,
};
use wasmtime::{Engine, Store, StoreLimits, StoreLimitsBuilder};
pub(super) struct State {
    limits: StoreLimits,
    live: Arc<AtomicUsize>,
    bound: usize,
    pub(super) peak_memory: usize,
    pub(super) memory_denials: usize,
}
impl wasmtime::ResourceLimiter for State {
    fn memory_growing(
        &mut self,
        current: usize,
        desired: usize,
        maximum: Option<usize>,
    ) -> wasmtime::Result<bool> {
        if desired > self.bound {
            self.memory_denials += 1;
        }
        let allowed = self.limits.memory_growing(current, desired, maximum)?;
        if allowed && maximum.is_none_or(|limit| desired <= limit) {
            self.peak_memory = self.peak_memory.max(desired);
        }
        Ok(allowed)
    }
    fn table_growing(
        &mut self,
        current: usize,
        desired: usize,
        maximum: Option<usize>,
    ) -> wasmtime::Result<bool> {
        self.limits.table_growing(current, desired, maximum)
    }
    fn instances(&self) -> usize {
        self.limits.instances()
    }
    fn tables(&self) -> usize {
        self.limits.tables()
    }
    fn memories(&self) -> usize {
        self.limits.memories()
    }
}
impl Drop for State {
    fn drop(&mut self) {
        self.live.fetch_sub(1, Ordering::AcqRel);
    }
}
pub(super) struct Ticker {
    stop: Arc<AtomicBool>,
    worker: Option<JoinHandle<()>>,
}
impl Ticker {
    pub(super) fn start(engine: Engine) -> Self {
        let stop = Arc::new(AtomicBool::new(false));
        let signal = stop.clone();
        let worker = std::thread::spawn(move || {
            while !signal.load(Ordering::Acquire) {
                std::thread::sleep(Duration::from_millis(1));
                engine.increment_epoch();
            }
        });
        Self {
            stop,
            worker: Some(worker),
        }
    }
}
impl Drop for Ticker {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Release);
        if let Some(worker) = self.worker.take() {
            worker.join().expect("owned epoch ticker exited");
        }
    }
}
pub(super) fn state(
    engine: &Engine,
    live: &Arc<AtomicUsize>,
    memory: usize,
) -> Result<Store<State>, String> {
    live.fetch_add(1, Ordering::AcqRel);
    let limits = StoreLimitsBuilder::new()
        .memory_size(memory)
        .trap_on_grow_failure(true)
        .memories(1)
        .instances(32)
        .tables(4)
        .table_elements(131_072)
        .build();
    let mut store = Store::new(
        engine,
        State {
            limits,
            live: live.clone(),
            bound: memory,
            peak_memory: 0,
            memory_denials: 0,
        },
    );
    store.limiter(|s| s);
    store.set_fuel(FUEL).map_err(message)?;
    store.set_hostcall_fuel(HOSTCALL);
    store.set_epoch_deadline(5_000);
    Ok(store)
}

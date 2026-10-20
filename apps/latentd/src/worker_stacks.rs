//! Fixed node-owned Tokio stacks; separate from activation-owned Wasmtime fibers.
use std::{
    io,
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
};
use tokio::runtime::{Builder, Runtime};

pub(crate) const THREAD_STACK_BYTES: usize = 2 * 1024 * 1024;
// Conservative separate guard/alignment capacity, not an observed RSS counter.
pub(crate) const THREAD_GUARD_ALLOWANCE: usize = 64 * 1024;
pub(crate) const THREAD_MAPPING_ALLOWANCE: usize = THREAD_STACK_BYTES + THREAD_GUARD_ALLOWANCE;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct WorkerStacks {
    workers: usize,
    blocking: usize,
    maximum_threads: usize,
    maximum_mapping_bytes: usize,
}
impl WorkerStacks {
    fn checked(workers: usize, blocking: usize) -> Option<Self> {
        let maximum_threads = workers.checked_add(blocking)?;
        Some(Self {
            workers,
            blocking,
            maximum_threads,
            maximum_mapping_bytes: maximum_threads.checked_mul(THREAD_MAPPING_ALLOWANCE)?,
        })
    }
    pub(crate) const fn maximum_threads(self) -> usize {
        self.maximum_threads
    }
    pub(crate) const fn maximum_mapping_bytes(self) -> usize {
        self.maximum_mapping_bytes
    }
    pub(crate) fn build(
        self,
        name: &'static str,
        counter: &Arc<AtomicUsize>,
    ) -> io::Result<Runtime> {
        let started = Arc::clone(counter);
        let stopped = Arc::clone(counter);
        Builder::new_multi_thread()
            .worker_threads(self.workers)
            .max_blocking_threads(self.blocking)
            .thread_stack_size(THREAD_STACK_BYTES)
            .thread_name(name)
            .on_thread_start(move || {
                started.fetch_add(1, Ordering::SeqCst);
            })
            .on_thread_stop(move || {
                stopped.fetch_sub(1, Ordering::SeqCst);
            })
            .enable_all()
            .build()
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct NodeWorkerStacks {
    pub(crate) invocation: WorkerStacks,
    pub(crate) control: WorkerStacks,
}
impl NodeWorkerStacks {
    pub(crate) fn checked(runtime: usize, control: usize, control_blocking: usize) -> Option<Self> {
        if !(1..=32).contains(&runtime)
            || !(1..=8).contains(&control)
            || !(1..=2).contains(&control_blocking)
        {
            return None;
        }
        Some(Self {
            invocation: WorkerStacks::checked(runtime, 1)?,
            control: WorkerStacks::checked(control, control_blocking)?,
        })
    }
}

#[cfg(test)]
mod tests;

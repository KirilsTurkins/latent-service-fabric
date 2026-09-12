//! Fixed owned compiler threads, bounded coalescing and affine ready pins.

mod acquire;
mod metrics;
mod ready;
mod shutdown;
mod state;
#[cfg(test)]
mod tests;
mod wait;
mod worker;

use std::sync::{Arc, Condvar, Mutex};
use std::thread::JoinHandle;

use latent_artifacts::ArtifactPreparationIdentity;
use latent_core::{PlatformError, PlatformErrorCode};
use latent_executor::PreparationKey;

use crate::cache::{PrepareReservation, PreparedCache};
use crate::preparation_observer::PreparationJob;
use crate::{PreparationObserver, WasmtimeConfig};

pub use metrics::CompilerObserver;
use ready::ReadyGate;
pub(crate) use ready::{ReadyPermit, ReadyPin};
use state::{Core, State};
pub(crate) use wait::PreparationWait;

#[derive(Clone, PartialEq, Eq)]
pub(crate) struct CoalescingKey {
    pub(crate) key: PreparationKey,
    pub(crate) source: ArtifactPreparationIdentity,
    pub(crate) eligibility: Option<latent_artifacts::ReleaseEligibility>,
}

pub(crate) struct Admission {
    pub(crate) identity: Option<CoalescingKey>,
    pub(crate) handle: String,
    pub(crate) source_bytes: usize,
    pub(crate) metadata_bytes: usize,
    pub(crate) document_bytes: usize,
}

pub(crate) struct CompilationResult<T> {
    pub(crate) runtime: Arc<T>,
    pub(crate) reservation: Option<PrepareReservation<T>>,
    pub(crate) observation: PreparationJob,
}

pub(crate) struct QueueWindow {
    pub(crate) started_nanos: u64,
    pub(crate) finished_nanos: u64,
}

type Task<T> = Box<dyn FnOnce(QueueWindow) -> Result<CompilationResult<T>, PlatformError> + Send>;

pub(crate) enum Acquisition<T: Send + Sync + 'static> {
    Ready(ReadyPin<T>),
    Waiting {
        future: PreparationWait<T>,
        owner: bool,
    },
}

pub(crate) struct CompilerPool<T: Send + Sync + 'static> {
    core: Arc<Core<T>>,
    workers: Vec<JoinHandle<()>>,
}

impl<T: Send + Sync + 'static> CompilerPool<T> {
    pub(crate) fn new(
        config: &WasmtimeConfig,
        cache: Arc<PreparedCache<T>>,
        observer: PreparationObserver,
        costs: fn(&T) -> (usize, usize),
    ) -> Result<Self, PlatformError> {
        let metrics = CompilerObserver::new(config, &observer);
        let core = Arc::new(Core {
            state: Mutex::new(State::new()),
            wake: Condvar::new(),
            cache,
            ready: ReadyGate::new(
                config.maximum_ready_preparations,
                config.prepared_cache_maximum_metadata_bytes,
                config.prepared_cache_maximum_compiled_image_bytes,
                metrics.clone(),
            ),
            metrics,
            costs,
            observer,
        });
        let mut pool = Self {
            core,
            workers: Vec::with_capacity(config.effective_compiler_workers()),
        };
        for worker in 0..config.effective_compiler_workers() {
            let core = Arc::clone(&pool.core);
            match std::thread::Builder::new()
                .name(format!("latent-compiler-{worker}"))
                .spawn(move || worker::run(core, worker))
            {
                Ok(handle) => pool.workers.push(handle),
                Err(_) => {
                    pool.stop_and_join()?;
                    return Err(capacity_error("compiler-thread-start"));
                }
            }
        }
        Ok(pool)
    }

    pub(crate) fn observer(&self) -> CompilerObserver {
        self.core.metrics.clone()
    }
}

fn capacity_error(reason: &'static str) -> PlatformError {
    crate::containment::platform_error(PlatformErrorCode::Unavailable, reason, true)
}

fn wake(wakers: Vec<std::task::Waker>) {
    for waker in wakers {
        let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| waker.wake()));
    }
}

//! One wakeable epoch worker, owned by the shared runtime rather than the factory.

use std::sync::mpsc::{self, Sender};
use std::thread::{self, JoinHandle};
use std::time::Duration;

use latent_core::{PlatformError, PlatformErrorCode};
use wasmtime::Engine;

use super::platform_error;

pub(crate) struct EpochTicker {
    stop: Option<Sender<()>>,
    worker: Option<JoinHandle<()>>,
    #[cfg(test)]
    observation: EpochObservation,
}

impl EpochTicker {
    pub(crate) fn start(engine: &Engine, interval: Duration) -> Result<Self, PlatformError> {
        #[cfg(target_has_atomic = "64")]
        {
            let weak_engine = engine.weak();
            let (stop, receiver) = mpsc::channel();
            #[cfg(test)]
            let observation = EpochObservation::default();
            #[cfg(test)]
            let worker_observation = observation.clone();
            let worker = thread::Builder::new()
                .name("latent-wasmtime-epoch".to_owned())
                .spawn(move || {
                    #[cfg(test)]
                    let _completion = Completion(worker_observation.clone());
                    // The worker owns neither the runtime nor its owner/handle.
                    // Dropping the only sender wakes it even with a long interval.
                    while let Err(mpsc::RecvTimeoutError::Timeout) = receiver.recv_timeout(interval)
                    {
                        let Some(engine) = weak_engine.upgrade() else {
                            break;
                        };
                        engine.increment_epoch();
                        #[cfg(test)]
                        worker_observation.ticked();
                    }
                })
                .map_err(|_| {
                    platform_error(
                        PlatformErrorCode::Internal,
                        "failed to start the Wasmtime epoch ticker",
                        false,
                    )
                })?;
            Ok(Self {
                stop: Some(stop),
                worker: Some(worker),
                #[cfg(test)]
                observation,
            })
        }
        #[cfg(not(target_has_atomic = "64"))]
        {
            let _ = (engine, interval);
            Err(platform_error(
                PlatformErrorCode::Internal,
                "Wasmtime epoch interruption requires 64-bit atomics",
                false,
            ))
        }
    }

    pub(crate) fn stop_and_join(&mut self) -> Result<(), PlatformError> {
        drop(self.stop.take());
        let Some(worker) = self.worker.take() else {
            return Ok(());
        };
        // The worker never owns this value, so this is unreachable through the
        // production constructor. Keep the guard to avoid a self-join if that
        // ownership invariant changes; dropping the handle only detaches it.
        if worker.thread().id() == thread::current().id() {
            return Err(platform_error(
                PlatformErrorCode::Internal,
                "wasmtime-epoch-worker-cannot-join-itself",
                false,
            ));
        }
        worker.join().map_err(|_| {
            platform_error(
                PlatformErrorCode::Internal,
                "wasmtime-epoch-worker-panicked",
                false,
            )
        })
    }

    #[cfg(test)]
    pub(crate) fn observation(&self) -> EpochObservation {
        self.observation.clone()
    }
}

impl Drop for EpochTicker {
    fn drop(&mut self) {
        // Joining is best effort during unwinding; the explicit shutdown API
        // reports a worker panic without turning Drop into a second panic.
        let _ = self.stop_and_join();
    }
}

#[cfg(test)]
#[derive(Clone, Default)]
pub(crate) struct EpochObservation(std::sync::Arc<ObservationState>);

#[cfg(test)]
#[derive(Default)]
struct ObservationState {
    ticks: std::sync::atomic::AtomicU64,
    completed: std::sync::atomic::AtomicBool,
}

#[cfg(test)]
impl EpochObservation {
    fn ticked(&self) {
        self.0
            .ticks
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    }

    pub(crate) fn ticks(&self) -> u64 {
        self.0.ticks.load(std::sync::atomic::Ordering::Relaxed)
    }

    pub(crate) fn completed(&self) -> bool {
        self.0.completed.load(std::sync::atomic::Ordering::Acquire)
    }

    fn complete(&self) {
        self.0
            .completed
            .store(true, std::sync::atomic::Ordering::Release);
    }
}

#[cfg(test)]
struct Completion(EpochObservation);

#[cfg(test)]
impl Drop for Completion {
    fn drop(&mut self) {
        self.0.complete();
    }
}

//! Bounded neutral instrumentation for actual preparation stages.
//!
//! This observer owns no engine, repository, Store, worker or execution permit.
//! Linux CPU observations are task ticks, with absent results on probe failure
//! or thread migration. Stage durations exclude their own CPU probe reads;
//! enclosing whole-job observations include instrumentation overhead.

mod cpu;
mod guard;
mod model;
mod state;
#[cfg(test)]
mod tests;
mod wait;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use latent_core::{BoxFuture, PlatformError, ReleaseDigest};

pub(crate) use guard::PreparationJob;
pub use model::{
    PreparationCompilerSnapshot, PreparationObserverSnapshot, PreparationStage,
    PreparationStageObservation, PreparationStageTotals, PreparationThreadCpu,
    PreparationThreadCpuInterval, PreparationThreadIdentity, RunningPreparation,
};
use state::{Inner, State, MAXIMUM_STAGE_OBSERVATIONS};

/// Cloneable diagnostics ownership independent of the runtime factory.
#[derive(Clone)]
pub struct PreparationObserver {
    inner: Arc<Inner>,
}

#[derive(Clone)]
pub(crate) struct PreparationNotifier(std::sync::Weak<Inner>);

impl PreparationNotifier {
    pub(crate) fn notify(&self) {
        if let Some(inner) = self.0.upgrade() {
            let waker = inner.lock().changed();
            state::wake(waker);
        }
    }
}

impl PreparationObserver {
    pub(crate) fn new(maximum_running: usize) -> Self {
        Self {
            inner: Arc::new(Inner {
                enabled: AtomicBool::new(false),
                compiler: Mutex::new(None),
                origin: Instant::now(),
                state: Mutex::new(State::new(maximum_running.clamp(1, 1024))),
            }),
        }
    }

    /// Enables bounded detailed instrumentation for subsequent preparations.
    /// Call before measured work in both comparison arms. It cannot be disabled
    /// midway through a recorded interval. Compiler ownership gauges are separate.
    pub fn enable(&self) {
        if !self.inner.enabled.swap(true, Ordering::AcqRel) {
            let waker = self.inner.lock().changed();
            state::wake(waker);
        }
    }

    #[must_use]
    pub fn snapshot(&self) -> PreparationObserverSnapshot {
        let state = self.inner.lock();
        PreparationObserverSnapshot {
            enabled: self.inner.enabled.load(Ordering::Acquire),
            revision: state.revision,
            observed_nanos: self.inner.elapsed_nanos(),
            maximum_running_entries: state.maximum_running,
            maximum_stage_observations: MAXIMUM_STAGE_OBSERVATIONS,
            active_jobs: state.active_jobs,
            dropped_running_entries: state.dropped_running,
            dropped_stage_observations: state.dropped_observations,
            compiler: self
                .inner
                .compiler
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .as_ref()
                .map(|state| {
                    *state
                        .lock()
                        .unwrap_or_else(std::sync::PoisonError::into_inner)
                }),
            stages: state.stages,
            running: state.running.clone(),
            recent_stages: state.observations.iter().cloned().collect(),
        }
    }

    /// Registers at most one concurrent observation waiter. Drop deregisters it;
    /// it never blocks, pauses or cancels the measured preparation itself.
    pub fn wait_for_change(
        &self,
        after_revision: u64,
    ) -> BoxFuture<'_, Result<u64, PlatformError>> {
        Box::pin(wait::Changed {
            inner: Arc::clone(&self.inner),
            revision: after_revision,
            registration: None,
        })
    }

    pub(crate) fn begin(&self, release: &ReleaseDigest) -> PreparationJob {
        PreparationJob::new(Arc::clone(&self.inner), digest(&release.0))
    }

    pub(crate) fn attach_compiler(&self, state: Arc<Mutex<PreparationCompilerSnapshot>>) {
        *self
            .inner
            .compiler
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = Some(state);
    }

    pub(crate) fn notifier(&self) -> PreparationNotifier {
        PreparationNotifier(Arc::downgrade(&self.inner))
    }
}

fn digest(release: &str) -> Option<[u8; 32]> {
    let encoded = release.strip_prefix("sha256:")?;
    if encoded.len() != 64 {
        return None;
    }
    let mut digest = [0_u8; 32];
    for (value, pair) in digest.iter_mut().zip(encoded.as_bytes().chunks_exact(2)) {
        let high = char::from(pair[0]).to_digit(16)?;
        let low = char::from(pair[1]).to_digit(16)?;
        *value = u8::try_from(high * 16 + low).ok()?;
    }
    Some(digest)
}

use std::sync::{Arc, Mutex};
use std::time::Instant;

use crate::{PreparationCompilerSnapshot, PreparationObserver, WasmtimeConfig};

/// Independent finite counters; retaining this handle retains no compiler.
#[derive(Clone)]
pub struct CompilerObserver {
    pub(super) state: Arc<Mutex<PreparationCompilerSnapshot>>,
    notifier: Option<crate::preparation_observer::PreparationNotifier>,
    last_work_completion: Arc<Mutex<Option<Instant>>>,
}

impl CompilerObserver {
    pub(crate) fn disabled() -> Self {
        Self {
            state: Arc::new(Mutex::new(PreparationCompilerSnapshot::default())),
            notifier: None,
            last_work_completion: Arc::new(Mutex::new(None)),
        }
    }

    pub(super) fn new(config: &WasmtimeConfig, observer: &PreparationObserver) -> Self {
        let mut output = Self::disabled();
        output.notifier = Some(observer.notifier());
        output.update(|state| {
            state.maximum_jobs = config.maximum_concurrent_preparations;
            state.maximum_workers = config.effective_compiler_workers();
            state.maximum_queued_jobs = state.maximum_jobs - state.maximum_workers;
            state.maximum_waiters = config.maximum_preparation_waiters;
            state.maximum_waiters_per_job = config.maximum_waiters_per_preparation;
            state.maximum_ready_preparations = config.maximum_ready_preparations;
            state.maximum_document_bytes = config.maximum_preparation_document_bytes;
            state.accepting = true;
        });
        observer.attach_compiler(Arc::clone(&output.state));
        output
    }

    #[must_use]
    pub fn snapshot(&self) -> PreparationCompilerSnapshot {
        *self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    /// Latest native job completion after its input/result/reservation owners
    /// were disposed. Idle worker retirement and unstarted cancellation do not
    /// change this value. The clock is the process monotonic `Instant` clock.
    #[must_use]
    pub fn last_work_completed_at(&self) -> Option<Instant> {
        *self
            .last_work_completion
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    pub(super) fn record_work_completed_at(&self, completed: Instant) {
        let mut latest = self
            .last_work_completion
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        // Concurrent workers may reach this mutex in a different order.
        *latest = Some(latest.map_or(completed, |previous| previous.max(completed)));
    }

    pub(super) fn update(&self, apply: impl FnOnce(&mut PreparationCompilerSnapshot)) {
        apply(
            &mut self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner),
        );
    }

    /// Call only after releasing registry, waiter and ready-gate locks.
    pub(super) fn notify(&self) {
        if let Some(notifier) = &self.notifier {
            notifier.notify();
        }
    }
}

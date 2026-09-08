use std::sync::{Arc, Mutex};

use crate::{PreparationCompilerSnapshot, PreparationObserver, WasmtimeConfig};

/// Independent finite counters; retaining this handle retains no compiler.
#[derive(Clone)]
pub struct CompilerObserver {
    pub(super) state: Arc<Mutex<PreparationCompilerSnapshot>>,
    notifier: Option<crate::preparation_observer::PreparationNotifier>,
}

impl CompilerObserver {
    pub(crate) fn disabled() -> Self {
        Self {
            state: Arc::new(Mutex::new(PreparationCompilerSnapshot::default())),
            notifier: None,
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

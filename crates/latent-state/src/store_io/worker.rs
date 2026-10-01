use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::Arc;

use super::state::{Bootstrap, Control, Finalizer, QueuedWork, Retirement};
use super::{StoreIoEnginePhase, StoreIoError, StoreIoKind};

enum Action<S> {
    Run(QueuedWork<S>),
    Reject(QueuedWork<S>),
    Retire(Box<dyn Retirement>),
    Finalize(Finalizer<S>),
    Exit,
}

fn next<S>(control: &Control<S>, recovery: bool) -> Action<S> {
    let mut state = control
        .state
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    loop {
        if matches!(state.bootstrap, Bootstrap::Spawning) {
            state = control
                .changed
                .wait(state)
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            continue;
        }
        state.check_shutdown_deadline(control.clock.monotonic_now());
        let retirements = if recovery {
            &mut state.recovery_retirements
        } else {
            &mut state.retirements
        };
        if let Some(retirement) = retirements.pop_front() {
            return Action::Retire(retirement);
        }
        if state.quarantined {
            let queue = if recovery {
                &mut state.recovery_queue
            } else {
                &mut state.queue
            };
            if let Some(queued) = queue.pop_front() {
                return Action::Reject(queued);
            }
        } else if let Some(index) = {
            let queue = if recovery {
                &state.recovery_queue
            } else {
                &state.queue
            };
            queue.iter().position(|queued| state.can_run(queued.kind))
        } {
            let queue = if recovery {
                &mut state.recovery_queue
            } else {
                &mut state.queue
            };
            let queued = queue.remove(index).expect("selected bounded queue index");
            state.running(queued.kind, true);
            return Action::Run(queued);
        }
        if state.closed
            && state.queue.is_empty()
            && state.recovery_queue.is_empty()
            && state.physical_owners == 0
        {
            // Reserve exit under the same lock. Concurrent idle workers cannot
            // all believe another worker will perform the finalization.
            let last = state.live_workers - state.exiting_workers == 1;
            state.exiting_workers += 1;
            if !last || matches!(state.bootstrap, Bootstrap::Failed) {
                return Action::Exit;
            }
            if let Some(finalizer) = state.finalizer.take() {
                state.engine_phase = StoreIoEnginePhase::Finalizing;
                return Action::Finalize(finalizer);
            }
            return Action::Exit;
        }
        state = control
            .changed
            .wait(state)
            .unwrap_or_else(std::sync::PoisonError::into_inner);
    }
}

fn finished_job<S>(control: &Control<S>, kind: StoreIoKind) {
    control
        .state
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .running(kind, false);
    control.notify();
}

pub(super) fn run<S: Send + Sync + 'static>(
    control: Arc<Control<S>>,
    store: Arc<S>,
    recovery: bool,
) {
    loop {
        match next(&control, recovery) {
            Action::Run(queued) => {
                queued.work.run(&store);
                finished_job(&control, queued.kind);
            }
            Action::Reject(queued) => {
                queued.work.reject();
                control.notify();
            }
            Action::Retire(retirement) => {
                if catch_unwind(AssertUnwindSafe(|| retirement.retire())).is_err() {
                    control.fail(StoreIoError::RecoveryRequired);
                }
            }
            Action::Finalize(finalizer) => {
                control.notify();
                let finalization = catch_unwind(AssertUnwindSafe(|| finalizer(&store)));
                {
                    let mut state = control
                        .state
                        .lock()
                        .unwrap_or_else(std::sync::PoisonError::into_inner);
                    if !matches!(finalization, Ok(Ok(()))) {
                        state.quarantined = true;
                        state.failure = Some(StoreIoError::FinalizationFailed);
                    }
                }
                break;
            }
            Action::Exit => break,
        }
    }
    // A nonfinal worker decrements first; the final worker must destroy the
    // actual engine before publishing its own physical retirement.
    drop(store);
    let retired_at = control.clock.monotonic_now();
    {
        let mut state = control
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.live_workers -= 1;
        state.exiting_workers -= 1;
        if state.live_workers == 0 {
            state.engine_phase = StoreIoEnginePhase::Closed;
            state.retained_bytes -= state.limits.resident_bytes;
            if state.accepted == 0 {
                state.retired_at = Some(retired_at);
            }
            state.queue = std::collections::VecDeque::new();
            state.recovery_queue = std::collections::VecDeque::new();
        }
    }
    control.notify();
    drop(control);
}

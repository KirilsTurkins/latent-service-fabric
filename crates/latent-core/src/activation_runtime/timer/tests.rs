use super::super::tests::{child_runtime, runtime};
use super::*;
use std::sync::mpsc;

#[test]
fn original_cancellation_after_the_live_check_does_not_commit_timer_readiness() {
    for period in [None, Some(Duration::from_millis(1))] {
        let runtime = runtime();
        let first = Instant::now();
        let timer = RuntimeTimer::new(&runtime, first, period, None).unwrap();
        let mut wait = timer.begin_wait().unwrap();
        let before = runtime.snapshot();
        let budget = runtime.inner.budget.clone();
        let result = wait.complete_with_after_live_check(first, || {
            budget.cancel_descendants().unwrap();
        });
        assert_eq!(result.unwrap_err().code, PlatformErrorCode::Cancelled);
        let schedule = timer.inner.schedule.lock().unwrap();
        assert_eq!(schedule.next, Some(first));
        assert!(schedule.waiting);
        drop(schedule);
        let after = runtime.snapshot();
        assert_eq!(after.owners, before.owners);
        assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
        drop(wait);
        drop(timer);
        runtime.retire().unwrap();
    }
}

#[test]
fn finalized_budget_after_the_live_check_refuses_timer_readiness() {
    let runtime = runtime();
    let first = Instant::now();
    let timer = RuntimeTimer::new(&runtime, first, None, None).unwrap();
    let mut wait = timer.begin_wait().unwrap();
    let before = runtime.snapshot();
    let budget = runtime.inner.budget.clone();
    let result = wait.complete_with_after_live_check(first, || {
        let _ = budget.finalize_at(None, Instant::now());
    });
    assert_eq!(result.unwrap_err().code, PlatformErrorCode::Cancelled);
    assert!(budget.finalized().is_some());
    assert_eq!(timer.inner.schedule.lock().unwrap().next, Some(first));
    let after = runtime.snapshot();
    assert_eq!(after.owners, before.owners);
    assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
    assert_eq!(after.phase, super::super::RuntimePhase::Cancelling);
    drop(wait);
    drop(timer);
    runtime.retire().unwrap();
}

#[test]
fn ancestor_stop_after_the_live_check_refuses_timer_readiness() {
    for finalize in [false, true] {
        let (parent, child, runtime) = child_runtime();
        let first = Instant::now();
        let timer =
            RuntimeTimer::new(&runtime, first, Some(Duration::from_millis(1)), None).unwrap();
        let mut wait = timer.begin_wait().unwrap();
        let before = runtime.snapshot();
        let result = wait.complete_with_after_live_check(first, || {
            if finalize {
                let _ = parent.finalize_at(None, Instant::now());
            } else {
                parent.cancel_descendants().unwrap();
            }
        });
        assert_eq!(result.unwrap_err().code, PlatformErrorCode::Cancelled);
        assert_eq!(timer.inner.schedule.lock().unwrap().next, Some(first));
        let after = runtime.snapshot();
        assert_eq!(after.owners, before.owners);
        assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
        assert_eq!(after.phase, super::super::RuntimePhase::Cancelling);
        drop(wait);
        drop(timer);
        runtime.retire().unwrap();
        drop(runtime);
        let _ = child.finish(None, Instant::now());
        assert_eq!(parent.descendant_snapshot().unwrap().live_descendants, 0);
    }
}

#[test]
fn closed_timer_keeps_its_error_when_original_budget_is_cancelled_after_check() {
    let runtime = runtime();
    let first = Instant::now();
    let timer = RuntimeTimer::new(&runtime, first, None, None).unwrap();
    let mut wait = timer.begin_wait().unwrap();
    let budget = runtime.inner.budget.clone();
    let result = wait.complete_with_after_live_check(first, || {
        timer.close();
        budget.cancel_descendants().unwrap();
    });
    let failure = result.unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::Cancelled);
    assert_eq!(failure.message, "runtime-timer-closed");
    assert_eq!(
        runtime.snapshot().phase,
        super::super::RuntimePhase::Running
    );
    drop(wait);
    drop(timer);
    runtime.retire().unwrap();
}

#[test]
fn finalization_after_the_last_probe_can_precede_timer_publication() {
    // The budget terminal transition does not take these timer/runtime locks.
    // The already-paid timer and wait remain charged until physical drop.
    let runtime = runtime();
    let first = Instant::now();
    let timer = RuntimeTimer::new(&runtime, first, None, None).unwrap();
    let mut wait = timer.begin_wait().unwrap();
    let budget = runtime.inner.budget.clone();
    let before = runtime.snapshot();
    let result = wait.complete_with_hooks(
        first,
        || {},
        || {
            let terminal = budget.finalize_at(None, Instant::now());
            assert!(terminal.consumption().peak_memory_bytes >= before.host_memory_bytes);
        },
    );
    assert_eq!(result.unwrap(), 0);
    assert!(budget.finalized().is_some());
    assert_eq!(timer.inner.schedule.lock().unwrap().next, None);
    let after = runtime.snapshot();
    assert_eq!(after.owners, before.owners);
    assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
    drop(wait);
    drop(timer);
    runtime.retire().unwrap();
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn deadline_after_the_last_probe_can_precede_timer_publication() {
    // The monotonic deadline can pass after observation and before the write;
    // the ledger check is not a clock/commit handshake.
    let runtime = runtime();
    let first = Instant::now();
    let deadline = runtime.inner.budget.deadline().monotonic().unwrap();
    let timer = RuntimeTimer::new(&runtime, first, None, None).unwrap();
    let mut wait = timer.begin_wait().unwrap();
    let result = wait.complete_with_hooks(
        first,
        || {},
        || {
            assert!(Instant::now() < deadline);
            std::thread::sleep(
                deadline.saturating_duration_since(Instant::now()) + Duration::from_millis(5),
            );
            assert!(Instant::now() >= deadline);
        },
    );
    assert_eq!(result.unwrap(), 0);
    assert_eq!(timer.inner.schedule.lock().unwrap().next, None);
    drop(wait);
    drop(timer);
    runtime.retire().unwrap();
}

#[test]
fn deadline_expiring_after_the_live_check_does_not_commit_timer_readiness() {
    let runtime = runtime();
    let first = Instant::now();
    let deadline = runtime.inner.budget.deadline().monotonic().unwrap();
    let (checked_tx, checked_rx) = mpsc::channel();
    let mut cases = Vec::new();
    for period in [None, Some(Duration::from_millis(1))] {
        let timer = RuntimeTimer::new(&runtime, first, period, None).unwrap();
        let mut wait = timer.begin_wait().unwrap();
        let checked = checked_tx.clone();
        let (resume_tx, resume_rx) = mpsc::sync_channel(0);
        let worker = std::thread::spawn(move || {
            let result = wait.complete_with_after_live_check(first, || {
                checked.send(()).unwrap();
                resume_rx.recv_timeout(Duration::from_secs(10)).unwrap();
            });
            (result, wait)
        });
        cases.push((timer, resume_tx, worker));
    }
    for _ in 0..cases.len() {
        checked_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    }
    assert!(Instant::now() < deadline);
    let before = runtime.snapshot();
    std::thread::sleep(
        deadline.saturating_duration_since(Instant::now()) + Duration::from_millis(5),
    );
    assert!(Instant::now() >= deadline);
    for (_, resume, _) in &cases {
        resume.send(()).unwrap();
    }
    let mut finished = Vec::new();
    for (timer, _, worker) in cases {
        let (result, wait) = worker.join().unwrap();
        assert_eq!(
            result.unwrap_err().code,
            PlatformErrorCode::DeadlineExceeded
        );
        let schedule = timer.inner.schedule.lock().unwrap();
        assert_eq!(schedule.next, Some(first));
        assert!(schedule.waiting);
        drop(schedule);
        finished.push((timer, wait));
    }
    assert_eq!(runtime.snapshot().owners, before.owners);
    assert_eq!(
        runtime.snapshot().host_memory_bytes,
        before.host_memory_bytes
    );
    drop(finished);
    runtime.retire().unwrap();
}

#[test]
fn cancelled_runtime_does_not_complete_or_advance_an_admitted_timer() {
    let runtime = runtime();
    let first = Instant::now();
    let timer = RuntimeTimer::new(&runtime, first, Some(Duration::from_millis(1)), None).unwrap();
    let mut wait = timer.begin_wait().unwrap();
    let before = runtime.snapshot();
    let (checked_tx, checked_rx) = mpsc::sync_channel(0);
    let (resume_tx, resume_rx) = mpsc::sync_channel(0);
    let worker = std::thread::spawn(move || {
        let result = wait.complete_with_after_live_check(first, || {
            checked_tx.send(()).unwrap();
            resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
        });
        (result, wait)
    });
    checked_rx.recv_timeout(Duration::from_secs(5)).unwrap();
    runtime.cancel();
    resume_tx.send(()).unwrap();
    let (result, wait) = worker.join().unwrap();
    assert_eq!(result.unwrap_err().code, PlatformErrorCode::Cancelled);
    let after = runtime.snapshot();
    assert_eq!(after.phase, super::super::RuntimePhase::Cancelling);
    assert_eq!(after.owners, before.owners);
    assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
    let schedule = timer.inner.schedule.lock().unwrap();
    assert_eq!(schedule.next, Some(first));
    assert!(schedule.waiting);
    drop(schedule);
    drop(wait);
    drop(timer);
    runtime.retire().unwrap();
}

#[test]
fn admitted_timer_can_complete_while_closing_and_draining() {
    for draining in [false, true] {
        let runtime = runtime();
        let first = Instant::now();
        let timer =
            RuntimeTimer::new(&runtime, first, Some(Duration::from_millis(1)), None).unwrap();
        let mut wait = timer.begin_wait().unwrap();
        runtime.close();
        if draining {
            runtime.begin_drain();
        }
        assert_eq!(wait.complete(first).unwrap(), 0);
        let schedule = timer.inner.schedule.lock().unwrap();
        assert_eq!(schedule.next, first.checked_add(Duration::from_millis(1)));
        drop(schedule);
        assert_eq!(
            runtime.snapshot().phase,
            if draining {
                super::super::RuntimePhase::Draining
            } else {
                super::super::RuntimePhase::Closing
            }
        );
        drop(wait);
        drop(timer);
        runtime.retire().unwrap();
    }
}

#[test]
fn closed_timer_retains_its_existing_error_when_close_and_cancel_win() {
    let runtime = runtime();
    let first = Instant::now();
    let timer = RuntimeTimer::new(&runtime, first, None, None).unwrap();
    let mut wait = timer.begin_wait().unwrap();
    let (checked_tx, checked_rx) = mpsc::sync_channel(0);
    let (resume_tx, resume_rx) = mpsc::sync_channel(0);
    let worker = std::thread::spawn(move || {
        let result = wait.complete_with_after_live_check(first, || {
            checked_tx.send(()).unwrap();
            resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
        });
        (result, wait)
    });
    checked_rx.recv_timeout(Duration::from_secs(5)).unwrap();
    timer.close();
    runtime.cancel();
    resume_tx.send(()).unwrap();
    let (result, wait) = worker.join().unwrap();
    let error = result.unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::Cancelled);
    assert_eq!(error.message, "runtime-timer-closed");
    drop(wait);
    drop(timer);
    runtime.retire().unwrap();
}

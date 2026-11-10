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
fn same_ledger_finalization_before_timer_publication_refuses_readiness() {
    for period in [None, Some(Duration::from_millis(1))] {
        let runtime = runtime();
        let first = Instant::now();
        let timer = RuntimeTimer::new(&runtime, first, period, None).unwrap();
        let mut wait = timer.begin_wait().unwrap();
        let budget = runtime.inner.budget.clone();
        let before = runtime.snapshot();
        let (checked_tx, checked_rx) = mpsc::sync_channel(0);
        let (resume_tx, resume_rx) = mpsc::sync_channel(0);
        let worker = std::thread::spawn(move || {
            let result = wait.complete_with_hooks(
                first,
                || {},
                || {
                    checked_tx.send(()).unwrap();
                    resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                },
                || {},
            );
            (result, wait)
        });
        checked_rx.recv_timeout(Duration::from_secs(3)).unwrap();
        let close_budget = budget.clone();
        let (closed_tx, closed_rx) = mpsc::sync_channel(0);
        let closer = std::thread::spawn(move || {
            let terminal = close_budget.finalize_at(None, Instant::now());
            closed_tx
                .send(terminal.consumption().peak_memory_bytes)
                .unwrap();
        });
        let early = closed_rx.recv_timeout(Duration::from_secs(3));
        let closed_before_resume = early.is_ok();
        // Always release the worker before asserting the race outcome.
        resume_tx.send(()).unwrap();
        let (result, wait) = worker.join().unwrap();
        let terminal_peak = match early {
            Ok(peak) => peak,
            Err(_) => closed_rx.recv_timeout(Duration::from_secs(3)).unwrap(),
        };
        closer.join().unwrap();
        assert!(closed_before_resume);
        assert!(terminal_peak >= before.host_memory_bytes);
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
        assert_eq!(budget.host_memory_bytes(), 0);
    }
}

#[test]
fn same_ledger_finalization_waits_for_timer_publication() {
    for period in [None, Some(Duration::from_millis(1))] {
        let runtime = runtime();
        let first = Instant::now();
        let timer = RuntimeTimer::new(&runtime, first, period, None).unwrap();
        let mut wait = timer.begin_wait().unwrap();
        let budget = runtime.inner.budget.clone();
        let before = runtime.snapshot();
        let (held_tx, held_rx) = mpsc::sync_channel(0);
        let (resume_tx, resume_rx) = mpsc::sync_channel(0);
        let worker = std::thread::spawn(move || {
            let result = wait.complete_with_hooks(
                first,
                || {},
                || {},
                || {
                    held_tx.send(()).unwrap();
                    resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                },
            );
            (result, wait)
        });
        held_rx.recv_timeout(Duration::from_secs(3)).unwrap();
        let close_budget = budget.clone();
        let (observed_tx, observed_rx) = mpsc::sync_channel(0);
        let (closed_tx, closed_rx) = mpsc::sync_channel(0);
        let closer = std::thread::spawn(move || {
            observed_tx
                .send(close_budget.test_accounting_is_locked())
                .unwrap();
            let terminal = close_budget.finalize_at(None, Instant::now());
            closed_tx
                .send(terminal.consumption().peak_memory_bytes)
                .unwrap();
        });
        let observed_locked = observed_rx.recv_timeout(Duration::from_secs(3)).unwrap();
        let early = closed_rx.recv_timeout(Duration::from_millis(100));
        let finished_early = early.is_ok();
        // Release the worker before asserting, including on a failed control.
        resume_tx.send(()).unwrap();
        let (result, wait) = worker.join().unwrap();
        let terminal_peak = if finished_early {
            early.unwrap()
        } else {
            closed_rx.recv_timeout(Duration::from_secs(3)).unwrap()
        };
        closer.join().unwrap();
        assert!(observed_locked);
        assert!(!finished_early);
        assert_eq!(result.unwrap(), 0);
        assert!(terminal_peak >= before.host_memory_bytes);
        assert_eq!(
            timer.inner.schedule.lock().unwrap().next,
            period.map(|period| first + period)
        );
        let after = runtime.snapshot();
        assert_eq!(after.owners, before.owners);
        assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
        drop(wait);
        drop(timer);
        runtime.retire().unwrap();
        drop(runtime);
        assert_eq!(budget.host_memory_bytes(), 0);
    }
}

#[test]
fn same_ledger_cancellation_before_timer_write_refuses_readiness() {
    // The atomic closed-flag store does not take the accounting mutex. This
    // control uses a no-op terminal probe.
    let runtime = runtime();
    let first = Instant::now();
    let timer = RuntimeTimer::new(&runtime, first, None, None).unwrap();
    let mut wait = timer.begin_wait().unwrap();
    let budget = runtime.inner.budget.clone();
    let (held_tx, held_rx) = mpsc::sync_channel(0);
    let (resume_tx, resume_rx) = mpsc::sync_channel(0);
    let worker = std::thread::spawn(move || {
        let result = wait.complete_with_hooks(
            first,
            || {},
            || {},
            || {
                held_tx.send(()).unwrap();
                resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
            },
        );
        (result, wait)
    });
    held_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    let close_budget = budget.clone();
    let (done_tx, done_rx) = mpsc::sync_channel(0);
    let closer = std::thread::spawn(move || {
        close_budget.cancel_descendants().unwrap();
        done_tx.send(()).unwrap();
    });
    let cancellation = done_rx.recv_timeout(Duration::from_secs(3));
    let was_nonblocking = cancellation.is_ok();
    resume_tx.send(()).unwrap();
    let (result, wait) = worker.join().unwrap();
    if !was_nonblocking {
        done_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    }
    closer.join().unwrap();
    assert!(was_nonblocking);
    assert_eq!(result.unwrap_err().code, PlatformErrorCode::Cancelled);
    assert_eq!(timer.inner.schedule.lock().unwrap().next, Some(first));
    drop(wait);
    drop(timer);
    runtime.retire().unwrap();
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn same_ledger_cancellation_rolls_back_hidden_timer_write() {
    for period in [None, Some(Duration::from_millis(1))] {
        let runtime = runtime();
        let first = Instant::now();
        let timer = RuntimeTimer::new(&runtime, first, period, None).unwrap();
        let mut wait = timer.begin_wait().unwrap();
        let before = runtime.snapshot();
        let budget = runtime.inner.budget.clone();
        let (held_tx, held_rx) = mpsc::sync_channel(0);
        let (resume_tx, resume_rx) = mpsc::sync_channel(0);
        let worker = std::thread::spawn(move || {
            let result = wait.complete_with_publication_hooks(
                first,
                || {},
                || {},
                || {},
                || {
                    held_tx.send(()).unwrap();
                    resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                },
                || {},
            );
            (result, wait)
        });
        held_rx.recv_timeout(Duration::from_secs(3)).unwrap();
        let schedule_hidden = matches!(
            timer.inner.schedule.try_lock(),
            Err(std::sync::TryLockError::WouldBlock)
        );
        let state_hidden = matches!(
            runtime.inner.state.try_lock(),
            Err(std::sync::TryLockError::WouldBlock)
        );
        let accounting_held = budget.test_accounting_is_locked();
        let close_budget = budget.clone();
        let (done_tx, done_rx) = mpsc::sync_channel(0);
        let closer = std::thread::spawn(move || {
            close_budget.cancel_descendants().unwrap();
            done_tx.send(()).unwrap();
        });
        let cancelled = done_rx.recv_timeout(Duration::from_secs(3));
        let signalled = cancelled.is_ok();
        resume_tx.send(()).unwrap();
        let (result, wait) = worker.join().unwrap();
        if !signalled {
            done_rx.recv_timeout(Duration::from_secs(3)).unwrap();
        }
        closer.join().unwrap();
        assert!(schedule_hidden && state_hidden && accounting_held && signalled);
        assert_eq!(result.unwrap_err().code, PlatformErrorCode::Cancelled);
        let schedule = timer.inner.schedule.lock().unwrap();
        assert_eq!(schedule.next, Some(first));
        assert!(schedule.waiting);
        drop(schedule);
        let after = runtime.snapshot();
        assert_eq!(after.phase, super::super::RuntimePhase::Cancelling);
        assert_eq!(after.owners, before.owners);
        assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
        drop(wait);
        drop(timer);
        runtime.retire().unwrap();
        drop(runtime);
        assert_eq!(budget.host_memory_bytes(), 0);
    }
}

#[test]
fn same_ledger_cancellation_after_timer_commit_keeps_readiness_charged() {
    for period in [None, Some(Duration::from_millis(1))] {
        let runtime = runtime();
        let first = Instant::now();
        let timer = RuntimeTimer::new(&runtime, first, period, None).unwrap();
        let mut wait = timer.begin_wait().unwrap();
        let before = runtime.snapshot();
        let budget = runtime.inner.budget.clone();
        let (held_tx, held_rx) = mpsc::sync_channel(0);
        let (resume_tx, resume_rx) = mpsc::sync_channel(0);
        let worker = std::thread::spawn(move || {
            let result = wait.complete_with_publication_hooks(
                first,
                || {},
                || {},
                || {},
                || {},
                || {
                    held_tx.send(()).unwrap();
                    resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                },
            );
            (result, wait)
        });
        held_rx.recv_timeout(Duration::from_secs(3)).unwrap();
        let schedule_hidden = matches!(
            timer.inner.schedule.try_lock(),
            Err(std::sync::TryLockError::WouldBlock)
        );
        let state_hidden = matches!(
            runtime.inner.state.try_lock(),
            Err(std::sync::TryLockError::WouldBlock)
        );
        let accounting_held = budget.test_accounting_is_locked();
        let close_budget = budget.clone();
        let (done_tx, done_rx) = mpsc::sync_channel(0);
        let closer = std::thread::spawn(move || {
            close_budget.cancel_descendants().unwrap();
            done_tx.send(()).unwrap();
        });
        let cancelled = done_rx.recv_timeout(Duration::from_secs(3));
        let signalled = cancelled.is_ok();
        let finalize_budget = budget.clone();
        let (started_tx, started_rx) = mpsc::sync_channel(0);
        let (final_tx, final_rx) = mpsc::sync_channel(0);
        let finalizer = std::thread::spawn(move || {
            started_tx.send(()).unwrap();
            let terminal = finalize_budget.finalize_at(None, Instant::now());
            final_tx
                .send(terminal.consumption().peak_memory_bytes)
                .unwrap();
        });
        started_rx.recv_timeout(Duration::from_secs(3)).unwrap();
        let early = final_rx.recv_timeout(Duration::from_millis(100));
        let finalized_early = early.is_ok();
        resume_tx.send(()).unwrap();
        let (result, wait) = worker.join().unwrap();
        if !signalled {
            done_rx.recv_timeout(Duration::from_secs(3)).unwrap();
        }
        let terminal_peak = match early {
            Ok(peak) => peak,
            Err(_) => final_rx.recv_timeout(Duration::from_secs(3)).unwrap(),
        };
        closer.join().unwrap();
        finalizer.join().unwrap();
        assert!(schedule_hidden && state_hidden && accounting_held && signalled);
        assert!(!finalized_early);
        assert_eq!(result.unwrap(), 0);
        assert_eq!(
            timer.inner.schedule.lock().unwrap().next,
            period.map(|period| first + period)
        );
        let after = runtime.snapshot();
        assert_eq!(after.owners, before.owners);
        assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
        assert!(terminal_peak >= before.host_memory_bytes);
        drop(wait);
        drop(timer);
        runtime.retire().unwrap();
        drop(runtime);
        assert_eq!(budget.host_memory_bytes(), 0);
    }
}

#[test]
fn ancestor_closure_before_timer_commit_refuses_readiness() {
    let mut outcomes = Vec::new();
    for finalize in [false, true] {
        for period in [None, Some(Duration::from_millis(1))] {
            let (parent, child, runtime) = child_runtime();
            let first = Instant::now();
            let timer = RuntimeTimer::new(&runtime, first, period, None).unwrap();
            let mut wait = timer.begin_wait().unwrap();
            let before = runtime.snapshot();
            let (held_tx, held_rx) = mpsc::sync_channel(0);
            let (resume_tx, resume_rx) = mpsc::sync_channel(0);
            let worker = std::thread::spawn(move || {
                let result = wait.complete_with_publication_hooks(
                    first,
                    || {},
                    || {},
                    || {},
                    || {
                        held_tx.send(()).unwrap();
                        resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                    },
                    || {},
                );
                (result, wait)
            });
            held_rx.recv_timeout(Duration::from_secs(3)).unwrap();
            let close_parent = parent.clone();
            let (done_tx, done_rx) = mpsc::sync_channel(0);
            let closer = std::thread::spawn(move || {
                if finalize {
                    let _ = close_parent.finalize_at(None, Instant::now());
                } else {
                    close_parent.cancel_descendants().unwrap();
                }
                done_tx.send(()).unwrap();
            });
            let terminal_received = done_rx.recv_timeout(Duration::from_secs(3));
            let completed = terminal_received.is_ok();
            resume_tx.send(()).unwrap();
            let (result, wait) = worker.join().unwrap();
            if !completed {
                done_rx.recv_timeout(Duration::from_secs(3)).unwrap();
            }
            closer.join().unwrap();
            let after = runtime.snapshot();
            let next = timer.inner.schedule.lock().unwrap().next;
            outcomes.push((
                finalize,
                period,
                completed,
                result.is_ok(),
                first,
                next,
                before,
                after,
            ));
            drop(wait);
            drop(timer);
            runtime.retire().unwrap();
            drop(runtime);
            let _ = child.finish(None, Instant::now());
            assert_eq!(parent.descendant_snapshot().unwrap().live_descendants, 0);
        }
    }
    for (finalize, period, completed, published, first, next, before, after) in outcomes {
        assert!(completed);
        assert!(
            !published,
            "finalize={finalize} period={period:?} published after ancestor closure"
        );
        assert_eq!(next, Some(first));
        assert_eq!(after.phase, super::super::RuntimePhase::Cancelling);
        assert_eq!(after.owners, before.owners);
        assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
    }
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

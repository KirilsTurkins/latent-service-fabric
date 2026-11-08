use super::*;
use crate::{BudgetProfile, ClockSample, EffectiveActivationBudget, ResourceBudget};
use std::sync::Arc;

struct Signal;
impl crate::BudgetCancellationProbe for Signal {
    fn is_cancelled(&self) -> bool {
        false
    }
    fn cancelled(&self) -> crate::BoxFuture<'_, ()> {
        Box::pin(std::future::pending())
    }
    fn mark_terminal(&self) {}
}

pub(super) fn runtime() -> ActivationRuntime {
    runtime_with_probe(Arc::new(Signal))
}

fn runtime_with_probe(probe: Arc<dyn crate::BudgetCancellationProbe>) -> ActivationRuntime {
    let budget = ResourceBudget {
        cpu_fuel: 1_000_000,
        memory_bytes: 1_000_000,
        wall_time_limit_millis: Some(5000),
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 0,
        effect_count: 0,
    };
    let grant = EffectiveActivationBudget::admit_profile_at(
        BudgetProfile::Phase3,
        &budget,
        &budget,
        &budget,
        None,
        ClockSample::new(1000, Instant::now()),
    )
    .unwrap();
    let budget = ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap();
    budget
        .enable_descendants(crate::DelegationLimits::default(), probe)
        .unwrap();
    runtime_with_budget(budget)
}

fn runtime_with_budget(budget: ActivationBudget) -> ActivationRuntime {
    ActivationRuntime::new(
        budget,
        RuntimeLimits {
            tasks: 2,
            executors: 2,
            queued_work: 2,
            waits: 2,
            timers: 2,
            results: 2,
            native_owners: 2,
        },
    )
    .unwrap()
}

pub(super) fn child_runtime() -> (ActivationBudget, crate::ChildBudgetOwner, ActivationRuntime) {
    child_runtime_with_probes(Arc::new(Signal), Arc::new(Signal))
}

fn child_runtime_with_probes(
    parent_probe: Arc<dyn crate::BudgetCancellationProbe>,
    child_probe: Arc<dyn crate::BudgetCancellationProbe>,
) -> (ActivationBudget, crate::ChildBudgetOwner, ActivationRuntime) {
    let parent_limit = ResourceBudget {
        cpu_fuel: 2_000_000,
        memory_bytes: 2_000_000,
        wall_time_limit_millis: Some(5000),
        child_calls: 2,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 0,
        effect_count: 0,
    };
    let sample = ClockSample::new(1000, Instant::now());
    let grant = EffectiveActivationBudget::admit_profile_at(
        BudgetProfile::Phase3,
        &parent_limit,
        &parent_limit,
        &parent_limit,
        None,
        sample,
    )
    .unwrap();
    let parent = ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap();
    parent
        .enable_descendants(crate::DelegationLimits::default(), parent_probe)
        .unwrap();
    let mut requested = parent_limit.clone();
    requested.cpu_fuel = 1_000_000;
    requested.memory_bytes = 1_000_000;
    requested.child_calls = 0;
    let pending = parent
        .delegate_at(&requested, &requested, &parent_limit, None, sample)
        .unwrap();
    let child_grant = pending.grant();
    let child = pending
        .accept(&child_grant, child_probe, sample.monotonic())
        .unwrap();
    let runtime = runtime_with_budget(child.accounting().clone());
    (parent, child, runtime)
}

#[test]
fn commit_authority_probe_does_not_lock_runtime_or_budget_again() {
    use std::sync::mpsc;
    use std::time::Duration;

    let runtime = runtime();
    let budget = runtime.inner.budget.clone();
    let (held_tx, held_rx) = mpsc::sync_channel(0);
    let (release_tx, release_rx) = mpsc::sync_channel(0);
    let holder = std::thread::spawn(move || {
        budget.with_test_accounting_lock(|| {
            held_tx.send(()).unwrap();
            release_rx.recv_timeout(Duration::from_secs(5)).unwrap();
        });
    });
    held_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    let (done_tx, done_rx) = mpsc::sync_channel(0);
    let worker_runtime = runtime.clone();
    let worker = std::thread::spawn(move || {
        let _state = worker_runtime.inner.state.lock().unwrap();
        done_tx.send(worker_runtime.check_commit_ledger()).unwrap();
    });
    let result = done_rx.recv_timeout(Duration::from_secs(2));
    release_tx.send(()).unwrap();
    holder.join().unwrap();
    if result.is_ok() {
        worker.join().unwrap();
    }
    assert!(result.unwrap().is_ok());
    runtime.retire().unwrap();
}

#[test]
fn commit_ledger_probe_does_not_call_a_locked_external_probe() {
    use std::sync::{mpsc, Mutex};
    use std::time::Duration;

    struct LockingProbe(Arc<Mutex<()>>);
    impl crate::BudgetCancellationProbe for LockingProbe {
        fn is_cancelled(&self) -> bool {
            let _guard = self.0.lock().unwrap();
            false
        }
        fn cancelled(&self) -> crate::BoxFuture<'_, ()> {
            Box::pin(std::future::pending())
        }
        fn mark_terminal(&self) {}
    }

    let gate = Arc::new(Mutex::new(()));
    let runtime = runtime_with_probe(Arc::new(LockingProbe(gate.clone())));
    let (held_tx, held_rx) = mpsc::sync_channel(0);
    let (release_tx, release_rx) = mpsc::sync_channel(0);
    let holder = std::thread::spawn(move || {
        let _guard = gate.lock().unwrap();
        held_tx.send(()).unwrap();
        release_rx.recv_timeout(Duration::from_secs(5)).unwrap();
    });
    held_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    let (done_tx, done_rx) = mpsc::sync_channel(0);
    let worker_runtime = runtime.clone();
    let worker = std::thread::spawn(move || {
        let _state = worker_runtime.inner.state.lock().unwrap();
        done_tx.send(worker_runtime.check_commit_ledger()).unwrap();
    });
    let result = done_rx.recv_timeout(Duration::from_secs(2));
    release_tx.send(()).unwrap();
    holder.join().unwrap();
    if result.is_ok() {
        worker.join().unwrap();
    }
    assert!(result.unwrap().is_ok());
    runtime.retire().unwrap();
}

#[test]
fn finalization_during_admission_refuses_without_releasing_allocated_slab() {
    for stop_at in [
        AdmissionStep::CheckedBeforeAccounting,
        AdmissionStep::ChargedFuel,
        AdmissionStep::PreparedSlot,
    ] {
        let runtime = runtime();
        let budget = runtime.inner.budget.clone();
        let original = budget.host_memory_bytes();
        let mut reached = false;
        let mut state = runtime.inner.state.lock().unwrap();
        let result = runtime.register_locked_with_hook(&mut state, OwnerKind::Task, None, |step| {
            if step == stop_at {
                reached = true;
                let _ = budget.finalize_at(None, Instant::now());
            }
        });
        drop(state);
        assert!(reached);
        assert_eq!(result.unwrap_err().code, PlatformErrorCode::Cancelled);
        assert!(budget.finalized().is_some());
        let after = runtime.snapshot();
        assert_eq!(after.owners, [0; 7]);
        if stop_at == AdmissionStep::PreparedSlot {
            assert!(after.host_memory_bytes > original);
        } else {
            assert_eq!(after.host_memory_bytes, original);
        }
        runtime.retire().unwrap();
        assert_eq!(budget.host_memory_bytes(), original);
        drop(runtime);
        assert_eq!(budget.host_memory_bytes(), 0);
    }
}

#[test]
fn same_ledger_finalization_before_owner_commit_refuses_publication() {
    use std::sync::mpsc;
    use std::time::Duration;

    let runtime = runtime();
    let budget = runtime.inner.budget.clone();
    let worker_runtime = runtime.clone();
    let (checked_tx, checked_rx) = mpsc::sync_channel(0);
    let (release_tx, release_rx) = mpsc::sync_channel(0);
    let worker = std::thread::spawn(move || {
        let mut state = worker_runtime.inner.state.lock().unwrap();
        worker_runtime.register_locked_with_hook(&mut state, OwnerKind::Task, None, |step| {
            if step == AdmissionStep::CheckedBeforePublication {
                checked_tx.send(()).unwrap();
                release_rx.recv_timeout(Duration::from_secs(5)).unwrap();
            }
        })
    });
    checked_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    let reserved_at_terminal = budget.host_memory_bytes();
    let terminal = budget.finalize_at(None, Instant::now());
    assert!(terminal.consumption().peak_memory_bytes >= reserved_at_terminal);
    release_tx.send(()).unwrap();
    let failure = worker.join().unwrap().unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::Cancelled);
    assert_eq!(runtime.snapshot().owners[0], 0);
    assert_eq!(budget.host_memory_bytes(), reserved_at_terminal);
    runtime.retire().unwrap();
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn same_ledger_finalization_waits_for_owner_publication() {
    use std::sync::mpsc;
    use std::time::Duration;

    let runtime = runtime();
    let budget = runtime.inner.budget.clone();
    let worker_runtime = runtime.clone();
    let (held_tx, held_rx) = mpsc::sync_channel(0);
    let (release_tx, release_rx) = mpsc::sync_channel(0);
    let worker = std::thread::spawn(move || {
        let mut state = worker_runtime.inner.state.lock().unwrap();
        worker_runtime.register_locked_with_hook(&mut state, OwnerKind::Task, None, |step| {
            if step == AdmissionStep::HoldingPublicationGuard {
                held_tx.send(()).unwrap();
                release_rx.recv_timeout(Duration::from_secs(5)).unwrap();
            }
        })
    });
    held_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    let close_budget = budget.clone();
    let (observed_tx, observed_rx) = mpsc::sync_channel(0);
    let (done_tx, done_rx) = mpsc::sync_channel(0);
    let closer = std::thread::spawn(move || {
        observed_tx
            .send(close_budget.test_accounting_is_locked())
            .unwrap();
        let _ = close_budget.finalize_at(None, Instant::now());
        done_tx.send(()).unwrap();
    });
    let observed_locked = observed_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    let early = done_rx.recv_timeout(Duration::from_millis(100));
    let finished_early = early.is_ok();
    // Release the worker before asserting, including on a failed control.
    release_tx.send(()).unwrap();
    let owner = worker.join().unwrap().unwrap();
    if !finished_early {
        done_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    }
    closer.join().unwrap();
    assert!(observed_locked);
    assert!(matches!(early, Err(mpsc::RecvTimeoutError::Timeout)));
    assert_eq!(runtime.snapshot().owners[0], 1);
    drop(owner);
    runtime.retire().unwrap();
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn same_ledger_cancellation_before_owner_write_refuses_publication() {
    // The atomic closed-flag store does not take accounting; this control
    // uses a no-op terminal probe.
    use std::sync::mpsc;
    use std::time::Duration;

    let runtime = runtime();
    let budget = runtime.inner.budget.clone();
    let original = budget.host_memory_bytes();
    let worker_runtime = runtime.clone();
    let (held_tx, held_rx) = mpsc::sync_channel(0);
    let (release_tx, release_rx) = mpsc::sync_channel(0);
    let worker = std::thread::spawn(move || {
        let mut state = worker_runtime.inner.state.lock().unwrap();
        worker_runtime.register_locked_with_hook(&mut state, OwnerKind::Task, None, |step| {
            if step == AdmissionStep::HoldingPublicationGuard {
                held_tx.send(()).unwrap();
                release_rx.recv_timeout(Duration::from_secs(5)).unwrap();
            }
        })
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
    release_tx.send(()).unwrap();
    let owner = worker.join().unwrap();
    if !was_nonblocking {
        done_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    }
    closer.join().unwrap();
    assert!(was_nonblocking);
    assert_eq!(owner.unwrap_err().code, PlatformErrorCode::Cancelled);
    assert_eq!(runtime.snapshot().owners[0], 0);
    let state = runtime.inner.state.lock().unwrap();
    assert_eq!(state.next_id, 1);
    assert!(state
        .slab
        .as_ref()
        .unwrap()
        .records
        .iter()
        .all(Option::is_none));
    drop(state);
    assert!(budget.host_memory_bytes() > original);
    runtime.retire().unwrap();
    assert_eq!(budget.host_memory_bytes(), original);
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn same_ledger_cancellation_rolls_back_hidden_owner_write() {
    use std::sync::mpsc;
    use std::time::Duration;

    let runtime = runtime();
    let task = runtime.register(OwnerKind::Task, None).unwrap();
    let wake = runtime.park(task.token()).unwrap();
    let before = runtime.snapshot();
    assert_eq!(before.phase, RuntimePhase::Waiting);
    let next_id = runtime.inner.state.lock().unwrap().next_id;
    let budget = runtime.inner.budget.clone();
    let worker_runtime = runtime.clone();
    let token = task.token();
    let (held_tx, held_rx) = mpsc::sync_channel(0);
    let (release_tx, release_rx) = mpsc::sync_channel(0);
    let worker = std::thread::spawn(move || {
        let mut state = worker_runtime.inner.state.lock().unwrap();
        worker_runtime.register_locked_with_hook(
            &mut state,
            OwnerKind::Native,
            Some(token),
            |step| {
                if step == AdmissionStep::TentativePublication {
                    held_tx.send(()).unwrap();
                    release_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                }
            },
        )
    });
    held_rx.recv_timeout(Duration::from_secs(3)).unwrap();
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
    release_tx.send(()).unwrap();
    let result = worker.join().unwrap();
    if !signalled {
        done_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    }
    closer.join().unwrap();
    assert!(state_hidden && accounting_held && signalled);
    assert_eq!(result.unwrap_err().code, PlatformErrorCode::Cancelled);
    let after = runtime.snapshot();
    assert_eq!(after.phase, RuntimePhase::Cancelling);
    assert_eq!(after.owners, before.owners);
    assert_eq!(after.parked_tasks, before.parked_tasks);
    assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
    let state = runtime.inner.state.lock().unwrap();
    assert_eq!(state.next_id, next_id);
    assert_eq!(
        state
            .slab
            .as_ref()
            .unwrap()
            .records
            .iter()
            .flatten()
            .count(),
        1
    );
    assert!(runtime.record(&state, task.token()).unwrap().parked);
    drop(state);
    drop(wake);
    drop(task);
    runtime.retire().unwrap();
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn same_ledger_cancellation_after_owner_commit_keeps_owner_charged() {
    use std::sync::mpsc;
    use std::time::Duration;

    struct Probe(mpsc::Sender<std::thread::ThreadId>);
    impl crate::BudgetCancellationProbe for Probe {
        fn is_cancelled(&self) -> bool {
            false
        }
        fn cancelled(&self) -> crate::BoxFuture<'_, ()> {
            Box::pin(std::future::pending())
        }
        fn mark_terminal(&self) {
            self.0.send(std::thread::current().id()).unwrap();
        }
    }

    let (signal_tx, signal_rx) = mpsc::channel();
    let runtime = runtime_with_probe(Arc::new(Probe(signal_tx)));
    let budget = runtime.inner.budget.clone();
    let original = budget.host_memory_bytes();
    let worker_runtime = runtime.clone();
    let (held_tx, held_rx) = mpsc::sync_channel(0);
    let (release_tx, release_rx) = mpsc::sync_channel(0);
    let worker = std::thread::spawn(move || {
        let mut state = worker_runtime.inner.state.lock().unwrap();
        worker_runtime.register_locked_with_hook(&mut state, OwnerKind::Task, None, |step| {
            if step == AdmissionStep::CommittedPublication {
                held_tx.send(()).unwrap();
                release_rx.recv_timeout(Duration::from_secs(5)).unwrap();
            }
        })
    });
    held_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    let state_hidden = matches!(
        runtime.inner.state.try_lock(),
        Err(std::sync::TryLockError::WouldBlock)
    );
    let accounting_held = budget.test_accounting_is_locked();
    let close_budget = budget.clone();
    let (cancel_tx, cancel_rx) = mpsc::sync_channel(0);
    let closer = std::thread::spawn(move || {
        let thread = std::thread::current().id();
        close_budget.cancel_descendants().unwrap();
        cancel_tx.send(thread).unwrap();
    });
    let cancel_thread = cancel_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    let signal_thread = signal_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    let finalize_budget = budget.clone();
    let (started_tx, started_rx) = mpsc::sync_channel(0);
    let (done_tx, done_rx) = mpsc::sync_channel(0);
    let finalizer = std::thread::spawn(move || {
        started_tx.send(()).unwrap();
        let finalization = finalize_budget.finalize_at(None, Instant::now());
        done_tx
            .send(finalization.consumption().peak_memory_bytes)
            .unwrap();
    });
    started_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    let early = done_rx.recv_timeout(Duration::from_millis(100));
    let finalized_early = early.is_ok();
    release_tx.send(()).unwrap();
    let owner = worker.join().unwrap().unwrap();
    let terminal_peak = match early {
        Ok(peak) => peak,
        Err(_) => done_rx.recv_timeout(Duration::from_secs(3)).unwrap(),
    };
    closer.join().unwrap();
    finalizer.join().unwrap();
    assert!(state_hidden && accounting_held);
    assert_eq!(signal_thread, cancel_thread);
    assert!(!finalized_early);
    assert_eq!(runtime.snapshot().owners[0], 1);
    let occupied = budget.host_memory_bytes();
    assert!(occupied > original && terminal_peak >= occupied);
    drop(owner);
    assert_eq!(budget.host_memory_bytes(), occupied);
    runtime.retire().unwrap();
    assert_eq!(budget.host_memory_bytes(), original);
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn ancestor_closure_before_owner_park_wake_commit_refuses_publication() {
    use std::sync::mpsc;
    use std::time::Duration;

    #[derive(Clone, Copy, Debug)]
    enum Operation {
        Owner,
        Park,
        Wake,
    }
    let mut outcomes = Vec::new();
    for finalize in [false, true] {
        for operation in [Operation::Owner, Operation::Park, Operation::Wake] {
            let (parent, child, runtime) = child_runtime();
            let owner = runtime.register(OwnerKind::Task, None).unwrap();
            let token = owner.token();
            let wake = if matches!(operation, Operation::Wake) {
                Some(runtime.park(token).unwrap())
            } else {
                None
            };
            let before = runtime.snapshot();
            let worker_runtime = runtime.clone();
            let (held_tx, held_rx) = mpsc::sync_channel(0);
            let (resume_tx, resume_rx) = mpsc::sync_channel(0);
            let worker = std::thread::spawn(move || match operation {
                Operation::Owner => {
                    let mut state = worker_runtime.inner.state.lock().unwrap();
                    let result = worker_runtime.register_locked_with_hook(
                        &mut state,
                        OwnerKind::Native,
                        Some(token),
                        |step| {
                            if step == AdmissionStep::TentativePublication {
                                held_tx.send(()).unwrap();
                                resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                            }
                        },
                    );
                    drop(state);
                    result.is_ok()
                }
                Operation::Park | Operation::Wake => {
                    let hook = |step| {
                        if step == ReadinessStep::Tentative {
                            held_tx.send(()).unwrap();
                            resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                        }
                    };
                    if matches!(operation, Operation::Park) {
                        worker_runtime.park_with_hooks(token, || {}, hook).is_ok()
                    } else {
                        wake.unwrap().wake_with_hooks(|| {}, hook)
                    }
                }
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
            let published = worker.join().unwrap();
            if !completed {
                done_rx.recv_timeout(Duration::from_secs(3)).unwrap();
            }
            closer.join().unwrap();
            let after = runtime.snapshot();
            outcomes.push((operation, finalize, completed, published, before, after));
            drop(owner);
            runtime.retire().unwrap();
            drop(runtime);
            let _ = child.finish(None, Instant::now());
            assert_eq!(parent.descendant_snapshot().unwrap().live_descendants, 0);
        }
    }
    for (operation, finalize, completed, published, before, after) in outcomes {
        assert!(completed);
        assert!(
            !published,
            "{operation:?} finalize={finalize} published after ancestor closure"
        );
        assert_eq!(after.phase, RuntimePhase::Cancelling);
        assert_eq!(after.owners, before.owners);
        assert_eq!(after.parked_tasks, before.parked_tasks);
        assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
        assert_eq!(after.stale_wakes, before.stale_wakes);
    }
}

#[test]
fn ancestor_closure_after_owner_commit_keeps_original_capacity() {
    use std::sync::mpsc;
    use std::time::Duration;

    struct Probe(mpsc::Sender<std::thread::ThreadId>);
    impl crate::BudgetCancellationProbe for Probe {
        fn is_cancelled(&self) -> bool {
            false
        }
        fn cancelled(&self) -> crate::BoxFuture<'_, ()> {
            Box::pin(std::future::pending())
        }
        fn mark_terminal(&self) {
            self.0.send(std::thread::current().id()).unwrap();
        }
    }

    for finalize in [false, true] {
        let (signal_tx, signal_rx) = mpsc::channel();
        let (parent, child, runtime) =
            child_runtime_with_probes(Arc::new(Probe(signal_tx)), Arc::new(Signal));
        let task = runtime.register(OwnerKind::Task, None).unwrap();
        let token = task.token();
        let before = runtime.snapshot();
        let reserved = parent.descendant_snapshot().unwrap().reserved_memory_bytes;
        let worker_runtime = runtime.clone();
        let (held_tx, held_rx) = mpsc::sync_channel(0);
        let (resume_tx, resume_rx) = mpsc::sync_channel(0);
        let worker = std::thread::spawn(move || {
            let mut state = worker_runtime.inner.state.lock().unwrap();
            worker_runtime.register_locked_with_hook(
                &mut state,
                OwnerKind::Native,
                Some(token),
                |step| {
                    if step == AdmissionStep::CommittedPublication {
                        held_tx.send(()).unwrap();
                        resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                    }
                },
            )
        });
        held_rx.recv_timeout(Duration::from_secs(3)).unwrap();
        let hidden = matches!(
            runtime.inner.state.try_lock(),
            Err(std::sync::TryLockError::WouldBlock)
        );
        let guarded = child.accounting().test_accounting_is_locked();
        let close_parent = parent.clone();
        let (done_tx, done_rx) = mpsc::sync_channel(0);
        let closer = std::thread::spawn(move || {
            let thread = std::thread::current().id();
            if finalize {
                let _ = close_parent.finalize_at(None, Instant::now());
            } else {
                close_parent.cancel_descendants().unwrap();
            }
            done_tx.send(thread).unwrap();
        });
        let terminal_received = done_rx.recv_timeout(Duration::from_secs(3));
        let completed = terminal_received.is_ok();
        let signal = signal_rx.recv_timeout(Duration::from_secs(3));
        resume_tx.send(()).unwrap();
        let accepted = worker.join().unwrap().unwrap();
        let close_thread = match terminal_received {
            Ok(thread) => thread,
            Err(_) => done_rx.recv_timeout(Duration::from_secs(3)).unwrap(),
        };
        closer.join().unwrap();
        assert!(hidden && guarded && completed);
        assert_eq!(signal.unwrap(), close_thread);
        let after = runtime.snapshot();
        assert_eq!(after.owners[6], before.owners[6] + 1);
        assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
        assert_eq!(
            parent.descendant_snapshot().unwrap().reserved_memory_bytes,
            reserved
        );
        drop(accepted);
        drop(task);
        runtime.retire().unwrap();
        drop(runtime);
        let _ = child.finish(None, Instant::now());
        assert_eq!(parent.descendant_snapshot().unwrap().live_descendants, 0);
        assert_eq!(
            parent.descendant_snapshot().unwrap().reserved_memory_bytes,
            0
        );
    }
}

#[test]
fn ancestor_accounting_lock_does_not_block_prepaid_owner_publication() {
    use std::sync::mpsc;
    use std::time::Duration;

    let (parent, child, runtime) = child_runtime();
    let task = runtime.register(OwnerKind::Task, None).unwrap();
    let token = task.token();
    let locked_parent = parent.clone();
    let (held_tx, held_rx) = mpsc::sync_channel(0);
    let (release_tx, release_rx) = mpsc::sync_channel(0);
    let holder = std::thread::spawn(move || {
        locked_parent.with_test_accounting_lock(|| {
            held_tx.send(()).unwrap();
            release_rx.recv_timeout(Duration::from_secs(5)).unwrap();
        });
    });
    held_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    let worker_runtime = runtime.clone();
    let (done_tx, done_rx) = mpsc::sync_channel(0);
    let worker = std::thread::spawn(move || {
        done_tx
            .send(worker_runtime.register(OwnerKind::Native, Some(token)))
            .unwrap();
    });
    let early = done_rx.recv_timeout(Duration::from_secs(3));
    let finished_while_locked = early.is_ok();
    release_tx.send(()).unwrap();
    let accepted = match early {
        Ok(result) => result.unwrap(),
        Err(_) => done_rx
            .recv_timeout(Duration::from_secs(3))
            .unwrap()
            .unwrap(),
    };
    holder.join().unwrap();
    worker.join().unwrap();
    assert!(finished_while_locked);
    drop(accepted);
    drop(task);
    runtime.retire().unwrap();
    drop(runtime);
    let _ = child.finish(None, Instant::now());
    assert_eq!(parent.descendant_snapshot().unwrap().live_descendants, 0);
}

#[test]
fn external_probe_cancellation_is_not_a_ledger_terminal_signal() {
    use std::sync::atomic::{AtomicBool, Ordering};

    struct ExternalSignal {
        cancelled: AtomicBool,
        changed: tokio::sync::watch::Sender<bool>,
    }
    impl crate::BudgetCancellationProbe for ExternalSignal {
        fn is_cancelled(&self) -> bool {
            self.cancelled.load(Ordering::Acquire)
        }
        fn cancelled(&self) -> crate::BoxFuture<'_, ()> {
            let mut changed = self.changed.subscribe();
            Box::pin(async move {
                loop {
                    if *changed.borrow() {
                        return;
                    }
                    if changed.changed().await.is_err() {
                        return;
                    }
                }
            })
        }
        fn mark_terminal(&self) {
            self.changed.send_replace(true);
        }
    }

    // Known boundary: a separately changing external probe is checked before
    // locking, but is deliberately not called under the runtime lock.
    let signal = Arc::new(ExternalSignal {
        cancelled: AtomicBool::new(false),
        changed: tokio::sync::watch::channel(false).0,
    });
    let runtime = runtime_with_probe(signal.clone());
    let owner = runtime
        .register_after_live_check(OwnerKind::Task, None, || {
            signal.cancelled.store(true, Ordering::Release);
            signal.changed.send_replace(true);
        })
        .unwrap();
    assert_eq!(runtime.snapshot().owners[0], 1);
    drop(owner);
    runtime.retire().unwrap();
}

#[test]
fn stale_continuation_keeps_its_error_when_original_budget_is_cancelled_after_check() {
    for from_task in [false, true] {
        let runtime = runtime();
        let task = runtime.register(OwnerKind::Task, None).unwrap();
        let token = task.token();
        drop(task);
        let budget = runtime.inner.budget.clone();
        let after_check = || budget.cancel_descendants().unwrap();
        let result = if from_task {
            runtime.register_from_task_after_live_check(OwnerKind::Native, token, after_check)
        } else {
            runtime.register_after_live_check(OwnerKind::Native, Some(token), after_check)
        };
        let failure = result.unwrap_err();
        assert_eq!(failure.code, PlatformErrorCode::InvalidArgument);
        assert_eq!(
            failure.message,
            if from_task {
                "runtime-task-continuation"
            } else {
                "runtime-token"
            }
        );
        assert_eq!(runtime.snapshot().owners, [0; 7]);
        runtime.retire().unwrap();
    }
}

#[test]
fn ancestor_stop_after_the_live_check_fences_admission_park_and_wake() {
    for finalize in [false, true] {
        for action in 0..3 {
            let (parent, child, runtime) = child_runtime();
            let task = runtime.register(OwnerKind::Task, None).unwrap();
            let wake = (action == 2).then(|| runtime.park(task.token()).unwrap());
            let before = runtime.snapshot();
            let stop_parent = || {
                if finalize {
                    let _ = parent.finalize_at(None, Instant::now());
                } else {
                    parent.cancel_descendants().unwrap();
                }
            };
            match action {
                0 => assert_eq!(
                    runtime
                        .register_after_live_check(
                            OwnerKind::Native,
                            Some(task.token()),
                            stop_parent
                        )
                        .unwrap_err()
                        .code,
                    PlatformErrorCode::Cancelled
                ),
                1 => assert_eq!(
                    runtime
                        .park_with_after_live_check(task.token(), stop_parent)
                        .unwrap_err()
                        .code,
                    PlatformErrorCode::Cancelled
                ),
                _ => assert!(!wake.unwrap().wake_with_after_live_check(stop_parent)),
            }
            let after = runtime.snapshot();
            assert_eq!(after.owners, before.owners);
            assert_eq!(after.parked_tasks, before.parked_tasks);
            assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
            assert_eq!(after.phase, RuntimePhase::Cancelling);
            drop(task);
            runtime.retire().unwrap();
            drop(runtime);
            let _ = child.finish(None, Instant::now());
            assert_eq!(parent.descendant_snapshot().unwrap().live_descendants, 0);
        }
    }
}

#[tokio::test]
async fn ancestor_terminal_wakes_child_waiters_without_a_new_child_callback() {
    use std::future::Future;
    use std::task::Poll;
    use std::time::Duration;

    struct WatchSignal(tokio::sync::watch::Sender<bool>);
    impl crate::BudgetCancellationProbe for WatchSignal {
        fn is_cancelled(&self) -> bool {
            false
        }
        fn cancelled(&self) -> crate::BoxFuture<'_, ()> {
            let mut signal = self.0.subscribe();
            Box::pin(async move {
                loop {
                    if *signal.borrow() {
                        return;
                    }
                    if signal.changed().await.is_err() {
                        return;
                    }
                }
            })
        }
        fn mark_terminal(&self) {
            self.0.send_replace(true);
        }
    }
    let parent_signal = Arc::new(WatchSignal(tokio::sync::watch::channel(false).0));
    let child_signal = Arc::new(WatchSignal(tokio::sync::watch::channel(false).0));
    let (parent, child, runtime) =
        child_runtime_with_probes(parent_signal.clone(), child_signal.clone());
    let task = runtime.register(OwnerKind::Task, None).unwrap();
    let mut cancelled = Box::pin(child.accounting().descendant_cancelled());
    std::future::poll_fn(|context| {
        assert!(cancelled.as_mut().poll(context).is_pending());
        Poll::Ready(())
    })
    .await;
    let result = runtime.register_after_live_check(OwnerKind::Native, Some(task.token()), || {
        parent.cancel_descendants().unwrap();
    });
    assert_eq!(result.unwrap_err().code, PlatformErrorCode::Cancelled);
    assert_eq!(runtime.snapshot().phase, RuntimePhase::Cancelling);
    assert!(*parent_signal.0.borrow());
    assert!(!*child_signal.0.borrow());
    tokio::time::timeout(Duration::from_secs(2), cancelled)
        .await
        .unwrap();
    drop(task);
    runtime.retire().unwrap();
    drop(runtime);
    let _ = child.finish(None, Instant::now());
}

#[test]
fn deadline_expiring_after_the_live_check_fences_park_and_wake() {
    use std::sync::mpsc;
    use std::time::Duration;

    let runtime = runtime();
    let runnable = runtime.register(OwnerKind::Task, None).unwrap();
    let parked = runtime.register(OwnerKind::Task, None).unwrap();
    let wake = runtime.park(parked.token()).unwrap();
    let before = runtime.snapshot();
    let deadline = runtime.inner.budget.deadline().monotonic().unwrap();
    let (checked_tx, checked_rx) = mpsc::channel();
    let (park_resume, park_rx) = mpsc::sync_channel(0);
    let (wake_resume, wake_rx) = mpsc::sync_channel(0);
    let worker_runtime = runtime.clone();
    let token = runnable.token();
    let park_checked = checked_tx.clone();
    let park_worker = std::thread::spawn(move || {
        worker_runtime.park_with_after_live_check(token, || {
            park_checked.send(()).unwrap();
            park_rx.recv_timeout(Duration::from_secs(10)).unwrap();
        })
    });
    let wake_worker = std::thread::spawn(move || {
        wake.wake_with_after_live_check(|| {
            checked_tx.send(()).unwrap();
            wake_rx.recv_timeout(Duration::from_secs(10)).unwrap();
        })
    });
    for _ in 0..2 {
        checked_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    }
    assert!(Instant::now() < deadline);
    std::thread::sleep(
        deadline.saturating_duration_since(Instant::now()) + Duration::from_millis(5),
    );
    assert!(Instant::now() >= deadline);
    park_resume.send(()).unwrap();
    wake_resume.send(()).unwrap();
    assert_eq!(
        park_worker.join().unwrap().unwrap_err().code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert!(!wake_worker.join().unwrap());
    let after = runtime.snapshot();
    assert_eq!(after.owners, before.owners);
    assert_eq!(after.parked_tasks, before.parked_tasks);
    assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
    assert_eq!(after.phase, before.phase);
    drop(runnable);
    drop(parked);
    runtime.retire().unwrap();
}

#[test]
fn original_cancellation_after_the_live_check_does_not_admit_owners() {
    for from_task in [false, true] {
        let runtime = runtime();
        let task = runtime.register(OwnerKind::Task, None).unwrap();
        let before = runtime.snapshot();
        let budget = runtime.inner.budget.clone();
        let after_check = || budget.cancel_descendants().unwrap();
        let result = if from_task {
            runtime.register_from_task_after_live_check(
                OwnerKind::Native,
                task.token(),
                after_check,
            )
        } else {
            runtime.register_after_live_check(OwnerKind::Task, None, after_check)
        };
        assert_eq!(result.unwrap_err().code, PlatformErrorCode::Cancelled);
        let after = runtime.snapshot();
        assert_eq!(after.owners, before.owners);
        assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
        assert_eq!(after.admission_failures, before.admission_failures + 1);
        drop(task);
        runtime.retire().unwrap();
    }
}

#[test]
fn deadline_expiring_after_the_live_check_does_not_admit_owners() {
    use std::sync::mpsc;
    use std::time::Duration;

    let runtime = runtime();
    let task = runtime.register(OwnerKind::Task, None).unwrap();
    let token = task.token();
    let deadline = runtime.inner.budget.deadline().monotonic().unwrap();
    let before = runtime.snapshot();
    let (checked_tx, checked_rx) = mpsc::channel();
    let mut workers = Vec::new();
    for from_task in [false, true] {
        let worker_runtime = runtime.clone();
        let checked = checked_tx.clone();
        let (resume_tx, resume_rx) = mpsc::sync_channel(0);
        let worker = std::thread::spawn(move || {
            let after_check = || {
                checked.send(()).unwrap();
                resume_rx.recv_timeout(Duration::from_secs(10)).unwrap();
            };
            if from_task {
                worker_runtime.register_from_task_after_live_check(
                    OwnerKind::Native,
                    token,
                    after_check,
                )
            } else {
                worker_runtime.register_after_live_check(OwnerKind::Task, None, after_check)
            }
        });
        workers.push((resume_tx, worker));
    }
    for _ in 0..workers.len() {
        checked_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    }
    assert!(Instant::now() < deadline);
    std::thread::sleep(
        deadline.saturating_duration_since(Instant::now()) + Duration::from_millis(5),
    );
    assert!(Instant::now() >= deadline);
    for (resume, _) in &workers {
        resume.send(()).unwrap();
    }
    for (_, worker) in workers {
        assert_eq!(
            worker.join().unwrap().unwrap_err().code,
            PlatformErrorCode::DeadlineExceeded
        );
    }
    let after = runtime.snapshot();
    assert_eq!(after.owners, before.owners);
    assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
    assert_eq!(after.admission_failures, before.admission_failures + 2);
    drop(task);
    runtime.retire().unwrap();
}

#[test]
fn lazy_path_allocates_no_records_and_accepted_owners_share_finite_limits() {
    let runtime = runtime();
    let metadata = runtime.snapshot().host_memory_bytes;
    assert!(metadata > 0);
    assert!(runtime.inner.state.lock().unwrap().slab.is_none());
    let first = runtime.register(OwnerKind::Task, None).unwrap();
    let second = runtime
        .register(OwnerKind::ManagedIdleWorker, None)
        .unwrap();
    assert!(runtime.register(OwnerKind::Task, None).is_err());
    let memory = runtime.snapshot().host_memory_bytes;
    assert!(memory > 0);
    drop(first);
    assert_eq!(runtime.snapshot().host_memory_bytes, memory);
    drop(second);
    runtime.retire().unwrap();
    assert_eq!(runtime.snapshot().host_memory_bytes, metadata);
    let budget = runtime.inner.budget.clone();
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn record_backing_and_bookkeeping_are_reserved_before_owner_admission() {
    let runtime = runtime();
    let budget = runtime.inner.budget.clone();
    let original = budget.host_memory_bytes();
    let count = runtime.inner.limits.total();
    let bytes = (std::alloc::Layout::array::<Option<Record>>(count)
        .unwrap()
        .size()
        + SLAB_ALLOCATION_BOOKKEEPING) as u64;
    let remaining = budget.remaining_at(Instant::now()).memory_bytes;
    // Leave enough for the record layout alone, but one byte less than the
    // complete modelled backing and its allocator bookkeeping.
    let padding = budget.reserve_host_memory(remaining - bytes + 1).unwrap();
    let reserved = budget.host_memory_bytes();
    let reservations = budget.outstanding_reservations();
    let failure = runtime.register(OwnerKind::Task, None).unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(budget.host_memory_bytes(), reserved);
    assert_eq!(budget.outstanding_reservations(), reservations);
    let state = runtime.inner.state.lock().unwrap();
    assert!(state.slab.is_none());
    assert_eq!(state.owners, [0; 7]);
    drop(state);

    drop(padding);
    let owner = runtime.register(OwnerKind::Task, None).unwrap();
    assert_eq!(budget.host_memory_bytes(), original + bytes);
    let state = runtime.inner.state.lock().unwrap();
    let slab = state.slab.as_ref().unwrap();
    assert_eq!(slab.records.capacity(), count);
    drop(state);
    drop(owner);
    assert_eq!(budget.host_memory_bytes(), original + bytes);
    runtime.retire().unwrap();
    assert_eq!(budget.host_memory_bytes(), original);
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn actual_owner_refusals_name_only_the_original_bucket_without_refunding_live_owners() {
    use crate::diagnostic::{ActivationDiagnostic, DiagnosticReason as R};
    for (kind, reason) in [
        (OwnerKind::Task, R::RuntimeTaskLimit),
        (OwnerKind::ManagedIdleWorker, R::RuntimeTaskLimit),
        (OwnerKind::Executor, R::RuntimeExecutorLimit),
        (OwnerKind::QueuedWork, R::RuntimeQueueLimit),
        (OwnerKind::Wait, R::RuntimeWaitLimit),
        (OwnerKind::Timer, R::RuntimeTimerLimit),
        (OwnerKind::Result, R::RuntimeResultLimit),
        (OwnerKind::Native, R::RuntimeNativeOwnerLimit),
    ] {
        let runtime = runtime();
        let first = runtime.register(kind, None).unwrap();
        let second = runtime.register(kind, None).unwrap();
        let before = runtime.snapshot();
        let failure = runtime.register(kind, None).unwrap_err();
        let observed = ActivationDiagnostic::from_error(&failure).unwrap();
        assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
        assert_eq!(observed.reason, reason);
        assert_eq!(observed.configured_bound, Some(2));
        assert_eq!(observed.calculated_requirement, Some(3));
        assert_eq!(runtime.snapshot().owners, before.owners);
        drop(first);
        drop(second);
        runtime.retire().unwrap();
        assert_eq!(runtime.snapshot().owners, [0; 7]);
    }
}

#[test]
fn actual_native_reservation_refusal_keeps_original_budget_and_does_not_guess_other_dimensions() {
    use crate::diagnostic::{ActivationDiagnostic, DiagnosticReason};
    let runtime = runtime();
    let budget = &runtime.inner.budget;
    let before = budget.host_memory_bytes();
    let limit = budget.granted().memory_bytes;
    let failure = budget.reserve_host_memory(limit + 1).err().unwrap();
    assert!(ActivationDiagnostic::from_error(&failure.to_platform_error()).is_none());
    let observed = ActivationDiagnostic::from_error(&failure.to_host_memory_error()).unwrap();
    assert_eq!(observed.reason, DiagnosticReason::NativeMemoryExhausted);
    assert_eq!(observed.configured_bound, Some(limit));
    assert!(observed.calculated_requirement.unwrap() > limit);
    assert_eq!(budget.host_memory_bytes(), before);
    let fuel = budget
        .consume_cpu_fuel(budget.granted().cpu_fuel + 1)
        .unwrap_err();
    assert!(ActivationDiagnostic::from_error(&fuel.to_host_memory_error()).is_none());
}

#[test]
fn continuations_require_live_original_generation_before_any_admission() {
    let foreign = runtime();
    let runtime = runtime();
    let foreign_owner = foreign.register(OwnerKind::Task, None).unwrap();
    let metadata = runtime.snapshot().host_memory_bytes;
    let reject = |token| {
        let before = runtime.snapshot();
        let failure = runtime
            .register(OwnerKind::Result, Some(token))
            .unwrap_err();
        assert_eq!(failure.code, PlatformErrorCode::InvalidArgument);
        assert_eq!(failure.message, "runtime-token");
        let after = runtime.snapshot();
        assert_eq!(after.owners, before.owners);
        assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
        assert_eq!(after.admission_failures, before.admission_failures + 1);
    };
    reject(foreign_owner.token());
    assert!(runtime.inner.state.lock().unwrap().slab.is_none());
    assert_eq!(runtime.snapshot().host_memory_bytes, metadata);

    let settled = runtime.register(OwnerKind::Task, None).unwrap();
    let stale = settled.token();
    drop(settled);
    let live = runtime.register(OwnerKind::Task, None).unwrap();
    reject(stale);
    reject(RuntimeToken {
        generation: live.token().generation,
        id: u64::MAX,
    });
    let before = runtime.snapshot().host_memory_bytes;
    let failure = RuntimeTimer::new(&runtime, Instant::now(), None, Some(stale)).unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::InvalidArgument);
    assert_eq!(runtime.snapshot().host_memory_bytes, before);

    let result = runtime
        .register(OwnerKind::Result, Some(live.token()))
        .unwrap();
    drop(result);
    runtime.begin_drain();
    reject(stale);
    reject(foreign_owner.token());
    let result = runtime
        .register(OwnerKind::Result, Some(live.token()))
        .unwrap();
    drop(result);
    drop(live);
    runtime.retire().unwrap();
    drop(foreign_owner);
    foreign.retire().unwrap();
}

#[test]
fn close_allows_bounded_live_continuations_and_rejects_independent_work() {
    let runtime = runtime();
    let task = runtime.register(OwnerKind::Task, None).unwrap();
    let token = task.token();
    runtime.close();
    runtime.begin_drain();
    assert!(runtime.register(OwnerKind::Task, None).is_err());
    let result = runtime.register(OwnerKind::Result, Some(token)).unwrap();
    let owners = runtime.snapshot().owners;
    let failure = runtime.retire().unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::Internal);
    assert_eq!(failure.message, "runtime-lifecycle-unproven");
    assert!(!failure.retryable);
    assert!(failure.details.is_empty());
    assert_eq!(runtime.snapshot().owners, owners);
    drop(task);
    assert!(runtime.register(OwnerKind::Result, Some(token)).is_err());
    drop(result);
    runtime.retire().unwrap();
    assert!(runtime.register(OwnerKind::Task, None).is_err());
}

#[test]
fn task_support_admission_checks_original_kind_and_liveness_under_the_same_lock() {
    let foreign = runtime();
    let foreign_task = foreign.register(OwnerKind::Task, None).unwrap();
    let runtime = runtime();
    let wrong_kind = runtime.register(OwnerKind::Result, None).unwrap();
    let task = runtime.register(OwnerKind::Task, None).unwrap();
    let task_token = task.token();
    let reject = |token| {
        let before = runtime.snapshot();
        let failure = runtime
            .register_from_task(OwnerKind::Native, token)
            .unwrap_err();
        assert_eq!(failure.code, PlatformErrorCode::InvalidArgument);
        assert_eq!(failure.message, "runtime-task-continuation");
        let after = runtime.snapshot();
        assert_eq!(after.owners, before.owners);
        assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
        assert_eq!(after.admission_failures, before.admission_failures + 1);
    };
    reject(wrong_kind.token());
    reject(foreign_task.token());
    reject(RuntimeToken {
        generation: task_token.generation,
        id: u64::MAX,
    });
    runtime.begin_drain();
    let native = runtime
        .register_from_task(OwnerKind::Native, task_token)
        .unwrap();
    drop(task);
    reject(task_token);
    drop(native);
    drop(wrong_kind);
    runtime.retire().unwrap();
    drop(foreign_task);
    foreign.retire().unwrap();
}

#[test]
fn waking_a_parked_thread_leaves_runnable_sibling_and_fences_reused_slots() {
    let runtime = runtime();
    let first = runtime.register(OwnerKind::Task, None).unwrap();
    let second = runtime.register(OwnerKind::Task, None).unwrap();
    let wake = runtime.park(first.token()).unwrap();
    assert_eq!(runtime.snapshot().phase, RuntimePhase::Running);
    assert_eq!(runtime.snapshot().parked_tasks, 1);
    assert!(wake.wake());
    let stale = runtime.park(first.token()).unwrap();
    drop(first);
    let replacement = runtime.register(OwnerKind::Task, None).unwrap();
    assert!(!stale.wake());
    assert_eq!(runtime.snapshot().stale_wakes, 1);
    runtime.cancel();
    assert!(!wake.wake());
    assert!(runtime.retire().is_err());
    drop(second);
    drop(replacement);
    runtime.retire().unwrap();
}

#[test]
fn same_ledger_closure_after_readiness_check_refuses_park_and_wake() {
    use std::sync::mpsc;
    use std::time::Duration;

    let mut outcomes = Vec::new();
    for finalize in [false, true] {
        for park in [false, true] {
            let runtime = runtime();
            let owner = runtime.register(OwnerKind::Task, None).unwrap();
            let token = owner.token();
            let wake = if park {
                None
            } else {
                Some(runtime.park(token).unwrap())
            };
            let before = runtime.snapshot();
            let budget = runtime.inner.budget.clone();
            let worker_runtime = runtime.clone();
            let (checked_tx, checked_rx) = mpsc::sync_channel(0);
            let (resume_tx, resume_rx) = mpsc::sync_channel(0);
            let worker = std::thread::spawn(move || {
                let hook = |step| {
                    if step == ReadinessStep::Checked {
                        checked_tx.send(()).unwrap();
                        resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                    }
                };
                if park {
                    worker_runtime.park_with_hooks(token, || {}, hook).is_ok()
                } else {
                    wake.unwrap().wake_with_hooks(|| {}, hook)
                }
            });
            checked_rx.recv_timeout(Duration::from_secs(3)).unwrap();
            let close_budget = budget.clone();
            let (done_tx, done_rx) = mpsc::sync_channel(0);
            let closer = std::thread::spawn(move || {
                if finalize {
                    let _ = close_budget.finalize_at(None, Instant::now());
                } else {
                    close_budget.cancel_descendants().unwrap();
                }
                done_tx.send(()).unwrap();
            });
            let terminal_received = done_rx.recv_timeout(Duration::from_secs(3));
            let closed_before_resume = terminal_received.is_ok();
            resume_tx.send(()).unwrap();
            let published = worker.join().unwrap();
            if !closed_before_resume {
                done_rx.recv_timeout(Duration::from_secs(3)).unwrap();
            }
            closer.join().unwrap();
            let after = runtime.snapshot();
            outcomes.push((
                park,
                finalize,
                closed_before_resume,
                published,
                before,
                after,
            ));
            drop(owner);
            runtime.retire().unwrap();
            drop(runtime);
            assert_eq!(budget.host_memory_bytes(), 0);
        }
    }
    for (park, finalize, closed, published, before, after) in outcomes {
        assert!(closed, "closure must complete before publication resumes");
        assert!(
            !published,
            "park={park} finalize={finalize} published after closure"
        );
        assert_eq!(after.phase, RuntimePhase::Cancelling);
        assert_eq!(after.parked_tasks, before.parked_tasks);
        assert_eq!(after.owners, before.owners);
        assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
        assert_eq!(after.stale_wakes, before.stale_wakes);
    }
}

#[test]
fn same_ledger_cancellation_restores_hidden_park_and_wake() {
    use std::sync::mpsc;
    use std::time::Duration;

    for park in [false, true] {
        for already_set in [false, true] {
            let runtime = runtime();
            let owner = runtime.register(OwnerKind::Task, None).unwrap();
            let token = owner.token();
            let wake = if !park || already_set {
                let wake = runtime.park(token).unwrap();
                if !park && already_set {
                    assert!(wake.wake());
                }
                Some(wake)
            } else {
                None
            };
            let before = runtime.snapshot();
            let budget = runtime.inner.budget.clone();
            let worker_runtime = runtime.clone();
            let (held_tx, held_rx) = mpsc::sync_channel(0);
            let (resume_tx, resume_rx) = mpsc::sync_channel(0);
            let worker = std::thread::spawn(move || {
                let hook = |step| {
                    if step == ReadinessStep::Tentative {
                        held_tx.send(()).unwrap();
                        resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                    }
                };
                if park {
                    worker_runtime.park_with_hooks(token, || {}, hook).is_ok()
                } else {
                    wake.unwrap().wake_with_hooks(|| {}, hook)
                }
            });
            held_rx.recv_timeout(Duration::from_secs(3)).unwrap();
            let hidden = matches!(
                runtime.inner.state.try_lock(),
                Err(std::sync::TryLockError::WouldBlock)
            );
            let guarded = budget.test_accounting_is_locked();
            let close_budget = budget.clone();
            let (done_tx, done_rx) = mpsc::sync_channel(0);
            let closer = std::thread::spawn(move || {
                close_budget.cancel_descendants().unwrap();
                done_tx.send(()).unwrap();
            });
            let cancelled = done_rx.recv_timeout(Duration::from_secs(3));
            let signalled = cancelled.is_ok();
            resume_tx.send(()).unwrap();
            let result = worker.join().unwrap();
            if !signalled {
                done_rx.recv_timeout(Duration::from_secs(3)).unwrap();
            }
            closer.join().unwrap();
            assert!(hidden && guarded && signalled);
            assert!(!result, "park={park} already_set={already_set}");
            let after = runtime.snapshot();
            assert_eq!(after.phase, RuntimePhase::Cancelling);
            assert_eq!(after.parked_tasks, before.parked_tasks);
            assert_eq!(after.owners, before.owners);
            assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
            assert_eq!(after.stale_wakes, before.stale_wakes);
            drop(owner);
            runtime.retire().unwrap();
            drop(runtime);
            assert_eq!(budget.host_memory_bytes(), 0);
        }
    }
}

#[test]
fn same_ledger_finalization_waits_for_tentative_park_and_wake() {
    use std::sync::mpsc;
    use std::time::Duration;

    for park in [false, true] {
        let runtime = runtime();
        let owner = runtime.register(OwnerKind::Task, None).unwrap();
        let token = owner.token();
        let wake = if park {
            None
        } else {
            Some(runtime.park(token).unwrap())
        };
        let before = runtime.snapshot();
        let budget = runtime.inner.budget.clone();
        let worker_runtime = runtime.clone();
        let (held_tx, held_rx) = mpsc::sync_channel(0);
        let (resume_tx, resume_rx) = mpsc::sync_channel(0);
        let worker = std::thread::spawn(move || {
            let hook = |step| {
                if step == ReadinessStep::Tentative {
                    held_tx.send(()).unwrap();
                    resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                }
            };
            if park {
                worker_runtime.park_with_hooks(token, || {}, hook).is_ok()
            } else {
                wake.unwrap().wake_with_hooks(|| {}, hook)
            }
        });
        held_rx.recv_timeout(Duration::from_secs(3)).unwrap();
        let hidden = matches!(
            runtime.inner.state.try_lock(),
            Err(std::sync::TryLockError::WouldBlock)
        );
        let guarded = budget.test_accounting_is_locked();
        let close_budget = budget.clone();
        let (started_tx, started_rx) = mpsc::sync_channel(0);
        let (done_tx, done_rx) = mpsc::sync_channel(0);
        let closer = std::thread::spawn(move || {
            started_tx.send(()).unwrap();
            let terminal = close_budget.finalize_at(None, Instant::now());
            done_tx
                .send(terminal.consumption().peak_memory_bytes)
                .unwrap();
        });
        started_rx.recv_timeout(Duration::from_secs(3)).unwrap();
        let early = done_rx.recv_timeout(Duration::from_millis(100));
        let finalized_early = early.is_ok();
        resume_tx.send(()).unwrap();
        let result = worker.join().unwrap();
        let terminal_peak = match early {
            Ok(peak) => peak,
            Err(_) => done_rx.recv_timeout(Duration::from_secs(3)).unwrap(),
        };
        closer.join().unwrap();
        assert!(hidden && guarded && !finalized_early && result);
        let after = runtime.snapshot();
        assert_eq!(after.parked_tasks, u32::from(park));
        assert_eq!(after.owners, before.owners);
        assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
        assert_eq!(after.stale_wakes, before.stale_wakes);
        assert!(terminal_peak >= before.host_memory_bytes);
        drop(owner);
        runtime.retire().unwrap();
        drop(runtime);
        assert_eq!(budget.host_memory_bytes(), 0);
    }
}

#[test]
fn same_ledger_cancellation_after_park_and_wake_commit_keeps_owner() {
    use std::sync::mpsc;
    use std::time::Duration;

    struct Probe(mpsc::Sender<std::thread::ThreadId>);
    impl crate::BudgetCancellationProbe for Probe {
        fn is_cancelled(&self) -> bool {
            false
        }
        fn cancelled(&self) -> crate::BoxFuture<'_, ()> {
            Box::pin(std::future::pending())
        }
        fn mark_terminal(&self) {
            self.0.send(std::thread::current().id()).unwrap();
        }
    }

    for park in [false, true] {
        let (signal_tx, signal_rx) = mpsc::channel();
        let runtime = runtime_with_probe(Arc::new(Probe(signal_tx)));
        let owner = runtime.register(OwnerKind::Task, None).unwrap();
        let token = owner.token();
        let wake = if park {
            None
        } else {
            Some(runtime.park(token).unwrap())
        };
        let before = runtime.snapshot();
        let budget = runtime.inner.budget.clone();
        let worker_runtime = runtime.clone();
        let (held_tx, held_rx) = mpsc::sync_channel(0);
        let (resume_tx, resume_rx) = mpsc::sync_channel(0);
        let worker = std::thread::spawn(move || {
            let hook = |step| {
                if step == ReadinessStep::Committed {
                    held_tx.send(()).unwrap();
                    resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                }
            };
            if park {
                worker_runtime.park_with_hooks(token, || {}, hook).is_ok()
            } else {
                wake.unwrap().wake_with_hooks(|| {}, hook)
            }
        });
        held_rx.recv_timeout(Duration::from_secs(3)).unwrap();
        let hidden = matches!(
            runtime.inner.state.try_lock(),
            Err(std::sync::TryLockError::WouldBlock)
        );
        let guarded = budget.test_accounting_is_locked();
        let close_budget = budget.clone();
        let (done_tx, done_rx) = mpsc::sync_channel(0);
        let closer = std::thread::spawn(move || {
            let thread = std::thread::current().id();
            close_budget.cancel_descendants().unwrap();
            done_tx.send(thread).unwrap();
        });
        let cancel_thread = done_rx.recv_timeout(Duration::from_secs(3)).unwrap();
        let signal_thread = signal_rx.recv_timeout(Duration::from_secs(3)).unwrap();
        resume_tx.send(()).unwrap();
        let result = worker.join().unwrap();
        closer.join().unwrap();
        assert!(hidden && guarded && result);
        assert_eq!(signal_thread, cancel_thread);
        let after = runtime.snapshot();
        assert_eq!(after.parked_tasks, u32::from(park));
        assert_eq!(after.owners, before.owners);
        assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
        assert_eq!(after.stale_wakes, before.stale_wakes);
        drop(owner);
        runtime.retire().unwrap();
        drop(runtime);
        assert_eq!(budget.host_memory_bytes(), 0);
    }
}

#[test]
fn park_phase_accounts_for_tasks_and_non_task_owners() {
    let runtime = runtime();
    let task = runtime.register(OwnerKind::Task, None).unwrap();
    let worker = runtime
        .register(OwnerKind::ManagedIdleWorker, None)
        .unwrap();
    let wait = runtime.register(OwnerKind::Wait, None).unwrap();
    let non_task_wake = runtime.park(wait.token()).unwrap();
    assert_eq!(runtime.snapshot().phase, RuntimePhase::Running);
    let task_wake = runtime.park(task.token()).unwrap();
    assert_eq!(runtime.snapshot().phase, RuntimePhase::Running);
    let worker_wake = runtime.park(worker.token()).unwrap();
    assert_eq!(runtime.snapshot().phase, RuntimePhase::Waiting);
    assert!(task_wake.wake());
    assert_eq!(runtime.snapshot().phase, RuntimePhase::Running);
    let task_wake_again = runtime.park(task.token()).unwrap();
    assert_eq!(runtime.snapshot().phase, RuntimePhase::Waiting);
    drop((task_wake_again, worker_wake, task_wake, non_task_wake));
    drop((wait, worker, task));
    runtime.retire().unwrap();
}

// Pause immediately after the same successful liveness check used by the
// public method, then let the cancelling thread win the mutation lock.
#[test]
fn park_refuses_when_cancel_wins_after_the_live_check() {
    let runtime = runtime();
    let owner = runtime.register(OwnerKind::Task, None).unwrap();
    let token = owner.token();
    let before = runtime.snapshot();
    let (checked_tx, checked_rx) = std::sync::mpsc::sync_channel(0);
    let (resume_tx, resume_rx) = std::sync::mpsc::sync_channel(0);
    let worker_runtime = runtime.clone();
    let worker = std::thread::spawn(move || {
        worker_runtime.park_with_after_live_check(token, || {
            checked_tx.send(()).unwrap();
            resume_rx
                .recv_timeout(std::time::Duration::from_secs(5))
                .unwrap();
        })
    });
    checked_rx
        .recv_timeout(std::time::Duration::from_secs(5))
        .unwrap();
    runtime.cancel();
    resume_tx.send(()).unwrap();
    let error = worker.join().unwrap().unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::Cancelled);
    let after = runtime.snapshot();
    assert_eq!(after.phase, RuntimePhase::Cancelling);
    assert_eq!(after.parked_tasks, 0);
    assert_eq!(after.owners, before.owners);
    assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
    drop(owner);
    runtime.retire().unwrap();
}

#[test]
fn wake_refuses_when_cancel_wins_after_the_live_check() {
    let runtime = runtime();
    let owner = runtime.register(OwnerKind::Task, None).unwrap();
    let wake = runtime.park(owner.token()).unwrap();
    let before = runtime.snapshot();
    let (checked_tx, checked_rx) = std::sync::mpsc::sync_channel(0);
    let (resume_tx, resume_rx) = std::sync::mpsc::sync_channel(0);
    let worker = std::thread::spawn(move || {
        wake.wake_with_after_live_check(|| {
            checked_tx.send(()).unwrap();
            resume_rx
                .recv_timeout(std::time::Duration::from_secs(5))
                .unwrap();
        })
    });
    checked_rx
        .recv_timeout(std::time::Duration::from_secs(5))
        .unwrap();
    runtime.cancel();
    resume_tx.send(()).unwrap();
    assert!(!worker.join().unwrap());
    let after = runtime.snapshot();
    assert_eq!(after.phase, RuntimePhase::Cancelling);
    assert_eq!(after.parked_tasks, 1);
    assert_eq!(after.owners, before.owners);
    assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
    assert_eq!(after.stale_wakes, before.stale_wakes);
    drop(owner);
    runtime.retire().unwrap();
}

#[test]
fn stale_wake_is_still_counted_when_owner_settles_before_cancellation() {
    let runtime = runtime();
    let owner = runtime.register(OwnerKind::Task, None).unwrap();
    let wake = runtime.park(owner.token()).unwrap();
    let (checked_tx, checked_rx) = std::sync::mpsc::sync_channel(0);
    let (resume_tx, resume_rx) = std::sync::mpsc::sync_channel(0);
    let worker = std::thread::spawn(move || {
        wake.wake_with_after_live_check(|| {
            checked_tx.send(()).unwrap();
            resume_rx
                .recv_timeout(std::time::Duration::from_secs(5))
                .unwrap();
        })
    });
    checked_rx
        .recv_timeout(std::time::Duration::from_secs(5))
        .unwrap();
    drop(owner);
    runtime.cancel();
    resume_tx.send(()).unwrap();
    assert!(!worker.join().unwrap());
    assert_eq!(runtime.snapshot().stale_wakes, 1);
    runtime.retire().unwrap();
}

#[test]
fn accepted_work_may_park_and_wake_during_closing_and_draining() {
    for draining in [false, true] {
        let runtime = runtime();
        let owner = runtime.register(OwnerKind::Task, None).unwrap();
        runtime.close();
        if draining {
            runtime.begin_drain();
        }
        let phase = if draining {
            RuntimePhase::Draining
        } else {
            RuntimePhase::Closing
        };
        let wake = runtime.park(owner.token()).unwrap();
        assert_eq!(runtime.snapshot().parked_tasks, 1);
        assert!(wake.wake());
        let snapshot = runtime.snapshot();
        assert_eq!(snapshot.phase, phase);
        assert_eq!(snapshot.parked_tasks, 0);
        drop(owner);
        runtime.retire().unwrap();
    }
}

#[test]
fn foreign_store_token_and_opaque_sleeping_work_cannot_establish_quiescence() {
    let first = runtime();
    let fresh = runtime();
    let owner = first.register(OwnerKind::Task, None).unwrap();
    let waiter = first.park(owner.token()).unwrap();
    assert!(fresh.park(owner.token()).is_err());
    assert!(first.retire().is_err());
    drop(owner);
    first.retire().unwrap();
    assert!(!waiter.wake());
    fresh.retire().unwrap();
}

#[test]
fn recurring_timer_coalesces_storms_and_cancelled_waits_keep_physical_ownership() {
    use std::time::Duration;
    let runtime = runtime();
    let first = Instant::now();
    let timer = RuntimeTimer::new(&runtime, first, Some(Duration::from_nanos(1)), None).unwrap();
    let mut wait = timer.begin_wait().unwrap();
    assert!(timer.begin_wait().is_err());
    assert_eq!(
        wait.complete(first + Duration::from_secs(1)).unwrap(),
        1_000_000_000
    );
    drop(wait);
    let wait = timer.begin_wait().unwrap();
    assert_eq!(
        wait.requested(),
        first + Duration::from_secs(1) + Duration::from_nanos(1)
    );
    timer.close();
    assert!(wait.is_closed());
    assert!(timer.begin_wait().is_err());
    drop(timer);
    assert_eq!(runtime.snapshot().owners[4], 1);
    assert!(runtime.retire().is_err());
    drop(wait);
    assert_eq!(runtime.snapshot().owners[4], 0);
    runtime.retire().unwrap();
}

#[test]
fn timer_next_refuses_when_the_original_c_wait_uses_the_last_wait_slot() {
    let seed = runtime();
    let runtime = ActivationRuntime::new(
        seed.inner.budget.clone(),
        RuntimeLimits {
            waits: 1,
            ..seed.inner.limits
        },
    )
    .unwrap();
    drop(seed);

    let task = runtime.register(OwnerKind::Task, None).unwrap();
    let c_wait = runtime
        .register(OwnerKind::Wait, Some(task.token()))
        .unwrap();
    let timer = RuntimeTimer::new(&runtime, Instant::now(), None, Some(c_wait.token())).unwrap();
    let wake = runtime.park(task.token()).unwrap();
    let before = runtime.snapshot();
    assert_eq!(before.parked_tasks, 1);
    assert_eq!(before.owners[OwnerKind::Wait.index()], 1);
    assert_eq!(before.owners[OwnerKind::Timer.index()], 1);
    assert_eq!(
        timer.begin_wait().unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    let after = runtime.snapshot();
    assert_eq!(after.owners, before.owners);
    assert_eq!(after.parked_tasks, 1);
    assert_eq!(after.admission_failures, before.admission_failures + 1);
    assert!(wake.wake());
    assert_eq!(runtime.snapshot().parked_tasks, 0);

    timer.close();
    drop(timer);
    drop(c_wait);
    let timer = RuntimeTimer::new(&runtime, Instant::now(), None, Some(task.token())).unwrap();
    let physical_wait = timer.begin_wait().unwrap();
    assert_eq!(runtime.snapshot().owners[OwnerKind::Wait.index()], 1);
    drop(physical_wait);
    timer.close();
    drop(timer);
    drop(task);
    runtime.retire().unwrap();
}

#[test]
fn timer_next_refusal_then_cancellation_preserves_original_wait_custody() {
    for stopped_before_cancel in [false, true] {
        let seed = runtime();
        let runtime = ActivationRuntime::new(
            seed.inner.budget.clone(),
            RuntimeLimits {
                waits: 1,
                ..seed.inner.limits
            },
        )
        .unwrap();
        drop(seed);
        let task = runtime.register(OwnerKind::Task, None).unwrap();
        let c_wait = runtime
            .register(OwnerKind::Wait, Some(task.token()))
            .unwrap();
        let mut timer =
            Some(RuntimeTimer::new(&runtime, Instant::now(), None, Some(c_wait.token())).unwrap());
        let wake = runtime.park(task.token()).unwrap();
        assert_eq!(
            timer.as_ref().unwrap().begin_wait().unwrap_err().code,
            PlatformErrorCode::ResourceExhausted
        );
        if stopped_before_cancel {
            let timer = timer.take().unwrap();
            timer.close();
            drop(timer);
        }
        let before = runtime.snapshot();
        assert_eq!(before.owners[OwnerKind::Wait.index()], 1);
        assert_eq!(
            before.owners[OwnerKind::Timer.index()],
            u32::from(!stopped_before_cancel)
        );
        runtime.cancel();
        assert!(!wake.wake());
        let after = runtime.snapshot();
        assert_eq!(after.phase, RuntimePhase::Cancelling);
        assert_eq!(after.parked_tasks, 1);
        assert_eq!(after.owners, before.owners);
        assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
        drop(timer);
        drop(c_wait);
        drop(task);
        runtime.retire().unwrap();
    }
}

#[test]
fn readiness_weak_headers_remain_paid_without_retaining_runtime_payload() {
    let runtime = runtime();
    let budget = runtime.inner.budget.clone();
    let runtime_bytes = Shared::<Inner>::allocation_bytes().unwrap();
    let task = runtime.register(OwnerKind::Task, None).unwrap();
    let wake = runtime.park(task.token()).unwrap();
    let second = wake.clone();
    drop(task);
    // Do not retire: destruction itself must free the real record slab even
    // while readiness clones keep only the original runtime header alive.
    assert!(budget.host_memory_bytes() > runtime_bytes);
    drop(runtime);
    assert!(!wake.wake());
    assert!(!second.wake());
    assert_eq!(budget.host_memory_bytes(), runtime_bytes);
    assert_eq!(budget.outstanding_reservations(), 1);
    drop(wake);
    assert_eq!(budget.host_memory_bytes(), runtime_bytes);
    std::thread::spawn(move || drop(second)).join().unwrap();
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

#[test]
fn runtime_header_refusal_precedes_generation_and_keeps_original_ledger() {
    let runtime = runtime();
    let budget = runtime.inner.budget.clone();
    let bytes = Shared::<Inner>::allocation_bytes().unwrap();
    let remaining = budget.remaining_at(Instant::now()).memory_bytes;
    let padding = budget.reserve_host_memory(remaining - bytes + 1).unwrap();
    let before = budget.host_memory_bytes();
    let reservations = budget.outstanding_reservations();
    let peak = budget.snapshot_at(Instant::now()).peak_memory_bytes;
    let failure = ActivationRuntime::new(budget.clone(), runtime.inner.limits).unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(budget.host_memory_bytes(), before);
    assert_eq!(budget.outstanding_reservations(), reservations);
    assert_eq!(budget.snapshot_at(Instant::now()).peak_memory_bytes, peak);
    assert!(runtime.inner.state.lock().unwrap().slab.is_none());
    drop(padding);
    let fresh = ActivationRuntime::new(budget.clone(), runtime.inner.limits).unwrap();
    assert_ne!(fresh.inner.generation, runtime.inner.generation);
    assert_eq!(budget.host_memory_bytes(), bytes * 2);
    drop(fresh);
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

#[test]
fn timer_header_refusal_precedes_admission_and_waiter_retains_actual_backing() {
    let runtime = runtime();
    let budget = runtime.inner.budget.clone();
    let first = Instant::now();
    // Establish the existing lazy slab independently of timer metadata.
    drop(runtime.register(OwnerKind::Task, None).unwrap());
    let base = budget.host_memory_bytes();
    let timer = RuntimeTimer::new(&runtime, first, None, None).unwrap();
    let timer_bytes = budget.host_memory_bytes() - base;
    assert!(timer_bytes > 2 * 64);
    drop(timer);
    assert_eq!(budget.host_memory_bytes(), base);
    let remaining = budget.remaining_at(Instant::now()).memory_bytes;
    let padding = budget
        .reserve_host_memory(remaining - timer_bytes + 1)
        .unwrap();
    let before = runtime.snapshot();
    let reservations = budget.outstanding_reservations();
    let failure = RuntimeTimer::new(&runtime, first, None, None).unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(runtime.snapshot(), before);
    assert_eq!(budget.outstanding_reservations(), reservations);
    drop(padding);
    let timer = RuntimeTimer::new(&runtime, first, None, None).unwrap();
    let waiter = timer.begin_wait().unwrap();
    let second = timer.clone();
    timer.close();
    drop(timer);
    std::thread::spawn(move || drop(second)).join().unwrap();
    assert_eq!(budget.host_memory_bytes(), base + timer_bytes);
    assert_eq!(runtime.snapshot().owners[OwnerKind::Timer.index()], 1);
    assert_eq!(runtime.snapshot().owners[OwnerKind::Wait.index()], 1);
    assert!(runtime.retire().is_err());
    assert!(waiter.is_closed());
    drop(waiter);
    assert_eq!(runtime.snapshot().owners, [0; 7]);
    assert_eq!(budget.host_memory_bytes(), base);
    runtime.retire().unwrap();
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

#[test]
fn immediate_ready_wake_on_running_task_preserves_sibling_and_runtime_phase() {
    for phase in [
        RuntimePhase::Running,
        RuntimePhase::Closing,
        RuntimePhase::Draining,
    ] {
        let runtime = runtime();
        let current = runtime.register(OwnerKind::Task, None).unwrap();
        let sibling = runtime.register(OwnerKind::Task, None).unwrap();
        let sibling_wake = runtime.park(sibling.token()).unwrap();
        match phase {
            RuntimePhase::Running => {}
            RuntimePhase::Closing => runtime.close(),
            RuntimePhase::Draining => runtime.begin_drain(),
            _ => unreachable!(),
        }
        let wait = runtime
            .register(OwnerKind::Wait, Some(current.token()))
            .unwrap();
        let before = runtime.snapshot();
        assert_eq!(before.phase, phase);
        assert_eq!(before.parked_tasks, 1);
        // The current Task has never been parked. Immediate zero-duration
        // readiness must not mark it parked or make its sibling runnable.
        assert!(runtime.wake(current.token()));
        assert_eq!(runtime.snapshot(), before);
        {
            let state = runtime.inner.state.lock().unwrap();
            assert!(!runtime.record(&state, current.token()).unwrap().parked);
            assert!(runtime.record(&state, sibling.token()).unwrap().parked);
        }
        assert!(sibling_wake.wake());
        drop((wait, sibling, current));
        runtime.retire().unwrap();
    }
}

#[test]
fn immediate_ready_wake_refuses_ancestor_stop_after_its_live_check() {
    for finalize in [false, true] {
        let (parent, child, runtime) = child_runtime();
        let current = runtime.register(OwnerKind::Task, None).unwrap();
        let sibling = runtime.register(OwnerKind::Task, None).unwrap();
        let _sibling_wake = runtime.park(sibling.token()).unwrap();
        let wait = runtime
            .register(OwnerKind::Wait, Some(current.token()))
            .unwrap();
        let before = runtime.snapshot();
        let wake = RuntimeWake {
            inner: runtime.inner.downgrade(),
            token: current.token(),
        };
        assert!(!wake.wake_with_after_live_check(|| {
            if finalize {
                let _ = parent.finalize_at(None, Instant::now());
            } else {
                parent.cancel_descendants().unwrap();
            }
        }));
        let after = runtime.snapshot();
        assert_eq!(after.phase, RuntimePhase::Cancelling);
        assert_eq!(after.owners, before.owners);
        assert_eq!(after.parked_tasks, before.parked_tasks);
        assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
        assert_eq!(after.stale_wakes, before.stale_wakes);
        drop((wait, sibling, current));
        runtime.retire().unwrap();
        // Weak wake handles retain the actual runtime backing until dropped.
        drop((_sibling_wake, wake));
        drop(runtime);
        let _ = child.finish(None, Instant::now());
        assert_eq!(parent.descendant_snapshot().unwrap().live_descendants, 0);
    }
}

#[test]
fn immediate_ready_wake_refuses_cancellation_at_tentative_publication() {
    use std::sync::mpsc;
    use std::time::Duration;
    let runtime = runtime();
    let current = runtime.register(OwnerKind::Task, None).unwrap();
    let sibling = runtime.register(OwnerKind::Task, None).unwrap();
    let _sibling_wake = runtime.park(sibling.token()).unwrap();
    let wait = runtime
        .register(OwnerKind::Wait, Some(current.token()))
        .unwrap();
    let before = runtime.snapshot();
    let wake = RuntimeWake {
        inner: runtime.inner.downgrade(),
        token: current.token(),
    };
    let budget = runtime.inner.budget.clone();
    let (held_tx, held_rx) = mpsc::sync_channel(0);
    let (resume_tx, resume_rx) = mpsc::sync_channel(0);
    let worker = std::thread::spawn(move || {
        wake.wake_with_hooks(
            || {},
            |step| {
                if step == ReadinessStep::Tentative {
                    held_tx.send(()).unwrap();
                    resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                }
            },
        )
    });
    held_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    let hidden = runtime.inner.state.try_lock().is_err();
    let guarded = budget.test_accounting_is_locked();
    let close_budget = budget.clone();
    let (done_tx, done_rx) = mpsc::sync_channel(0);
    let closer = std::thread::spawn(move || {
        close_budget.cancel_descendants().unwrap();
        done_tx.send(()).unwrap();
    });
    let signalled = done_rx.recv_timeout(Duration::from_secs(3)).is_ok();
    resume_tx.send(()).unwrap();
    let result = worker.join().unwrap();
    if !signalled {
        done_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    }
    closer.join().unwrap();
    assert!(hidden && guarded && signalled && !result);
    let after = runtime.snapshot();
    assert_eq!(after.phase, RuntimePhase::Cancelling);
    assert_eq!(after.owners, before.owners);
    assert_eq!(after.parked_tasks, before.parked_tasks);
    assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
    assert_eq!(after.stale_wakes, before.stale_wakes);
    {
        let state = runtime.inner.state.lock().unwrap();
        assert!(!runtime.record(&state, current.token()).unwrap().parked);
        assert!(runtime.record(&state, sibling.token()).unwrap().parked);
    }
    drop((wait, sibling, current));
    runtime.retire().unwrap();
}

#[test]
fn immediate_ready_wake_refuses_deadline_after_initial_live_check() {
    use std::time::Duration;
    let limit = ResourceBudget {
        cpu_fuel: 1_000_000,
        memory_bytes: 1_000_000,
        wall_time_limit_millis: Some(2000),
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 0,
        effect_count: 0,
    };
    let grant = EffectiveActivationBudget::admit_profile_at(
        BudgetProfile::Phase3,
        &limit,
        &limit,
        &limit,
        None,
        ClockSample::new(1000, Instant::now()),
    )
    .unwrap();
    let budget = ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap();
    budget
        .enable_descendants(crate::DelegationLimits::default(), Arc::new(Signal))
        .unwrap();
    let runtime = runtime_with_budget(budget);
    let current = runtime.register(OwnerKind::Task, None).unwrap();
    let sibling = runtime.register(OwnerKind::Task, None).unwrap();
    let sibling_wake = runtime.park(sibling.token()).unwrap();
    let wait = runtime
        .register(OwnerKind::Wait, Some(current.token()))
        .unwrap();
    let before = runtime.snapshot();
    let deadline = runtime.inner.budget.deadline().monotonic().unwrap();
    let wake = RuntimeWake {
        inner: runtime.inner.downgrade(),
        token: current.token(),
    };
    let checked = std::cell::Cell::new(false);
    assert!(!wake.wake_with_after_live_check(|| {
        checked.set(true);
        std::thread::sleep(
            deadline.saturating_duration_since(Instant::now()) + Duration::from_millis(5),
        );
    }));
    assert!(
        checked.get(),
        "deadline must pass after the initial live check"
    );
    let after = runtime.snapshot();
    assert_eq!(
        after, before,
        "deadline refusal changes no owners, phase or wake counters"
    );
    drop((wait, sibling, current));
    runtime.retire().unwrap();
    drop((wake, sibling_wake));
}

#[test]
fn immediate_wait_settlement_alone_is_not_a_terminal_readiness_fence() {
    let runtime = runtime();
    let current = runtime.register(OwnerKind::Task, None).unwrap();
    let wait = runtime
        .register(OwnerKind::Wait, Some(current.token()))
        .unwrap();
    let before = runtime.snapshot();
    // Model the real host settle sequence: table() checks liveness, then the
    // original RuntimeOwner is removed. Closure can win between those steps.
    runtime.check_live().unwrap();
    runtime.inner.budget.cancel_descendants().unwrap();
    drop(wait);
    assert_eq!(
        runtime.snapshot().owners[OwnerKind::Wait.index()],
        before.owners[OwnerKind::Wait.index()] - 1
    );
    assert!(
        !runtime.wake(current.token()),
        "fenced wake must reject the already-closed ledger"
    );
    assert_eq!(runtime.snapshot().phase, RuntimePhase::Cancelling);
    drop(current);
    runtime.retire().unwrap();
}

#[test]
fn elapsed_plain_timer_requires_a_live_timer_owner_and_preserves_drain() {
    let runtime = runtime();
    let timer = runtime.register(OwnerKind::Timer, None).unwrap();
    let task = runtime.register(OwnerKind::Task, None).unwrap();
    let snapshot = runtime.snapshot();
    assert_eq!(
        runtime
            .commit_elapsed_timer_readiness(task.token())
            .unwrap_err()
            .code,
        PlatformErrorCode::InvalidArgument
    );
    runtime.close();
    runtime.begin_drain();
    runtime
        .commit_elapsed_timer_readiness(timer.token())
        .unwrap();
    assert_eq!(runtime.snapshot().phase, RuntimePhase::Draining);
    assert_eq!(runtime.snapshot().owners, snapshot.owners);
    let stale = timer.token();
    drop(timer);
    assert_eq!(
        runtime
            .commit_elapsed_timer_readiness(stale)
            .unwrap_err()
            .code,
        PlatformErrorCode::InvalidArgument
    );
    drop(task);
    runtime.retire().unwrap();
}

#[test]
fn elapsed_plain_timer_orders_original_and_ancestor_cancellation_with_commit() {
    use std::sync::mpsc;
    use std::time::Duration;

    for ancestor in [false, true] {
        for close_first in [false, true] {
            let (parent, child, runtime) = if ancestor {
                let (parent, child, runtime) = child_runtime();
                (Some(parent), Some(child), runtime)
            } else {
                (None, None, runtime())
            };
            let owner = runtime.register(OwnerKind::Timer, None).unwrap();
            let token = owner.token();
            let before = runtime.snapshot();
            let budget = runtime.inner.budget.clone();
            let closing = parent.as_ref().unwrap_or(&budget).clone();
            let worker_runtime = runtime.clone();
            let (held_tx, held_rx) = mpsc::sync_channel(0);
            let (resume_tx, resume_rx) = mpsc::sync_channel(0);
            let worker = std::thread::spawn(move || {
                worker_runtime.commit_elapsed_timer_readiness_with_hooks(token, |step| {
                    let target = if close_first {
                        ReadinessStep::Guarded
                    } else {
                        ReadinessStep::Committed
                    };
                    if step == target {
                        held_tx.send(()).unwrap();
                        resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                    }
                })
            });
            held_rx.recv_timeout(Duration::from_secs(3)).unwrap();
            let guarded = budget.test_accounting_is_locked();
            let (done_tx, done_rx) = mpsc::sync_channel(0);
            let closer = std::thread::spawn(move || {
                closing.cancel_descendants().unwrap();
                done_tx.send(()).unwrap();
            });
            let closed_before_resume = done_rx.recv_timeout(Duration::from_secs(3)).is_ok();
            resume_tx.send(()).unwrap();
            let result = worker.join().unwrap();
            if !closed_before_resume {
                done_rx.recv_timeout(Duration::from_secs(3)).unwrap();
            }
            closer.join().unwrap();
            assert!(guarded && closed_before_resume);
            if close_first {
                assert_eq!(result.unwrap_err().code, PlatformErrorCode::Cancelled);
            } else {
                result.unwrap();
            }
            let after = runtime.snapshot();
            assert_eq!(after.owners, before.owners);
            assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
            drop(owner);
            runtime.retire().unwrap();
            drop(runtime);
            if let Some(child) = child {
                drop(budget);
                let _ = child.finish(None, Instant::now());
                assert_eq!(
                    parent
                        .unwrap()
                        .descendant_snapshot()
                        .unwrap()
                        .live_descendants,
                    0
                );
            } else {
                assert_eq!(budget.host_memory_bytes(), 0);
            }
        }
    }
}

#[test]
fn elapsed_plain_timer_finalization_orders_before_or_after_commit() {
    use std::sync::mpsc;
    use std::time::Duration;

    for close_first in [false, true] {
        let runtime = runtime();
        let budget = runtime.inner.budget.clone();
        let owner = runtime.register(OwnerKind::Timer, None).unwrap();
        let token = owner.token();
        let before = runtime.snapshot();
        let worker_runtime = runtime.clone();
        let (held_tx, held_rx) = mpsc::sync_channel(0);
        let (resume_tx, resume_rx) = mpsc::sync_channel(0);
        let worker = std::thread::spawn(move || {
            worker_runtime.commit_elapsed_timer_readiness_with_hooks(token, |step| {
                let target = if close_first {
                    ReadinessStep::Checked
                } else {
                    ReadinessStep::Committed
                };
                if step == target {
                    held_tx.send(()).unwrap();
                    resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                }
            })
        });
        held_rx.recv_timeout(Duration::from_secs(3)).unwrap();
        let close_budget = budget.clone();
        let (started_tx, started_rx) = mpsc::sync_channel(0);
        let (done_tx, done_rx) = mpsc::sync_channel(0);
        let closer = std::thread::spawn(move || {
            started_tx.send(()).unwrap();
            let terminal = close_budget.finalize_at(None, Instant::now());
            done_tx
                .send(terminal.consumption().peak_memory_bytes)
                .unwrap();
        });
        started_rx.recv_timeout(Duration::from_secs(3)).unwrap();
        let early = done_rx.recv_timeout(if close_first {
            Duration::from_secs(3)
        } else {
            Duration::from_millis(100)
        });
        let before_resume = early.is_ok();
        resume_tx.send(()).unwrap();
        let result = worker.join().unwrap();
        let terminal_peak = match early {
            Ok(peak) => peak,
            Err(_) => done_rx.recv_timeout(Duration::from_secs(3)).unwrap(),
        };
        closer.join().unwrap();
        assert_eq!(before_resume, close_first);
        if close_first {
            assert_eq!(result.unwrap_err().code, PlatformErrorCode::Cancelled);
        } else {
            result.unwrap();
        }
        let after = runtime.snapshot();
        assert_eq!(after.owners, before.owners);
        assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
        assert!(terminal_peak >= before.host_memory_bytes);
        drop(owner);
        runtime.retire().unwrap();
        drop(runtime);
        assert_eq!(budget.host_memory_bytes(), 0);
    }
}

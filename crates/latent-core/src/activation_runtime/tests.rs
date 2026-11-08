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
fn finalization_after_the_last_probe_can_precede_owner_publication() {
    // Known boundary: the original budget terminal transition does not take
    // the runtime state lock. Keep this causal control until they are joined
    // by a shared admission/terminal handshake.
    let runtime = runtime();
    let budget = runtime.inner.budget.clone();
    let mut reserved_at_terminal = 0;
    let mut state = runtime.inner.state.lock().unwrap();
    let owner = runtime
        .register_locked_with_hook(&mut state, OwnerKind::Task, None, |step| {
            if step == AdmissionStep::CheckedBeforePublication {
                reserved_at_terminal = budget.host_memory_bytes();
                let terminal = budget.finalize_at(None, Instant::now());
                assert!(terminal.consumption().peak_memory_bytes >= reserved_at_terminal);
            }
        })
        .unwrap();
    drop(state);
    assert!(budget.finalized().is_some());
    assert_eq!(runtime.snapshot().owners[0], 1);
    assert_eq!(budget.host_memory_bytes(), reserved_at_terminal);
    drop(owner);
    assert_eq!(budget.host_memory_bytes(), reserved_at_terminal);
    runtime.retire().unwrap();
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
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

//! Actual original-ledger reservations for the activation runtime's backings.
use super::*;
use latent_core::{ActivationBudget, BudgetCancellationProbe, DelegationLimits};

struct Signal;
impl BudgetCancellationProbe for Signal {
    fn is_cancelled(&self) -> bool {
        false
    }
    fn cancelled(&self) -> latent_core::BoxFuture<'_, ()> {
        Box::pin(std::future::pending())
    }
    fn mark_terminal(&self) {}
}

fn budget(bytes: u64) -> ActivationBudget {
    let budget = crate::host::native_table_tests::budget(bytes);
    budget
        .enable_descendants(DelegationLimits::default(), Arc::new(Signal))
        .unwrap();
    budget
}

fn limits(timers: u32) -> RuntimeLimits {
    RuntimeLimits {
        tasks: 1,
        executors: 0,
        queued_work: 0,
        waits: 0,
        timers,
        results: 0,
        native_owners: 0,
    }
}

fn table_bytes(limits: RuntimeLimits) -> u64 {
    (std::mem::size_of::<Table>()
        + if limits.timers == 0 {
            0
        } else {
            std::mem::size_of::<RuntimeTimer>() * limits.timers as usize
                + BACKING_ALLOCATION_BOOKKEEPING
        }) as u64
}

#[test]
fn runtime_owner_storage_uses_exact_nonzero_array_layout() {
    for capacity in [1, 2, 8192] {
        let layout = std::alloc::Layout::array::<RuntimeOwner>(capacity).unwrap();
        assert_ne!(layout.size(), 0);
        assert_eq!(
            backing_bytes::<RuntimeOwner>(capacity).unwrap(),
            (layout.size() + BACKING_ALLOCATION_BOOKKEEPING) as u64
        );
        let storage = owner_storage::allocate(capacity).unwrap();
        assert!(storage.is_empty());
        assert_eq!(storage.capacity(), capacity);
        assert_eq!((storage.as_ptr() as usize) % layout.align(), 0);
        drop(storage);
    }
    for capacity in [0, usize::MAX] {
        assert!(owner_storage::allocate(capacity).is_err());
    }
}

#[test]
fn runtime_owner_allocator_refusal_keeps_original_backing_and_charge() {
    let limits = RuntimeLimits {
        tasks: 2,
        executors: 0,
        queued_work: 8,
        waits: 0,
        timers: 0,
        results: 0,
        native_owners: 0,
    };
    let bounded = budget(1_000_000);
    let mut table = Table::new(bounded.clone(), limits, None).unwrap();
    let original = table.register_owner(OwnerKind::Task, None).unwrap();
    let pointer = table.owners.as_ptr();
    let charge = bounded.host_memory_bytes();
    let snapshot = table.runtime.snapshot();
    let expected_replacement = backing_bytes::<RuntimeOwner>(2).unwrap();
    let refusal = table.prepare_owner_slot_with(|capacity| {
        assert_eq!(capacity, 2);
        assert_eq!(bounded.host_memory_bytes(), charge + expected_replacement);
        Err(())
    });
    assert_eq!(
        refusal.unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(table.owners.as_ptr(), pointer);
    assert_eq!(table.owners.capacity(), 1);
    assert_eq!(table.owners[0].token(), original);
    assert_eq!(table.runtime.snapshot().owners, snapshot.owners);
    assert_eq!(table.runtime.snapshot().phase, snapshot.phase);
    assert_eq!(bounded.host_memory_bytes(), charge);
    drop(table);
    assert_eq!(bounded.host_memory_bytes(), 0);
}

#[test]
fn runtime_owner_table_single_task_does_not_require_maximum_vector() {
    let limits = RuntimeLimits {
        tasks: 1,
        executors: 0,
        queued_work: 4095,
        waits: 0,
        timers: 0,
        results: 0,
        native_owners: 0,
    };
    // Measure the independently admitted runtime header and slab under the
    // original ledger, including one actual Task. This does not build a guest.
    let probe = budget(1_000_000);
    let runtime = ActivationRuntime::new(probe.clone(), limits).unwrap();
    let task = runtime.register(OwnerKind::Task, None).unwrap();
    let runtime_bytes = probe.host_memory_bytes();
    drop(task);
    drop(runtime);
    assert_eq!(probe.host_memory_bytes(), 0);
    let single_owner = backing_bytes::<RuntimeOwner>(1).unwrap();
    let limit = runtime_bytes + std::mem::size_of::<Table>() as u64 + single_owner + 1024;
    assert!(limit < table_bytes(limits) + backing_bytes::<RuntimeOwner>(limits.total()).unwrap());
    let other_bytes = 2 * 1024 * 1024;
    let bounded = budget(other_bytes + limit);
    let mut other = bounded.reserve_host_memory(other_bytes).unwrap();
    other.confirm();
    let mut table = Table::new(bounded.clone(), limits, None)
        .expect("one Task should not need the maximum owners vector");
    assert_eq!(table.owners.capacity(), 0);
    let fuel_before = bounded.remaining_at(Instant::now()).cpu_fuel;
    let token = table.register_owner(OwnerKind::Task, None).unwrap();
    assert_eq!(
        fuel_before - bounded.remaining_at(Instant::now()).cpu_fuel,
        200 + limits.total() as u64
    );
    assert_eq!(table.owners.capacity(), 1);
    assert_eq!(table.owners[0].token(), token);
    assert_eq!(table.runtime.snapshot().owners[0], 1);
    drop(table);
    drop(other);
    assert_eq!(bounded.host_memory_bytes(), 0);
}

#[test]
fn runtime_owner_growth_keeps_original_owners_through_refusal_and_retry() {
    let limits = RuntimeLimits {
        tasks: 2,
        executors: 0,
        queued_work: 8,
        waits: 0,
        timers: 0,
        results: 0,
        native_owners: 0,
    };
    let probe = budget(1_000_000);
    let mut table = Table::new(probe.clone(), limits, None).unwrap();
    table.register_owner(OwnerKind::Task, None).unwrap();
    let first_bytes = probe.host_memory_bytes();
    drop(table);
    assert_eq!(probe.host_memory_bytes(), 0);

    let replacement = backing_bytes::<RuntimeOwner>(2).unwrap();
    let bounded = budget(first_bytes + replacement + 256);
    let mut table = Table::new(bounded.clone(), limits, None).unwrap();
    let original = table.register_owner(OwnerKind::Task, None).unwrap();
    let wake = table.runtime.park(original).unwrap();
    let before = table.runtime.snapshot();
    let mut blocker = bounded.reserve_host_memory(257).unwrap();
    blocker.confirm();
    let charged = bounded.host_memory_bytes();
    let invalid = RuntimeToken {
        generation: original.generation,
        id: u64::MAX,
    };
    assert_eq!(
        table
            .register_owner(OwnerKind::Task, Some(invalid))
            .unwrap_err()
            .code,
        PlatformErrorCode::InvalidArgument
    );
    assert_eq!(
        table
            .register_owner(OwnerKind::Task, Some(original))
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(table.runtime.snapshot().phase, before.phase);
    assert_eq!(table.runtime.snapshot().owners, before.owners);
    assert_eq!(
        table.runtime.snapshot().admission_failures,
        before.admission_failures + 2
    );
    assert_eq!(table.owners.capacity(), 1);
    assert_eq!(table.owners[0].token(), original);
    assert_eq!(bounded.host_memory_bytes(), charged);
    drop(blocker);
    let fuel_before = bounded.remaining_at(Instant::now()).cpu_fuel;
    let next = table
        .register_owner(OwnerKind::Task, Some(original))
        .unwrap();
    assert_eq!(
        fuel_before - bounded.remaining_at(Instant::now()).cpu_fuel,
        2 * (100 + limits.total() as u64)
    );
    assert_eq!(next.id, original.id + 1);
    assert_eq!(table.owners.capacity(), 2);
    assert_eq!(table.owners[0].token(), original);
    assert_eq!(
        bounded.host_memory_bytes(),
        first_bytes - backing_bytes::<RuntimeOwner>(1).unwrap() + replacement
    );
    drop(wake);
    drop(table);
    assert_eq!(bounded.host_memory_bytes(), 0);
}

#[test]
fn runtime_owner_failed_growth_preserves_wait_only_phase() {
    let limits = RuntimeLimits {
        tasks: 1,
        executors: 0,
        queued_work: 8,
        waits: 1,
        timers: 0,
        results: 0,
        native_owners: 0,
    };
    let probe = budget(1_000_000);
    let mut table = Table::new(probe.clone(), limits, None).unwrap();
    table.register_owner(OwnerKind::Wait, None).unwrap();
    let first_bytes = probe.host_memory_bytes();
    drop(table);
    assert_eq!(probe.host_memory_bytes(), 0);

    let replacement = backing_bytes::<RuntimeOwner>(2).unwrap();
    let bounded = budget(first_bytes + replacement + 256);
    let mut table = Table::new(bounded.clone(), limits, None).unwrap();
    let wait = table.register_owner(OwnerKind::Wait, None).unwrap();
    let wake = table.runtime.park(wait).unwrap();
    let before = table.runtime.snapshot();
    assert_eq!(before.phase, RuntimePhase::Waiting);
    let mut blocker = bounded.reserve_host_memory(257).unwrap();
    blocker.confirm();
    let charged = bounded.host_memory_bytes();
    assert_eq!(
        table
            .register_owner(OwnerKind::Task, None)
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    let after = table.runtime.snapshot();
    assert_eq!(after.phase, RuntimePhase::Waiting);
    assert_eq!(after.owners, before.owners);
    assert_eq!(table.owners[0].token(), wait);
    assert_eq!(bounded.host_memory_bytes(), charged);
    drop(blocker);
    drop(wake);
    drop(table);
    assert_eq!(bounded.host_memory_bytes(), 0);
}

#[test]
fn runtime_owner_growth_retains_both_backings_until_replacement() {
    let limits = RuntimeLimits {
        tasks: 2,
        executors: 0,
        queued_work: 8,
        waits: 0,
        timers: 0,
        results: 0,
        native_owners: 0,
    };
    let bounded = budget(1_000_000);
    let mut table = Table::new(bounded.clone(), limits, None).unwrap();
    let original = table.register_owner(OwnerKind::Task, None).unwrap();
    let old_ptr = table.owners.as_ptr();
    let before = bounded.host_memory_bytes();
    let replacement = backing_bytes::<RuntimeOwner>(2).unwrap();
    table
        .register_owner(OwnerKind::Task, Some(original))
        .unwrap();
    assert_ne!(old_ptr, table.owners.as_ptr());
    assert!(bounded.snapshot_at(Instant::now()).peak_memory_bytes >= before + replacement);
    assert_eq!(
        bounded.host_memory_bytes(),
        before - backing_bytes::<RuntimeOwner>(1).unwrap() + replacement
    );
    drop(table);
    assert_eq!(bounded.host_memory_bytes(), 0);
}

#[test]
fn runtime_owner_preparation_never_authorizes_a_later_closed_registration() {
    let limits = RuntimeLimits {
        tasks: 2,
        executors: 0,
        queued_work: 8,
        waits: 0,
        timers: 0,
        results: 0,
        native_owners: 0,
    };
    let bounded = budget(1_000_000);
    let mut table = Table::new(bounded.clone(), limits, None).unwrap();
    let original = table.register_owner(OwnerKind::Task, None).unwrap();
    let wake = table.runtime.park(original).unwrap();
    let before = table.runtime.snapshot();
    let runtime = table.runtime.clone();
    let denied = table.register_owner_with_hook(OwnerKind::Task, None, || {
        std::thread::spawn(move || runtime.begin_drain())
            .join()
            .unwrap();
    });
    assert_eq!(denied.unwrap_err().code, PlatformErrorCode::Cancelled);
    assert_eq!(table.runtime.snapshot().phase, RuntimePhase::Draining);
    assert_eq!(table.runtime.snapshot().owners, before.owners);
    assert_eq!(table.owners[0].token(), original);
    assert_eq!(table.owners.capacity(), 2);
    drop(wake);
    drop(table);
    assert_eq!(bounded.host_memory_bytes(), 0);
}

#[test]
fn runtime_owner_preparation_does_not_admit_after_original_cancellation() {
    let limits = RuntimeLimits {
        tasks: 2,
        executors: 0,
        queued_work: 8,
        waits: 0,
        timers: 0,
        results: 0,
        native_owners: 0,
    };
    let probe = budget(1_000_000);
    let mut probe_table = Table::new(probe.clone(), limits, None).unwrap();
    probe_table.register_owner(OwnerKind::Task, None).unwrap();
    let first_bytes = probe.host_memory_bytes();
    drop(probe_table);
    for can_grow in [false, true] {
        let limit = if can_grow {
            1_000_000
        } else {
            first_bytes + backing_bytes::<RuntimeOwner>(2).unwrap() - 1
        };
        let bounded = budget(limit);
        let mut table = Table::new(bounded.clone(), limits, None).unwrap();
        let original = table.register_owner(OwnerKind::Task, None).unwrap();
        let wake = table.runtime.park(original).unwrap();
        let before = table.runtime.snapshot();
        let charged_before = bounded.host_memory_bytes();
        let cancel_budget = bounded.clone();
        let denied = table.register_owner_with_hook(OwnerKind::Task, Some(original), || {
            std::thread::spawn(move || cancel_budget.cancel_descendants().unwrap())
                .join()
                .unwrap();
        });
        assert_eq!(denied.unwrap_err().code, PlatformErrorCode::Cancelled);
        let after = table.runtime.snapshot();
        assert_eq!(after.phase, RuntimePhase::Cancelling);
        assert_eq!(after.owners, before.owners);
        assert_eq!(table.owners.len(), 1);
        assert_eq!(table.owners[0].token(), original);
        let expected_charge = if can_grow {
            assert_eq!(table.owners.capacity(), 2);
            charged_before - backing_bytes::<RuntimeOwner>(1).unwrap()
                + backing_bytes::<RuntimeOwner>(2).unwrap()
        } else {
            assert_eq!(table.owners.capacity(), 1);
            charged_before
        };
        assert_eq!(bounded.host_memory_bytes(), expected_charge);
        drop(wake);
        drop(table);
        assert_eq!(bounded.host_memory_bytes(), 0);
    }
}

#[test]
fn runtime_owner_preparation_rechecks_a_concurrent_owner_limit() {
    let limits = RuntimeLimits {
        tasks: 2,
        executors: 0,
        queued_work: 8,
        waits: 0,
        timers: 0,
        results: 0,
        native_owners: 0,
    };
    let probe = budget(1_000_000);
    let mut probe_table = Table::new(probe.clone(), limits, None).unwrap();
    probe_table.register_owner(OwnerKind::Task, None).unwrap();
    let first_bytes = probe.host_memory_bytes();
    drop(probe_table);
    for can_grow in [false, true] {
        let limit = if can_grow {
            1_000_000
        } else {
            first_bytes + backing_bytes::<RuntimeOwner>(2).unwrap() - 1
        };
        let bounded = budget(limit);
        let mut table = Table::new(bounded.clone(), limits, None).unwrap();
        let original = table.register_owner(OwnerKind::Task, None).unwrap();
        let wake = table.runtime.park(original).unwrap();
        let runtime = table.runtime.clone();
        let mut concurrent = None;
        let denied = table.register_owner_with_hook(OwnerKind::Task, Some(original), || {
            concurrent = Some(
                std::thread::spawn(move || runtime.register(OwnerKind::Task, None))
                    .join()
                    .unwrap()
                    .unwrap(),
            );
        });
        let failure = denied.unwrap_err();
        assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
        assert_eq!(failure.message, "runtime-owner-limit");
        assert_eq!(table.runtime.snapshot().owners[0], 2);
        assert_eq!(table.owners.len(), 1);
        assert_eq!(table.owners[0].token(), original);
        drop(concurrent.take());
        assert_eq!(table.runtime.snapshot().phase, RuntimePhase::Waiting);
        drop(wake);
        drop(table);
        assert_eq!(bounded.host_memory_bytes(), 0);
    }
}

#[test]
fn runtime_table_prepays_each_real_backing_and_no_empty_timer_allocation() {
    for count in [0, 2] {
        let limits = limits(count);
        let expected = table_bytes(limits);
        let budget = budget(1_000_000);
        let runtime = ActivationRuntime::new(budget.clone(), limits).unwrap();
        let header = budget.host_memory_bytes();
        assert!(header > 0);
        drop(runtime);
        assert_eq!(budget.host_memory_bytes(), 0);
        let table = Table::new(budget.clone(), limits, None).unwrap();
        assert_eq!(table.owners.capacity(), 0);
        assert_eq!(table.timers.capacity(), count as usize);
        assert_eq!(budget.host_memory_bytes(), expected + header);
        drop(table);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
    }
}

#[test]
fn runtime_table_refusals_release_original_reservation_before_publication() {
    let limits = limits(2);
    let bytes = table_bytes(limits);
    // This fails before either backing allocation.
    let too_small = budget(bytes - 1);
    assert!(matches!(Table::new(too_small.clone(), limits, None),
        Err(error) if error.code == PlatformErrorCode::ResourceExhausted));
    assert_eq!(too_small.host_memory_bytes(), 0);
    assert_eq!(too_small.outstanding_reservations(), 0);
    assert_eq!(too_small.snapshot_at(Instant::now()).peak_memory_bytes, 0);

    // The table backings fit, but the separately charged runtime header does
    // not. The constructor must drop both backings and its pending guard.
    let no_header = budget(bytes);
    assert!(matches!(Table::new(no_header.clone(), limits, None),
        Err(error) if error.code == PlatformErrorCode::ResourceExhausted));
    assert_eq!(no_header.host_memory_bytes(), 0);
    assert_eq!(no_header.outstanding_reservations(), 0);
    assert_eq!(
        no_header.snapshot_at(Instant::now()).peak_memory_bytes,
        bytes - std::mem::size_of::<Table>() as u64
    );
}

#[test]
fn plain_elapsed_wait_refuses_when_runtime_cancel_wins_after_live_check() {
    let runtime = ActivationRuntime::new(budget(1_000_000), limits(1)).unwrap();
    let owner = runtime.register(OwnerKind::Timer, None).unwrap();
    let before = runtime.snapshot();
    let (checked_tx, checked_rx) = std::sync::mpsc::sync_channel(0);
    let (resume_tx, resume_rx) = std::sync::mpsc::sync_channel(0);
    let token = owner.token();
    let worker_runtime = runtime.clone();
    let worker = std::thread::spawn(move || {
        worker_runtime.check_live().unwrap();
        checked_tx.send(()).unwrap();
        resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
        complete_elapsed_wait(&worker_runtime, None, Some(token), Instant::now())
    });
    checked_rx.recv_timeout(Duration::from_secs(5)).unwrap();
    runtime.cancel();
    resume_tx.send(()).unwrap();
    assert_eq!(
        worker.join().unwrap().unwrap_err().code,
        PlatformErrorCode::Cancelled
    );
    let after = runtime.snapshot();
    assert_eq!(after.phase, RuntimePhase::Cancelling);
    assert_eq!(after.owners, before.owners);
    assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
    drop(owner);
    runtime.retire().unwrap();
}

#[test]
fn admitted_plain_wait_can_complete_during_closing_and_draining() {
    for draining in [false, true] {
        let runtime = ActivationRuntime::new(budget(1_000_000), limits(1)).unwrap();
        let owner = runtime.register(OwnerKind::Timer, None).unwrap();
        runtime.close();
        if draining {
            runtime.begin_drain();
        }
        assert_eq!(
            complete_elapsed_wait(&runtime, None, Some(owner.token()), Instant::now()).unwrap(),
            0
        );
        assert_eq!(
            runtime.snapshot().phase,
            if draining {
                RuntimePhase::Draining
            } else {
                RuntimePhase::Closing
            }
        );
        drop(owner);
        runtime.retire().unwrap();
    }
}
#[test]
fn plain_elapsed_wait_refuses_same_ledger_cancellation_during_probe() {
    use std::sync::{
        atomic::{AtomicBool, Ordering},
        mpsc, Mutex,
    };

    // This test-only pause models preemption after the ledger flag load.
    // Real cancellation probes remain bounded and nonblocking.
    struct PausingProbe {
        armed: AtomicBool,
        entered: mpsc::Sender<()>,
        resume: Mutex<mpsc::Receiver<()>>,
    }
    impl BudgetCancellationProbe for PausingProbe {
        fn is_cancelled(&self) -> bool {
            if self.armed.swap(false, Ordering::AcqRel) {
                self.entered.send(()).unwrap();
                self.resume
                    .lock()
                    .unwrap()
                    .recv_timeout(Duration::from_secs(3))
                    .unwrap();
            }
            false
        }
        fn cancelled(&self) -> latent_core::BoxFuture<'_, ()> {
            Box::pin(std::future::pending())
        }
        fn mark_terminal(&self) {}
    }
    let (entered_tx, entered_rx) = mpsc::channel();
    let (resume_tx, resume_rx) = mpsc::channel();
    let probe = Arc::new(PausingProbe {
        armed: AtomicBool::new(false),
        entered: entered_tx,
        resume: Mutex::new(resume_rx),
    });
    let budget = crate::host::native_table_tests::budget(1_000_000);
    budget
        .enable_descendants(DelegationLimits::default(), probe.clone())
        .unwrap();
    let runtime = ActivationRuntime::new(budget.clone(), limits(1)).unwrap();
    let owner = runtime.register(OwnerKind::Timer, None).unwrap();
    let before = runtime.snapshot();
    let token = owner.token();
    let worker_runtime = runtime.clone();
    probe.armed.store(true, Ordering::Release);
    let worker = std::thread::spawn(move || {
        complete_elapsed_wait(&worker_runtime, None, Some(token), Instant::now())
    });
    entered_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    budget.cancel_descendants().unwrap();
    assert!(budget.descendant_is_cancelled());
    resume_tx.send(()).unwrap();
    let result = worker.join().unwrap();
    let after = runtime.snapshot();
    assert_eq!(after.owners, before.owners);
    assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
    drop(owner);
    runtime.retire().unwrap();
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(result.unwrap_err().code, PlatformErrorCode::Cancelled);
}

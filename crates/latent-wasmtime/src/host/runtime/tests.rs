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
        + std::mem::size_of::<RuntimeOwner>() * limits.total()
        + BACKING_ALLOCATION_BOOKKEEPING
        + if limits.timers == 0 {
            0
        } else {
            std::mem::size_of::<RuntimeTimer>() * limits.timers as usize
                + BACKING_ALLOCATION_BOOKKEEPING
        }) as u64
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
        assert_eq!(table.owners.capacity(), limits.total());
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

use super::*;
use crate::durable::tests::{attempt, conclusion, open, Directory};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::time::Duration;

fn while_fenced<T: Send>(
    handle: &AuditHandle,
    action: impl FnOnce(AuditHandle) -> Result<T> + Send,
) -> Result<T> {
    let held = handle.shared.state.lock().unwrap();
    let owner = handle.clone();
    thread::scope(|scope| {
        let (entered, started) = mpsc::sync_channel(0);
        let (sent, received) = mpsc::sync_channel(1);
        scope.spawn(move || {
            entered.send(()).unwrap();
            sent.send(action(owner)).unwrap();
        });
        started.recv_timeout(Duration::from_secs(2)).unwrap();
        let premature = received.recv_timeout(Duration::from_millis(50));
        drop(held);
        assert!(
            matches!(premature, Err(RecvTimeoutError::Timeout)),
            "control work must wait for the memory fence, not report capacity"
        );
        received.recv_timeout(Duration::from_secs(2)).unwrap()
    })
}

#[test]
fn control_reservation_waits_for_memory_fence_while_hot_reservation_rejects() {
    let directory = Directory::new();
    let (handle, _worker) = open(directory.0.join("audit"), AuditLimits::default()).unwrap();
    {
        let _held = handle.shared.state.lock().unwrap();
        let failure = handle.try_reserve_critical(&attempt()).err().unwrap();
        assert_eq!(failure.message, "audit-busy");
    }
    let reservation =
        while_fenced(&handle, |owner| owner.reserve_control_critical(&attempt())).unwrap();
    let mut active = reservation.begin().blocking_wait().unwrap();
    active.mutation_started().unwrap();
    active.finish(conclusion()).blocking_wait().unwrap();
    let snapshot = handle.snapshot();
    assert_eq!(snapshot.retained_records, 2);
    assert_eq!(snapshot.reserved_records, 0);
}

#[test]
fn recovery_snapshot_and_reconciliation_wait_for_memory_fence() {
    let directory = Directory::new();
    let path = directory.0.join("audit");
    let mut store = Store::open(&path, AuditLimits::default()).unwrap();
    let candidate = attempt();
    store
        .append(
            candidate.scope.clone(),
            candidate.actor.clone(),
            AuditRecordData::Attempt(candidate),
        )
        .unwrap();
    drop(store);
    let (handle, _worker) = open(&path, AuditLimits::default()).unwrap();
    let pending = while_fenced(&handle, |owner| owner.pending_attempts()).unwrap();
    assert_eq!(pending.len(), 1);
    let mut terminal = conclusion();
    terminal.result = AuditOperationResult::Unknown;
    terminal.reason = AuditReason::ReceiptUnavailable;
    terminal.receipt_digest = None;
    let ticket = while_fenced(&handle, |owner| {
        owner.reconcile(pending[0].sequence, terminal)
    })
    .unwrap();
    ticket.blocking_wait().unwrap();
    assert_eq!(handle.snapshot().unknown_outcomes, 1);
    assert_eq!(handle.snapshot().reserved_records, 0);
}

#[test]
fn control_reservation_preserves_capacity_pending_and_closed_rejection() {
    let directory = Directory::new();
    let (handle, _worker) = open(directory.0.join("audit"), AuditLimits::default()).unwrap();
    let reservation = handle.reserve_control_critical(&attempt()).unwrap();
    let failure = handle.reserve_control_critical(&attempt()).err().unwrap();
    assert_eq!(failure.message, "audit-critical-pending");
    assert_eq!(handle.snapshot().reserved_records, 2);
    let mut active = reservation.begin().blocking_wait().unwrap();
    active.mutation_started().unwrap();
    active.finish(conclusion()).blocking_wait().unwrap();
    {
        let mut state = handle.shared.state.lock().unwrap();
        state.reserved_records =
            handle.shared.limits.maximum_records - state.summary.retained_records;
    }
    let failure = handle.reserve_control_critical(&attempt()).err().unwrap();
    assert_eq!(failure.message, "audit-capacity");
    handle.shared.state.lock().unwrap().reserved_records = 0;
    handle.close();
    let failure = handle.reserve_control_critical(&attempt()).err().unwrap();
    assert_eq!(failure.message, "audit-closed");
}

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

#[test]
fn two_observations_exhaust_32k_control_queue_until_actual_writer_drain() {
    let directory = Directory::new();
    let path = directory.0.join("audit");
    let limits = AuditLimits {
        maximum_queued_operations: 8,
        maximum_queued_bytes: 32 * 1024,
        ..Default::default()
    };
    let store = Store::open(&path, limits).unwrap();
    let (records, bytes, next) = store.summary();
    // Delay starting the real writer, so its two prepaid observations cannot
    // race this capacity assertion. No sleeps, production hooks or extra quota.
    let shared = Arc::new(Shared {
        limits,
        state: Mutex::new(State {
            queue: VecDeque::new(),
            queued_bytes: 0,
            reserved_records: 0,
            reserved_bytes: 0,
            summary: AuditSnapshot {
                retained_records: records,
                retained_bytes: bytes,
                next_sequence: next,
                ..Default::default()
            },
            closed: false,
            pending: None,
            finish: None,
            begin: None,
        }),
        wake: Condvar::new(),
        pages: Arc::new(PageBudget {
            state: Mutex::new((0, 0)),
            owners: limits.maximum_query_owners,
            bytes: limits.maximum_total_page_bytes,
        }),
        dropped: AtomicU64::new(0),
        unavailable: AtomicU64::new(0),
        finished: AtomicBool::new(false),
    });
    let handle = AuditHandle {
        shared: shared.clone(),
    };
    let event = AuditObservation {
        scope: crate::AuditScope::Node,
        actor: attempt().actor,
        kind: crate::Phase2AuditEventKind::CacheMiss,
        outcome: crate::AuditOutcome::Succeeded,
        identities: crate::AuditIdentities::default(),
        reason: AuditReason::CacheMiss,
        cache_kind: Some(crate::AuditCacheKind::Raw),
        occurred_at_unix_millis: 1,
    };
    handle.try_capture(&event).unwrap();
    handle.try_capture(&event).unwrap();
    let full = handle.snapshot();
    assert_eq!(full.queued_operations, 2);
    assert_eq!(full.queued_bytes, 32 * 1024);
    assert_eq!(full.reserved_records, 2);
    let failure = handle.reserve_control_critical(&attempt()).err().unwrap();
    assert_eq!(
        failure.code,
        latent_core::PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(failure.message, "audit-capacity");
    assert_eq!(
        handle.snapshot(),
        full,
        "failed admission has no partial reservation"
    );
    // Closing prevents new work but the actual writer still drains prepaid
    // records, refunds their charges, and releases its filesystem owner.
    handle.close();
    run::run(shared, store);
    let drained = handle.snapshot();
    assert_eq!(drained.retained_records, 2);
    assert_eq!(drained.queued_operations, 0);
    assert_eq!(drained.queued_bytes, 0);
    assert_eq!(drained.reserved_records, 0);
    assert_eq!(drained.reserved_bytes, 0);
    assert!(!drained.recovery_pending);
    let (reopened, _worker) = open(&path, limits).unwrap();
    assert_eq!(reopened.snapshot().retained_records, 2);
    let mut active = reopened
        .reserve_control_critical(&attempt())
        .unwrap()
        .begin()
        .blocking_wait()
        .unwrap();
    active.mutation_started().unwrap();
    active.finish(conclusion()).blocking_wait().unwrap();
    assert_eq!(reopened.snapshot().retained_records, 4);
}

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
fn abandoned_reservation_synchronizes_with_the_worker_wait_predicate() {
    let directory = Directory::new();
    let (handle, _worker) = open(directory.0.join("audit"), AuditLimits::default()).unwrap();
    let reservation = handle.reserve_control_critical(&attempt()).unwrap();
    while_fenced(&handle, move |_owner| {
        drop(reservation);
        Ok(())
    })
    .unwrap();
    let deadline = Instant::now() + Duration::from_secs(2);
    while handle.snapshot().pending_attempts != 0 {
        assert!(
            Instant::now() < deadline,
            "abandoned reservation must retire"
        );
        thread::yield_now();
    }
    let snapshot = handle.snapshot();
    assert_eq!(snapshot.pending_attempts, 0);
    assert_eq!(snapshot.reserved_records, 0);
    assert_eq!(snapshot.reserved_bytes, 0);
    assert_eq!(snapshot.queued_bytes, 0);
    assert_eq!(snapshot.retained_records, 0);
}

#[test]
fn abandoned_started_attempt_synchronizes_and_retires_as_unknown() {
    let directory = Directory::new();
    let (handle, _worker) = open(directory.0.join("audit"), AuditLimits::default()).unwrap();
    let mut active = handle
        .reserve_control_critical(&attempt())
        .unwrap()
        .begin()
        .blocking_wait()
        .unwrap();
    active.mutation_started().unwrap();
    while_fenced(&handle, move |_owner| {
        drop(active);
        Ok(())
    })
    .unwrap();
    let deadline = Instant::now() + Duration::from_secs(2);
    while handle.snapshot().pending_attempts != 0 {
        assert!(Instant::now() < deadline, "abandoned attempt must retire");
        thread::yield_now();
    }
    let snapshot = handle.snapshot();
    assert_eq!(snapshot.pending_attempts, 0);
    assert_eq!(snapshot.reserved_records, 0);
    assert_eq!(snapshot.reserved_bytes, 0);
    assert_eq!(snapshot.queued_bytes, 0);
    assert_eq!(snapshot.retained_records, 2);
    assert_eq!(snapshot.unknown_outcomes, 1);
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
    assert!(handle
        .wait_until_idle_for_test(Instant::now() + Duration::from_secs(2))
        .unwrap());
    let reservation = handle.reserve_control_critical(&attempt()).unwrap();
    assert!(!handle
        .wait_until_idle_for_test(Instant::now() + Duration::from_millis(20))
        .unwrap());
    let failure = handle.reserve_control_critical(&attempt()).err().unwrap();
    assert_eq!(failure.message, "audit-critical-pending");
    assert_eq!(handle.snapshot().reserved_records, 2);
    let mut active = reservation.begin().blocking_wait().unwrap();
    active.mutation_started().unwrap();
    active.finish(conclusion()).blocking_wait().unwrap();
    assert!(handle
        .wait_until_idle_for_test(Instant::now() + Duration::from_secs(2))
        .unwrap());
    {
        let mut state = handle.shared.state.lock().unwrap();
        state.reserved_records =
            handle.shared.limits.maximum_records - state.summary.retained_records;
    }
    let failure = handle.reserve_control_critical(&attempt()).err().unwrap();
    assert_eq!(failure.message, "audit-capacity");
    handle.shared.state.lock().unwrap().reserved_records = 0;
    handle.close();
    assert_eq!(
        handle
            .wait_until_idle_for_test(Instant::now() + Duration::from_secs(2))
            .unwrap_err()
            .message,
        "audit-closed"
    );
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
            waiting: false,
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

#[test]
fn query_notification_follows_command_retirement_with_response_lease_still_live() {
    use std::{
        future::Future,
        pin::Pin,
        task::{Context, Poll, Wake, Waker},
    };

    struct AdmissionOnWake {
        handle: AuditHandle,
        notice: mpsc::SyncSender<(AuditSnapshot, Result<AuditCriticalReservation>)>,
    }
    impl Wake for AdmissionOnWake {
        fn wake(self: Arc<Self>) {
            let snapshot = self.handle.snapshot();
            let admission = self.handle.reserve_control_critical(&attempt());
            self.notice.send((snapshot, admission)).unwrap();
        }
    }
    let directory = Directory::new();
    let limits = AuditLimits {
        maximum_queued_operations: 8,
        maximum_queued_bytes: 32 * 1024,
        ..Default::default()
    };
    let (store, shared, handle) = deferred_journal(&directory.0.join("audit"), limits);
    let query = AuditQueryRequest {
        scope: crate::AuditScope::Node,
        filter: crate::AuditFilter::default(),
        cursor: None,
        limit: 128,
        maximum_bytes: 65536,
    };
    let mut ticket = handle
        .query(query, Instant::now() + Duration::from_secs(5))
        .unwrap();
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
    assert_eq!(handle.snapshot().queued_bytes, 20 * 1024);
    let (notice, observed) = mpsc::sync_channel(1);
    let waker = Waker::from(Arc::new(AdmissionOnWake {
        handle: handle.clone(),
        notice,
    }));
    assert!(matches!(
        Pin::new(&mut ticket.0).poll(&mut Context::from_waker(&waker)),
        Poll::Pending
    ));
    // The real reply's synchronous wake observes the exact notification boundary,
    // before this same writer can consume the next prepaid observation.
    let (snapshot, admission, page) = thread::scope(|scope| {
        let writer = scope.spawn(|| run::run(shared, store));
        let (snapshot, admission) = observed.recv_timeout(Duration::from_secs(5)).unwrap();
        let admitted = admission
            .as_ref()
            .map(|_| ())
            .map_err(|e| e.message.clone());
        drop(admission);
        let page = ticket.blocking_wait().unwrap();
        handle.close();
        writer.join().unwrap();
        (snapshot, admitted, page)
    });
    assert_eq!(
        snapshot.query_owners, 1,
        "response bytes retain their independent physical lease"
    );
    assert_eq!(snapshot.query_bytes, 4 * 65536);
    assert_eq!(snapshot.queued_operations, 1);
    assert_eq!(
        snapshot.queued_bytes,
        16 * 1024,
        "completed query command bytes retired before notification"
    );
    assert!(
        admission.is_ok(),
        "one admission at the original 32 KiB boundary: {admission:?}"
    );
    assert_eq!(handle.snapshot().query_owners, 1);
    drop(page);
    assert_eq!(handle.snapshot().query_owners, 0);
    assert_eq!(handle.snapshot().query_bytes, 0);
    assert_eq!(handle.snapshot().queued_bytes, 0);
}

fn deferred_journal(path: &Path, limits: AuditLimits) -> (Store, Arc<Shared>, AuditHandle) {
    let store = Store::open(path, limits).unwrap();
    let (records, bytes, next) = store.summary();
    let shared = Arc::new(Shared {
        limits,
        state: Mutex::new(State {
            waiting: false,
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
    (store, shared, handle)
}

#[test]
fn durable_begin_notification_retires_command_but_retains_pending_record_owner() {
    use std::{
        future::Future,
        pin::Pin,
        task::{Context, Poll, Wake, Waker},
    };

    struct SnapshotOnWake {
        handle: AuditHandle,
        notice: mpsc::SyncSender<AuditSnapshot>,
    }
    impl Wake for SnapshotOnWake {
        fn wake(self: Arc<Self>) {
            self.notice.send(self.handle.snapshot()).unwrap();
        }
    }
    let directory = Directory::new();
    let limits = AuditLimits {
        maximum_queued_operations: 8,
        maximum_queued_bytes: 32 * 1024,
        ..Default::default()
    };
    let (store, shared, handle) = deferred_journal(&directory.0.join("audit"), limits);
    let mut ticket = handle.reserve_control_critical(&attempt()).unwrap().begin();
    assert_eq!(handle.snapshot().queued_bytes, 16 * 1024);
    let (notice, observed) = mpsc::sync_channel(1);
    let waker = Waker::from(Arc::new(SnapshotOnWake {
        handle: handle.clone(),
        notice,
    }));
    assert!(matches!(
        Pin::new(&mut ticket.0).poll(&mut Context::from_waker(&waker)),
        Poll::Pending
    ));
    let snapshot = thread::scope(|scope| {
        let writer = scope.spawn(|| run::run(shared, store));
        let snapshot = observed.recv_timeout(Duration::from_secs(5)).unwrap();
        let mut active = ticket.blocking_wait().unwrap();
        assert_eq!(active.sequence(), 1);
        active.mutation_started().unwrap();
        active.finish(conclusion()).blocking_wait().unwrap();
        handle.close();
        writer.join().unwrap();
        snapshot
    });
    assert_eq!(snapshot.queued_bytes, 0);
    assert_eq!(snapshot.queued_operations, 0);
    assert_eq!(
        snapshot.retained_records, 1,
        "real durable attempt precedes notification"
    );
    assert_eq!(
        snapshot.reserved_records, 1,
        "pending outcome remains funded"
    );
    assert_eq!(snapshot.reserved_bytes, limits.maximum_record_bytes);
    assert_eq!(snapshot.pending_attempts, 1);
    assert_eq!(handle.snapshot().retained_records, 2);
    assert_eq!(handle.snapshot().reserved_records, 0);
    assert_eq!(handle.snapshot().reserved_bytes, 0);
    assert_eq!(handle.snapshot().pending_attempts, 0);
}

use std::cell::RefCell;
use std::sync::mpsc::{sync_channel, SyncSender};
use std::time::Duration;

use super::*;

thread_local! {
    static CONTENTION: RefCell<Option<SyncSender<()>>> = const { RefCell::new(None) };
}

pub(super) fn note_contention() {
    if let Some(sender) = CONTENTION.with(|slot| slot.borrow_mut().take()) {
        let _ = sender.send(());
    }
}

fn ready() -> Arc<Shared> {
    let shared = Shared::new(super::super::tests::configuration());
    TransportHandle {
        shared: Arc::clone(&shared),
    }
    .start_accepting()
    .unwrap();
    shared
}

fn contended_acquire(
    shared: &Arc<Shared>,
    kind: Kind,
    update: impl FnOnce(&mut Counts),
) -> Result<Guard, Status> {
    std::thread::scope(|scope| {
        // The holder lives inside the scope closure, so unwinding always
        // releases it before the scoped worker is joined.
        let mut counts = shared.counts.lock().unwrap();
        let (observed, contention) = sync_channel(1);
        let (completed, result) = sync_channel(1);
        let worker_shared = Arc::clone(shared);
        let worker = scope.spawn(move || {
            CONTENTION.with(|slot| *slot.borrow_mut() = Some(observed));
            let result = worker_shared.acquire(kind);
            let _ = completed.send(result);
        });
        // This is sent only after try_lock actually reported WouldBlock.
        // Releasing now cannot make the old rejection branch pass the test.
        contention.recv_timeout(Duration::from_secs(2)).unwrap();
        update(&mut counts);
        drop(counts);
        let result = result.recv_timeout(Duration::from_secs(2)).unwrap();
        worker.join().unwrap();
        result
    })
}

#[test]
fn count_contention_does_not_reject_available_dispatch_capacity() {
    for kind in [
        Kind::Connection,
        Kind::Rpc { inspection: false },
        Kind::Rpc { inspection: true },
        Kind::ControlJob,
    ] {
        let shared = ready();
        let guard = contended_acquire(&shared, kind, |_| {}).unwrap();
        let snapshot = shared.snapshot();
        assert_eq!(
            snapshot.active_connections + snapshot.active_rpcs + snapshot.active_control_jobs,
            1
        );
        assert_eq!(
            snapshot.rejected_connections + snapshot.rejected_rpcs + snapshot.rejected_control_jobs,
            0
        );
        drop(guard);
        let snapshot = shared.snapshot();
        assert_eq!(
            snapshot.active_connections + snapshot.active_rpcs + snapshot.active_control_jobs,
            0
        );
    }
}

#[test]
fn contended_dispatch_still_checks_capacity_and_closing_after_locking() {
    let shared = ready();
    let held = shared.acquire(Kind::Connection).unwrap();
    let error = contended_acquire(&shared, Kind::Connection, |_| {})
        .err()
        .unwrap();
    assert_eq!(error.code(), tonic::Code::ResourceExhausted);
    assert_eq!(shared.snapshot().rejected_connections, 1);
    drop(held);

    let error = contended_acquire(&shared, Kind::Rpc { inspection: true }, |counts| {
        counts.phase = Phase::Closing;
    })
    .err()
    .unwrap();
    assert_eq!(error.code(), tonic::Code::Unavailable);
    assert_eq!(error.message(), "standalone node is not accepting work");
    let snapshot = shared.snapshot();
    assert!(!snapshot.accepting);
    assert_eq!(snapshot.active_rpcs, 0);
    assert_eq!(snapshot.rejected_rpcs, 1);
}

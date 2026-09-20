use super::support::{acquire, assert_exact_accounting, pool};
use crate::{CellLease, CellPool, FixedCellPool};
use latent_core::{ActivationId, PlatformErrorCode};
use latent_testkit::coordination::{with_watchdog, CoordinationError, PollProbe, Rendezvous, Stage, WATCHDOG};
use latent_testkit::{block_on, DeterministicIds};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

fn assert_settled(pool: &FixedCellPool, available: u32, quarantined: u32) {
    let observations = pool.observations();
    assert_eq!(observations.queue_depth, 0);
    assert_eq!(observations.active_leases, 0);
    assert_eq!(observations.available, available);
    assert_eq!(observations.quarantined, quarantined);
    assert_exact_accounting(observations);
}

async fn explicit_cancellation_cases() {
    with_watchdog(WATCHDOG, async {
        let mut ids = DeterministicIds::new("explicit-seed-433");
        // Cover both linearization orders exactly, rather than hope 64 races hit both.
        for cancel_first in [true, false] {
            let pool = pool(1, 1);
            let owner = acquire(&pool, &ids.next_id(), None).await.unwrap();
            let name = ids.next_id();
            let activation = ActivationId(name.clone());
            let mut waiting = Box::pin(acquire(&pool, &name, None));
            let probe = PollProbe::default();
            probe.pending(waiting.as_mut());
            // This is the real committed queue, while the owned acquisition is pending.
            assert_eq!(pool.observations().queue_depth, 1);
            if cancel_first {
                pool.cancel_queued(&activation).unwrap();
                assert_eq!(pool.observations().queue_depth, 0);
                pool.release(owner).await.unwrap();
                assert_eq!(probe.ready(waiting.as_mut()).unwrap_err().code, PlatformErrorCode::Cancelled);
            } else {
                pool.release(owner).await.unwrap();
                assert_eq!(pool.observations().queue_depth, 0);
                assert_eq!(pool.observations().active_leases, 1);
                assert_eq!(pool.cancel_queued(&activation).unwrap_err().code, PlatformErrorCode::NotFound);
                let lease = probe.ready(waiting.as_mut()).unwrap();
                pool.release(lease).await.unwrap();
            }
            assert_settled(&pool, 1, 0);
        }
    }).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn release_and_explicit_cancellation_race_is_linearizable() {
    explicit_cancellation_cases().await;
}

#[tokio::test(flavor = "current_thread")]
async fn explicit_cancellation_single_thread() { explicit_cancellation_cases().await; }

async fn task_abort_cases() {
    with_watchdog(WATCHDOG, async {
        for release_first in [false, true] {
            let pool = pool(1, 1);
            let mut owner = Some(acquire(&pool, "owner", None).await.unwrap());
            let waiting_pool = pool.clone();
            let mut waiting = Box::pin(async move { acquire(&waiting_pool, "waiter", None).await });
            PollProbe::default().pending(waiting.as_mut());
            assert_eq!(pool.observations().queue_depth, 1);
            // Keep the already-registered acquisition owned but unpolled. This
            // pins the cancellation boundary before or after grant delivery.
            let task = tokio::spawn(async move {
                std::future::pending::<()>().await;
                drop(waiting);
            });
            if release_first {
                pool.release(owner.take().unwrap()).await.unwrap();
                assert_eq!(pool.observations().active_leases, 1);
                assert_eq!(pool.observations().queue_depth, 0);
            }
            task.abort();
            assert!(task.await.unwrap_err().is_cancelled());
            // Joining the cancelled owner, not abort() or a yield, proves destruction.
            assert_eq!(pool.observations().queue_depth, 0);
            if let Some(owner) = owner { pool.release(owner).await.unwrap(); }
            assert_settled(&pool, 1, 0);
        }

        // Once accepted, an abandoned lease must quarantine, not refund reusable capacity.
        let pool = pool(1, 1);
        let lease = acquire(&pool, "accepted", None).await.unwrap();
        let rendezvous = Rendezvous::new(1);
        let (id, mut owner) = rendezvous.track(lease).unwrap();
        owner.commit(Stage::Entered).unwrap();
        let mut work = Box::pin(async move { owner.pause().await; drop(owner); });
        PollProbe::default().pending(work.as_mut());
        rendezvous.blocked(id, Stage::Entered).unwrap();
        let task = tokio::spawn(work);
        assert_eq!(pool.observations().active_leases, 1);
        assert_eq!(rendezvous.require_retired(id), Err(CoordinationError::WrongStage));
        task.abort();
        assert!(task.await.unwrap_err().is_cancelled());
        rendezvous.require_retired(id).unwrap();
        assert_settled(&pool, 0, 1);
    }).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn release_and_task_abort_race_preserves_exact_capacity_accounting() {
    task_abort_cases().await;
}

#[tokio::test(flavor = "current_thread")]
async fn task_abort_single_thread() { task_abort_cases().await; }

struct OwnedWork {
    buffer: Option<Vec<u8>>,
    lease: Option<CellLease>,
    bytes: Arc<AtomicUsize>,
    pool: FixedCellPool,
}

impl Drop for OwnedWork {
    fn drop(&mut self) {
        assert_eq!(self.bytes.load(Ordering::SeqCst), 16, "premature buffer refund");
        assert_eq!(self.pool.observations().active_leases, 1, "premature work refund");
        drop(self.buffer.take());
        self.bytes.store(0, Ordering::SeqCst);
        // The actual cell owner survives until after buffer destruction.
        drop(self.lease.take());
    }
}

async fn abandoned_client_case() {
    with_watchdog(WATCHDOG, async {
        let pool = pool(1, 0);
        let bytes = Arc::new(AtomicUsize::new(16));
        let work = OwnedWork {
            buffer: Some(vec![0; 16]),
            lease: Some(acquire(&pool, "retained-work", None).await.unwrap()),
            bytes: Arc::clone(&bytes),
            pool: pool.clone(),
        };
        let rendezvous = Rendezvous::new(1);
        let (id, mut work) = rendezvous.track(work).unwrap();
        work.commit(Stage::Entered).unwrap();
        let mut future = Box::pin(async move { work.pause().await; drop(work); });
        PollProbe::default().pending(future.as_mut());
        let ticket = rendezvous.blocked(id, Stage::Entered).unwrap();
        let (done, completion) = tokio::sync::oneshot::channel();
        let worker = std::thread::spawn(move || {
            block_on(future);
            let _ = done.send(()); // An abandoned client is not a worker failure.
        });
        let client = tokio::spawn(completion);
        client.abort();
        assert!(client.await.unwrap_err().is_cancelled());
        // Cancellation of the waiting test task cannot retire independently owned work.
        rendezvous.blocked(id, Stage::Entered).unwrap();
        assert_eq!(rendezvous.require_retired(id), Err(CoordinationError::WrongStage));
        assert_eq!(pool.observations().active_leases, 1);
        assert_eq!(pool.observations().available, 0);
        assert_eq!(bytes.load(Ordering::SeqCst), 16);
        rendezvous.release(ticket).unwrap();
        worker.join().unwrap();
        rendezvous.require_retired(id).unwrap();
        assert_eq!(bytes.load(Ordering::SeqCst), 0);
        assert_settled(&pool, 0, 1);
    }).await;
}

#[tokio::test(flavor = "current_thread")]
async fn abandoned_client_keeps_work_and_buffers_charged_single_thread() { abandoned_client_case().await; }

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn abandoned_client_keeps_work_and_buffers_charged_multi_thread() { abandoned_client_case().await; }

#[tokio::test(flavor = "current_thread")]
async fn lease_token_exhaustion_quarantines_the_slot_and_fails_all_waiters() {
    with_watchdog(WATCHDOG, async {
        let pool = pool(1, 2);
        let owner = acquire(&pool, "activation-owner", None).await.unwrap();
        pool.inner.state.lock().unwrap_or_else(std::sync::PoisonError::into_inner).next_lease_token = u64::MAX;
        let mut first = Box::pin(acquire(&pool, "activation-waiting-1", None));
        let mut second = Box::pin(acquire(&pool, "activation-waiting-2", None));
        let probe = PollProbe::default();
        probe.pending(first.as_mut());
        probe.pending(second.as_mut());
        assert_eq!(pool.observations().queue_depth, 2);
        pool.release(owner).await.unwrap();
        for error in [probe.ready(first.as_mut()).unwrap_err(), probe.ready(second.as_mut()).unwrap_err()] {
            assert_eq!(error.code, PlatformErrorCode::Internal);
        }
        assert_settled(&pool, 0, 1);
    }).await;
}

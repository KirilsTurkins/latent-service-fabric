//! Final open cancellation owners must be destroyed after unlocking scheduler state.

use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Weak};

use latent_admission::QuotaUsage;
use latent_core::{ActivationId, BoxFuture};

use super::measurement::fixture::{Cancellation, Fixture};
use super::state::Inner;
use super::{AdmittedSchedulingRequest, SchedulingCancellation};
use crate::{ActivationScheduler, CellClass};

#[derive(Default)]
struct Witness {
    drops: AtomicUsize,
    unlocked: AtomicBool,
    disposed: AtomicBool,
}

struct ReentrantCancellation {
    delegate: Arc<Cancellation>,
    owner: Weak<Inner>,
    witness: Arc<Witness>,
}

impl SchedulingCancellation for ReentrantCancellation {
    fn activation_id(&self) -> &ActivationId {
        self.delegate.activation_id()
    }

    fn is_cancelled(&self) -> bool {
        self.delegate.is_cancelled()
    }

    fn request_cancellation(&self) -> bool {
        self.delegate.request_cancellation()
    }

    fn cancelled(&self) -> BoxFuture<'_, ()> {
        self.delegate.cancelled()
    }
}

impl Drop for ReentrantCancellation {
    fn drop(&mut self) {
        self.witness.drops.fetch_add(1, Ordering::SeqCst);
        let owner = self.owner.upgrade().expect("scheduler remains alive");
        // Detect the regression without ever hanging this test inside Drop.
        let unlocked = owner.state.try_lock().is_ok();
        self.witness.unlocked.store(unlocked, Ordering::SeqCst);
        if unlocked {
            let snapshot = owner.observations(CellClass::Standard);
            self.witness.disposed.store(
                snapshot.active_leases == 0
                    && owner.quotas.usage().unwrap() == QuotaUsage::default(),
                Ordering::SeqCst,
            );
        }
    }
}

#[tokio::test]
async fn final_cancellation_owner_can_reenter_after_cell_and_quota_disposition() {
    for disposition in 0..3 {
        let fixture = Fixture::new(1, 4).unwrap();
        let witness = Arc::new(Witness::default());
        let cancellation = Arc::new(ReentrantCancellation {
            delegate: Cancellation::new(disposition),
            owner: Arc::downgrade(&fixture.scheduler.inner),
            witness: Arc::clone(&witness),
        });
        let assignment = fixture
            .scheduler
            .enqueue(AdmittedSchedulingRequest {
                permit: fixture.admit(disposition, 0).unwrap(),
                cancellation,
            })
            .await
            .unwrap();
        assert_eq!(witness.drops.load(Ordering::SeqCst), 0);
        match disposition {
            0 => assignment.release().await.unwrap(),
            1 => drop(assignment),
            2 => assignment.reclaim_before_execution(),
            _ => unreachable!(),
        }
        assert_eq!(witness.drops.load(Ordering::SeqCst), 1);
        assert!(witness.unlocked.load(Ordering::SeqCst));
        assert!(witness.disposed.load(Ordering::SeqCst));
        let snapshot = fixture.scheduler.observations(CellClass::Standard);
        assert_eq!(snapshot.queue_depth, 0);
        assert_eq!(snapshot.active_leases, 0);
        assert_eq!(snapshot.quarantined, u32::from(disposition == 1));
        assert_eq!(snapshot.available, 4 - u32::from(disposition == 1));
        assert!(fixture.scheduler.inner.lock().live.is_empty());
    }
}

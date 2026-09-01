use super::super::{FixedCellPoolTestTransition, FixedCellPoolTestTransitionKind};
use super::support::{acquire, pool};
use crate::CellPool;
use std::time::Duration;
use tokio::sync::mpsc::UnboundedReceiver;

async fn next_transition(
    receiver: &mut UnboundedReceiver<FixedCellPoolTestTransition>,
) -> FixedCellPoolTestTransition {
    tokio::time::timeout(Duration::from_secs(1), receiver.recv())
        .await
        .expect("pool transition notification timed out")
        .expect("pool transition observer closed")
}

#[tokio::test(flavor = "current_thread")]
async fn observer_reports_committed_active_and_queue_transitions() {
    let pool = pool(1, 1);
    let mut transitions = pool.subscribe_test_transitions();

    let owner = acquire(&pool, "activation-owner", None)
        .await
        .expect("owner lease");
    let active = next_transition(&mut transitions).await;
    assert_eq!(active.activation_id.0, "activation-owner");
    assert_eq!(
        active.kind,
        FixedCellPoolTestTransitionKind::LeaseActivated
    );
    assert_eq!(active.observations.active_leases, 1);
    assert_eq!(active.observations.queue_depth, 0);

    let waiter_pool = pool.clone();
    let waiter =
        tokio::spawn(async move { acquire(&waiter_pool, "activation-waiting", None).await });
    let queued = next_transition(&mut transitions).await;
    assert_eq!(queued.activation_id.0, "activation-waiting");
    assert_eq!(queued.kind, FixedCellPoolTestTransitionKind::RequestQueued);
    assert_eq!(queued.observations.active_leases, 1);
    assert_eq!(queued.observations.queue_depth, 1);

    pool.release(owner).await.expect("return owner lease");
    let promoted = next_transition(&mut transitions).await;
    assert_eq!(promoted.activation_id.0, "activation-waiting");
    assert_eq!(
        promoted.kind,
        FixedCellPoolTestTransitionKind::LeaseActivated
    );
    assert_eq!(promoted.observations.active_leases, 1);
    assert_eq!(promoted.observations.queue_depth, 0);

    let waiting = waiter.await.expect("waiter task").expect("waiting lease");
    pool.release(waiting).await.expect("return waiting lease");
}

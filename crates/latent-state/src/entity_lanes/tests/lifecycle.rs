use std::sync::Arc;

use latent_core::test_support::coordination::{PollProbe, Rendezvous, Stage};

use super::*;

#[test]
fn queued_cancellation_returns_original_payload_and_refunds_reservation() {
    let now = Instant::now();
    let lanes = EntityLanes::new(limits()).unwrap();
    let buffer = Arc::new(vec![7_u8; 32]);
    let weak = Arc::downgrade(&buffer);
    let waiter = lanes
        .enqueue(request(scope("tenant-A", "order", 1), 1, buffer, now), now)
        .unwrap();
    assert_eq!(lanes.snapshot().unwrap().queued, 1);
    let EntityCancellation::Queued(returned) = waiter.request_cancel().unwrap() else {
        panic!("queued cancellation must remove reservation");
    };
    assert_empty(&lanes);
    assert!(weak.upgrade().is_some());
    drop(returned);
    assert!(weak.upgrade().is_none());
    assert!(matches!(
        waiter.request_cancel().unwrap(),
        EntityCancellation::Retired
    ));
}

#[test]
fn dropped_queued_waiter_destroys_actual_payload() {
    let now = Instant::now();
    let lanes = EntityLanes::new(limits()).unwrap();
    let buffer = Arc::new(vec![7_u8; 32]);
    let weak = Arc::downgrade(&buffer);
    let waiter = lanes
        .enqueue(request(scope("tenant-A", "order", 1), 1, buffer, now), now)
        .unwrap();
    drop(waiter);
    assert!(weak.upgrade().is_none());
    assert_empty(&lanes);
}

#[test]
fn cancelled_waiter_cannot_refund_paused_physical_cleanup_owner() {
    let clock = clock();
    let now = clock.monotonic_now();
    let lanes = EntityLanes::new(limits()).unwrap();
    let buffer = Arc::new(vec![7_u8; 32]);
    let weak = Arc::downgrade(&buffer);
    let waiter = lanes
        .enqueue(request(scope("tenant-A", "order", 1), 1, buffer, now), now)
        .unwrap();
    let execution = start(&lanes, now);
    let fence = execution.fence();
    let (request, owner) = execution.into_owned_work();
    let rendezvous = Rendezvous::new(1);
    let (registration, mut physical) = rendezvous.track((request.into_payload(), owner)).unwrap();
    physical.commit(Stage::Entered).unwrap();
    let charge = lanes.snapshot().unwrap().active_bytes;
    {
        let mut pause = Box::pin(physical.pause());
        let probe = PollProbe::default();
        probe.pending(pause.as_mut());
        let readiness = rendezvous.blocked(registration, Stage::Entered).unwrap();
        assert!(matches!(
            waiter.request_cancel().unwrap(),
            EntityCancellation::ActiveRequested
        ));
        drop(waiter);
        clock.advance(Duration::from_secs(61));
        assert!(weak.upgrade().is_some());
        assert_eq!(lanes.snapshot().unwrap().active_bytes, charge);
        assert_eq!(lanes.snapshot().unwrap().active, 1);
        lanes.validate_fence(&fence).unwrap();
        rendezvous.release(readiness).unwrap();
        probe.ready(pause.as_mut());
    }
    assert!(physical
        .owner()
        .1
        .cancellation_requested(clock.monotonic_now()));
    physical.commit(Stage::CancellationObserved).unwrap();
    physical.owner().1.begin_cleanup().unwrap();
    assert_eq!(lanes.snapshot().unwrap().cleanup, 1);
    drop(physical);
    rendezvous.require_retired(registration).unwrap();
    assert!(weak.upgrade().is_none());
    assert_eq!(
        lanes.validate_fence(&fence),
        Err(EntityLaneError::StaleFence)
    );
    assert_empty(&lanes);
}

#[test]
fn stale_generation_and_restart_fences_cannot_affect_current_owner() {
    let now = Instant::now();
    let lanes = EntityLanes::new(limits()).unwrap();
    let _first = enqueue(&lanes, "tenant-A", "order", 1, now);
    let first = start(&lanes, now);
    let old = first.fence();
    drop(first);
    let _second = enqueue(&lanes, "tenant-A", "order", 2, now);
    let second = start(&lanes, now);
    let current = second.fence();
    assert!(current.generation() > old.generation());
    assert_eq!(lanes.validate_fence(&old), Err(EntityLaneError::StaleFence));
    lanes.validate_fence(&current).unwrap();
    let restarted = EntityLanes::new(limits()).unwrap();
    assert_empty::<Command>(&restarted);
    let _restart_waiter = enqueue(&restarted, "tenant-A", "order", 3, now);
    let after_restart = start(&restarted, now);
    assert_eq!(after_restart.fence().generation(), 1);
    assert_eq!(
        restarted.validate_fence(&old),
        Err(EntityLaneError::StaleFence)
    );
    assert_eq!(
        restarted.validate_fence(&current),
        Err(EntityLaneError::StaleFence)
    );
    drop((second, after_restart));
    assert_empty(&lanes);
    assert_empty(&restarted);
}

#[test]
fn namespace_recreation_revokes_old_scope_without_releasing_live_owner() {
    let now = Instant::now();
    let lanes = EntityLanes::new(limits()).unwrap();
    let _old_active = enqueue(&lanes, "tenant-A", "order", 1, now);
    let _old_queued = enqueue(&lanes, "tenant-A", "order", 2, now);
    let _other_tenant = enqueue(&lanes, "tenant-B", "order", 3, now);
    let owner = start(&lanes, now);
    let fence = owner.fence();
    let revoked = lanes
        .revoke_namespace(
            &TenantId("tenant-A".into()),
            &StateNamespaceId("orders".into()),
            1,
        )
        .unwrap();
    assert_eq!(revoked.len(), 1);
    assert_eq!(revoked[0].request.payload().attempt, 2);
    assert_eq!(lanes.snapshot().unwrap().active, 1);
    assert!(owner.cancellation_requested(now));
    assert_eq!(
        lanes.validate_fence(&fence),
        Err(EntityLaneError::StaleFence)
    );
    let _new_incarnation = lanes
        .enqueue(
            request(
                scope("tenant-A", "order", 2),
                4,
                Command {
                    publication: "publication-A",
                    attempt: 4,
                },
                now,
            ),
            now,
        )
        .unwrap();
    let other = start(&lanes, now);
    let new = start(&lanes, now);
    assert_eq!(other.request().scope().tenant().0, "tenant-B");
    assert_eq!(new.fence().scope().incarnation(), 2);
    lanes.validate_fence(&new.fence()).unwrap();
    owner.retain_physical_owner().begin_cleanup().unwrap();
    drop((owner, other, new));
    assert_empty(&lanes);
}

#[test]
fn dispatch_rechecks_current_publication_authority_outside_lane_lock() {
    let now = Instant::now();
    let lanes = EntityLanes::new(limits()).unwrap();
    let _waiter = enqueue(&lanes, "tenant-A", "order", 1, now);
    let dispatch = lanes
        .try_start_next(now, |scope, payload| {
            assert_eq!(scope.tenant().0, "tenant-A");
            assert_eq!(payload.publication, "publication-A");
            assert_eq!(lanes.snapshot().unwrap().active, 1);
            false
        })
        .unwrap()
        .unwrap();
    match dispatch {
        EntityDispatch::Rejected(rejected) => {
            assert_eq!(rejected.reason, EntityRejection::AuthorityChanged);
            assert_eq!(rejected.request.payload().publication, "publication-A");
        }
        EntityDispatch::Ready(_) => panic!("revoked publication started"),
    }
    assert_empty(&lanes);
}

#[test]
fn cancellation_or_revocation_during_authorization_never_yields_execution() {
    let now = Instant::now();
    for revoke in [false, true] {
        let lanes = EntityLanes::new(limits()).unwrap();
        let waiter = enqueue(&lanes, "tenant-A", "order", 1, now);
        let dispatch = lanes
            .try_start_next(now, |scope, _| {
                if revoke {
                    lanes
                        .revoke_namespace(scope.tenant(), scope.namespace(), scope.incarnation())
                        .unwrap();
                } else {
                    assert!(matches!(
                        waiter.request_cancel().unwrap(),
                        EntityCancellation::ActiveRequested
                    ));
                }
                true
            })
            .unwrap()
            .unwrap();
        match dispatch {
            EntityDispatch::Rejected(rejected) => assert_eq!(
                rejected.reason,
                if revoke {
                    EntityRejection::AuthorityChanged
                } else {
                    EntityRejection::CancelledBeforeExecution
                }
            ),
            EntityDispatch::Ready(_) => panic!("invalidated command started"),
        }
        assert_empty(&lanes);
    }
}

#[test]
fn synchronous_transactional_children_reject_same_key_and_cross_entity_cycles() {
    let now = Instant::now();
    let lanes = EntityLanes::new(limits()).unwrap();
    let _parent = enqueue(&lanes, "tenant-A", "parent", 1, now);
    let owner = start(&lanes, now);
    for entity in ["parent", "child"] {
        let rejected = lanes
            .enqueue(
                EntityLaneRequest::new(
                    scope("tenant-A", entity, 1),
                    vec![2],
                    Command {
                        publication: "publication-A",
                        attempt: 2,
                    },
                    0,
                    now + Duration::from_secs(1),
                    EntityCallKind::SynchronousTransactionalChild,
                ),
                now,
            )
            .err()
            .unwrap();
        assert_eq!(rejected.reason, EntityLaneError::NestedTransactionalCall);
        assert_eq!(lanes.snapshot().unwrap().active, 1);
        assert_eq!(lanes.snapshot().unwrap().queued, 0);
    }
    drop(owner);
    assert_empty(&lanes);
}

#[test]
fn cold_entity_churn_reclaims_live_lane_and_ready_metadata() {
    let now = Instant::now();
    let lanes = EntityLanes::new(limits()).unwrap();
    for id in 0..256 {
        let waiter = enqueue(&lanes, "tenant-A", &format!("cold-{id}"), id, now);
        let execution = start(&lanes, now);
        let fence = execution.fence();
        let physical = execution.retain_physical_owner();
        drop(execution);
        assert_eq!(lanes.snapshot().unwrap().keys, 1);
        physical.begin_cleanup().unwrap();
        drop(physical);
        assert_eq!(waiter.status().unwrap(), EntityWaitStatus::Retired);
        assert_eq!(
            lanes.validate_fence(&fence),
            Err(EntityLaneError::StaleFence)
        );
        assert_empty(&lanes);
    }
}

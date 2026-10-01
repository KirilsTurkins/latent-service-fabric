use super::*;

#[test]
fn global_tenant_and_entity_queue_caps() {
    let now = Instant::now();
    for kind in [
        EntityLaneLimit::GlobalQueue,
        EntityLaneLimit::TenantQueue,
        EntityLaneLimit::EntityQueue,
    ] {
        let mut config = limits();
        match kind {
            EntityLaneLimit::GlobalQueue => config.global_queued = 1,
            EntityLaneLimit::TenantQueue => config.tenant_queued = 1,
            EntityLaneLimit::EntityQueue => config.entity_queued = 1,
            _ => unreachable!(),
        }
        let lanes = EntityLanes::new(config).unwrap();
        let waiter = enqueue(&lanes, "tenant-A", "order", 1, now);
        let failed = lanes
            .enqueue(
                request(
                    scope("tenant-A", "order", 1),
                    2,
                    Command {
                        publication: "publication-B",
                        attempt: 2,
                    },
                    now,
                ),
                now,
            )
            .err()
            .unwrap();
        assert_eq!(failed.reason, EntityLaneError::Backpressure(kind));
        assert_eq!(failed.request.payload().publication, "publication-B");
        assert_eq!(lanes.snapshot().unwrap().queued, 1);
        drop(waiter);
        assert_empty(&lanes);
    }
}

#[test]
fn global_and_tenant_live_key_caps() {
    let now = Instant::now();
    for kind in [EntityLaneLimit::GlobalKeys, EntityLaneLimit::TenantKeys] {
        let mut config = limits();
        match kind {
            EntityLaneLimit::GlobalKeys => config.global_keys = 1,
            EntityLaneLimit::TenantKeys => config.tenant_keys = 1,
            _ => unreachable!(),
        }
        let lanes = EntityLanes::new(config).unwrap();
        let _first = enqueue(&lanes, "tenant-A", "key-A", 1, now);
        let owner = start(&lanes, now);
        let failed = lanes
            .enqueue(
                request(
                    scope("tenant-A", "key-B", 1),
                    2,
                    Command {
                        publication: "publication-A",
                        attempt: 2,
                    },
                    now,
                ),
                now,
            )
            .err()
            .unwrap();
        assert_eq!(failed.reason, EntityLaneError::Backpressure(kind));
        assert_eq!(lanes.snapshot().unwrap().keys, 1);
        drop(owner);
        let next = enqueue(&lanes, "tenant-A", "key-B", 2, now);
        drop(next);
        assert_empty(&lanes);
    }
}

#[test]
fn retained_bytes_stay_charged_through_active_cleanup() {
    let now = Instant::now();
    let calibration = EntityLanes::new(limits()).unwrap();
    let waiter = enqueue(&calibration, "tenant-A", "order", 1, now);
    let one_charge = calibration.snapshot().unwrap().retained_bytes();
    drop(waiter);
    for kind in [
        EntityLaneLimit::GlobalBytes,
        EntityLaneLimit::TenantBytes,
        EntityLaneLimit::EntityBytes,
    ] {
        let mut config = limits();
        match kind {
            EntityLaneLimit::GlobalBytes => config.global_bytes = one_charge,
            EntityLaneLimit::TenantBytes => config.tenant_bytes = one_charge,
            EntityLaneLimit::EntityBytes => config.entity_bytes = one_charge,
            _ => unreachable!(),
        }
        let lanes = EntityLanes::new(config).unwrap();
        let waiter = enqueue(&lanes, "tenant-A", "order", 1, now);
        let execution = start(&lanes, now);
        let (command, owner) = execution.into_owned_work();
        drop((command, waiter));
        owner.begin_cleanup().unwrap();
        let failed = lanes
            .enqueue(
                request(
                    scope("tenant-A", "order", 1),
                    2,
                    Command {
                        publication: "publication-A",
                        attempt: 2,
                    },
                    now,
                ),
                now,
            )
            .err()
            .unwrap();
        assert_eq!(failed.reason, EntityLaneError::Backpressure(kind));
        let snapshot = lanes.snapshot().unwrap();
        assert_eq!(snapshot.active_bytes, one_charge);
        assert_eq!(snapshot.cleanup, 1);
        drop(owner);
        assert_empty(&lanes);
        let waiter = enqueue(&lanes, "tenant-A", "order", 2, now);
        drop(waiter);
        assert_empty(&lanes);
    }
}

#[test]
fn scope_command_and_configuration_bounds() {
    let now = Instant::now();
    assert_eq!(
        EntityScope::new(
            TenantId(String::new()),
            StateNamespaceId("n".into()),
            1,
            EntityKey("k".into())
        ),
        Err(EntityLaneError::InvalidScope)
    );
    assert_eq!(
        EntityScope::new(
            TenantId("t".into()),
            StateNamespaceId("n".into()),
            0,
            EntityKey("k".into())
        ),
        Err(EntityLaneError::InvalidScope)
    );
    let mut invalid = limits();
    invalid.entity_queued = 0;
    assert!(matches!(
        EntityLanes::<()>::new(invalid),
        Err(EntityLaneError::InvalidLimits)
    ));
    let mut config = limits();
    config.scope_bytes = 20;
    config.command_identity_bytes = 8;
    let lanes = EntityLanes::new(config).unwrap();
    let accepted = lanes
        .enqueue(request(scope("tenant-A", "order!", 1), 1, (), now), now)
        .unwrap();
    let oversized_scope = lanes
        .enqueue(request(scope("tenant-A", "order!!", 1), 2, (), now), now)
        .err()
        .unwrap();
    assert_eq!(
        oversized_scope.reason,
        EntityLaneError::Backpressure(EntityLaneLimit::ScopeBytes)
    );
    let empty_identity = lanes
        .enqueue(
            EntityLaneRequest::new(
                scope("tenant-A", "order", 1),
                Vec::new(),
                (),
                0,
                now + Duration::from_secs(1),
                EntityCallKind::Root,
            ),
            now,
        )
        .err()
        .unwrap();
    assert_eq!(
        empty_identity.reason,
        EntityLaneError::InvalidCommandIdentity
    );
    let oversized_identity = lanes
        .enqueue(
            EntityLaneRequest::new(
                scope("tenant-A", "order", 1),
                vec![255; 9],
                (),
                0,
                now + Duration::from_secs(1),
                EntityCallKind::Root,
            ),
            now,
        )
        .err()
        .unwrap();
    assert_eq!(
        oversized_identity.reason,
        EntityLaneError::Backpressure(EntityLaneLimit::CommandIdentityBytes)
    );
    assert!(!format!("{oversized_identity:?}").contains("255"));
    drop(accepted);
    assert_empty(&lanes);
}

#[test]
fn wait_age_uses_monotonic_time_without_entity_timers() {
    let clock = clock();
    let now = clock.monotonic_now();
    let lanes = EntityLanes::new(limits()).unwrap();
    let waiter = enqueue(&lanes, "tenant-A", "order", 1, now);
    clock.set_wall_unix_millis(u64::MAX);
    clock.advance(Duration::from_secs(9));
    assert_eq!(waiter.status().unwrap(), EntityWaitStatus::Queued);
    clock.set_wall_unix_millis(0);
    clock.advance(Duration::from_secs(1));
    let dispatch = lanes
        .try_start_next(clock.monotonic_now(), |_, _| {
            panic!("expired work must not authorize")
        })
        .unwrap()
        .unwrap();
    match dispatch {
        EntityDispatch::Rejected(rejected) => {
            assert_eq!(rejected.reason, EntityRejection::WaitExpired);
        }
        EntityDispatch::Ready(_) => panic!("expired command started"),
    }
    assert_eq!(clock.pending_waiters(), 0);
    assert_empty(&lanes);
}

#[test]
fn original_deadline_expires_queued_work_during_cell_saturation() {
    let clock = clock();
    let now = clock.monotonic_now();
    let mut config = limits();
    config.global_active = 1;
    let lanes = EntityLanes::new(config).unwrap();
    let _active = enqueue(&lanes, "tenant-A", "hot", 1, now);
    let owner = start(&lanes, now);
    let waiter = lanes
        .enqueue(
            EntityLaneRequest::new(
                scope("tenant-A", "hot", 1),
                vec![2],
                Command {
                    publication: "publication-A",
                    attempt: 2,
                },
                0,
                now + Duration::from_secs(1),
                EntityCallKind::Root,
            ),
            now,
        )
        .unwrap();
    clock.advance(Duration::from_secs(1));
    match lanes
        .try_start_next(clock.monotonic_now(), |_, _| panic!("no cell eligibility"))
        .unwrap()
        .unwrap()
    {
        EntityDispatch::Rejected(rejected) => {
            assert_eq!(rejected.reason, EntityRejection::WaitExpired);
        }
        EntityDispatch::Ready(_) => panic!("expired command started"),
    }
    assert_eq!(waiter.status().unwrap(), EntityWaitStatus::Retired);
    assert_eq!(lanes.snapshot().unwrap().active, 1);
    assert_eq!(lanes.snapshot().unwrap().queued, 0);
    drop(owner);
    assert_empty(&lanes);
}

#[test]
fn identity_and_counter_exhaustion_fail_without_reusing_owners() {
    let now = Instant::now();
    let lanes = EntityLanes::new(limits()).unwrap();
    lanes.inner.state.lock().unwrap().next_ticket = u64::MAX;
    let failure = lanes
        .enqueue(request(scope("tenant-A", "order", 1), 1, (), now), now)
        .err()
        .unwrap();
    assert_eq!(failure.reason, EntityLaneError::Exhausted);
    assert_empty(&lanes);
    lanes.inner.state.lock().unwrap().next_ticket = 0;
    let waiter = lanes
        .enqueue(request(scope("tenant-A", "order", 1), 1, (), now), now)
        .unwrap();
    lanes.inner.state.lock().unwrap().next_generation = u64::MAX;
    assert!(matches!(
        lanes.try_start_next(now, |_, ()| true),
        Err(EntityLaneError::Exhausted)
    ));
    assert_eq!(waiter.status().unwrap(), EntityWaitStatus::Queued);
    assert_eq!(lanes.snapshot().unwrap().queued, 1);
    drop(waiter);
    assert_empty(&lanes);
}

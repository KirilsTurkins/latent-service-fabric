use super::*;

#[test]
fn same_key_serialization_preserves_publication_pin() {
    let now = Instant::now();
    let lanes = EntityLanes::new(limits()).unwrap();
    let first = enqueue(&lanes, "tenant-A", "hot", 1, now);
    let second = lanes
        .enqueue(
            request(
                scope("tenant-A", "hot", 1),
                2,
                Command {
                    publication: "publication-B",
                    attempt: 2,
                },
                now,
            ),
            now,
        )
        .unwrap();
    let owner = start(&lanes, now);
    assert_eq!(owner.request().payload().publication, "publication-A");
    assert_eq!(
        first.status().unwrap(),
        EntityWaitStatus::Active {
            generation: 1,
            cleanup: false,
            cancellation_requested: false,
        }
    );
    assert_eq!(second.status().unwrap(), EntityWaitStatus::Queued);
    assert!(lanes.try_start_next(now, |_, _| true).unwrap().is_none());
    drop(owner);
    let owner = start(&lanes, now);
    assert_eq!(owner.request().payload().publication, "publication-B");
    assert_eq!(owner.fence().generation(), 2);
    drop(owner);
    assert_empty(&lanes);
}

#[test]
fn distinct_keys_progress_with_hot_backlog() {
    let now = Instant::now();
    let lanes = EntityLanes::new(limits()).unwrap();
    let hot_waiters: Vec<_> = (0..16)
        .map(|id| enqueue(&lanes, "tenant-A", "hot", id, now))
        .collect();
    let _cold = enqueue(&lanes, "tenant-A", "cold", 20, now);
    let hot = start(&lanes, now);
    let cold = start(&lanes, now);
    assert_eq!(hot.request().scope().entity().0, "hot");
    assert_eq!(cold.request().scope().entity().0, "cold");
    assert_eq!(lanes.snapshot().unwrap().active, 2);
    assert_eq!(lanes.snapshot().unwrap().queued, 15);
    assert!(lanes.try_start_next(now, |_, _| true).unwrap().is_none());
    drop((hot, cold));
    drop(hot_waiters);
    assert_empty(&lanes);
}

#[test]
fn ready_keys_round_robin_after_retirement() {
    let now = Instant::now();
    let mut config = limits();
    config.global_active = 1;
    let lanes = EntityLanes::new(config).unwrap();
    let _waiters = [
        enqueue(&lanes, "tenant-A", "hot", 1, now),
        enqueue(&lanes, "tenant-A", "hot", 2, now),
        enqueue(&lanes, "tenant-A", "cold-A", 3, now),
        enqueue(&lanes, "tenant-A", "cold-B", 4, now),
    ];
    let order: Vec<_> = (0..4)
        .map(|_| {
            let execution = start(&lanes, now);
            execution.request().scope().entity().0.clone()
        })
        .collect();
    assert_eq!(order, ["hot", "cold-A", "cold-B", "hot"]);
    assert_empty(&lanes);
}

#[test]
fn tenant_active_cap_does_not_block_other_tenants() {
    let now = Instant::now();
    let mut config = limits();
    config.tenant_active = 1;
    let lanes = EntityLanes::new(config).unwrap();
    let _waiters = [
        enqueue(&lanes, "tenant-A", "A1", 1, now),
        enqueue(&lanes, "tenant-A", "A2", 2, now),
        enqueue(&lanes, "tenant-B", "B1", 3, now),
    ];
    let a = start(&lanes, now);
    let b = start(&lanes, now);
    assert_eq!(a.request().scope().tenant().0, "tenant-A");
    assert_eq!(b.request().scope().tenant().0, "tenant-B");
    assert!(lanes.try_start_next(now, |_, _| true).unwrap().is_none());
    a.retain_physical_owner().begin_cleanup().unwrap();
    assert_eq!(lanes.snapshot().unwrap().cleanup, 1);
    assert!(lanes.try_start_next(now, |_, _| true).unwrap().is_none());
    drop(a);
    let a2 = start(&lanes, now);
    assert_eq!(a2.request().scope().entity().0, "A2");
    drop((a2, b));
    assert_empty(&lanes);
}

#[test]
fn concurrent_duplicates_have_one_lane_owner() {
    let now = Instant::now();
    let lanes = EntityLanes::new(limits()).unwrap();
    let results = std::thread::scope(|threads| {
        let handles: Vec<_> = (0..8)
            .map(|_| {
                let lanes = &lanes;
                threads.spawn(move || {
                    lanes.enqueue(
                        request(
                            scope("tenant-A", "order", 1),
                            7,
                            Command {
                                publication: "publication-A",
                                attempt: 7,
                            },
                            now,
                        ),
                        now,
                    )
                })
            })
            .collect();
        handles
            .into_iter()
            .map(|h| h.join().unwrap())
            .collect::<Vec<_>>()
    });
    assert_eq!(results.iter().filter(|r| r.is_ok()).count(), 1);
    assert!(results
        .iter()
        .filter_map(|r| r.as_ref().err())
        .all(|e| e.reason == EntityLaneError::Duplicate));
    let execution = start(&lanes, now);
    assert_eq!(lanes.snapshot().unwrap().active, 1);
    let duplicate = lanes
        .enqueue(
            request(
                scope("tenant-A", "order", 1),
                7,
                Command {
                    publication: "publication-B",
                    attempt: 7,
                },
                now,
            ),
            now,
        )
        .err()
        .unwrap();
    assert_eq!(duplicate.reason, EntityLaneError::Duplicate);
    assert_eq!(execution.request().payload().publication, "publication-A");
    drop(execution);
    assert_empty(&lanes);
}

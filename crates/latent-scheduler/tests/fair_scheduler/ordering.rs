use std::time::Duration;

use latent_core::PlatformErrorCode;
use latent_scheduler::{ActivationScheduler, CellClass};

use super::support::{complete, failure, next, register, Fixture};

#[tokio::test(start_paused = true)]
async fn all_five_classes_preserve_their_configured_counts_under_simultaneous_load() {
    let fixture = Fixture::with_all_classes(1, true);
    let scheduler = &fixture.scheduler;
    let classes = [
        (CellClass::Tiny, 2, 65_536),
        (CellClass::Small, 1, 65_537),
        (CellClass::Standard, 3, 262_145),
        (CellClass::Large, 1, 1_048_577),
        (CellClass::ExtraLarge, 2, 4_194_305),
    ];
    let mut held = Vec::new();
    let mut pending = Vec::new();
    for (class, capacity, memory) in classes {
        for slot in 0..capacity {
            let request = fixture
                .custom_request(&format!("{class:?}-{slot}"), "a", 10, 60_000, memory)
                .0;
            let activation = complete(scheduler.enqueue(request)).await;
            assert_eq!(activation.lease().class, class);
            held.push(activation);
        }
        let snapshot = scheduler.observations(class);
        assert_eq!(snapshot.capacity, capacity);
        assert_eq!(snapshot.active_leases, capacity);
        assert_eq!(snapshot.available, 0);
        let mut queued = scheduler.enqueue(
            fixture
                .custom_request(&format!("{class:?}-queued"), "b", 10, 60_000, memory)
                .0,
        );
        register(&mut queued);
        pending.push(queued);
    }
    for (class, _, _) in classes {
        assert_eq!(scheduler.observations(class).queue_depth, 1);
        let index = held
            .iter()
            .position(|activation| activation.lease().class == class)
            .unwrap();
        held.remove(index).release().await.unwrap();
    }
    let mut completed_classes = std::collections::BTreeSet::new();
    while !pending.is_empty() {
        let activation = next(&mut pending).await;
        completed_classes.insert(activation.lease().class);
        activation.release().await.unwrap();
    }
    assert_eq!(completed_classes.len(), 5);
    for activation in held {
        activation.release().await.unwrap();
    }
    for (class, capacity, _) in classes {
        let snapshot = scheduler.observations(class);
        assert_eq!(snapshot.capacity, capacity);
        assert_eq!(snapshot.available, capacity);
        assert_eq!(snapshot.queue_depth, 0);
        assert_eq!(snapshot.active_leases, 0);
    }
    fixture.assert_no_quota();
}

#[tokio::test(start_paused = true)]
async fn extra_large_capacity_requires_explicit_tenant_permission_before_scheduling() {
    let fixture = Fixture::with_all_classes(1, false);
    match fixture.try_custom_request("extra-large-denied", "a", 10, 60_000, 4_194_305) {
        Err(error) => assert_eq!(error.code, PlatformErrorCode::PermissionDenied),
        Ok(_) => panic!("extra-large requires explicit tenant permission"),
    }
    assert_eq!(
        fixture
            .scheduler
            .observations(CellClass::ExtraLarge)
            .available,
        2
    );
    assert_eq!(
        fixture
            .scheduler
            .observations(CellClass::ExtraLarge)
            .granted,
        0
    );
    fixture.assert_no_quota();
}

#[tokio::test(start_paused = true)]
async fn zero_queue_capacity_denies_even_immediate_dispatch_without_leaking_quota() {
    let fixture = Fixture::new(1, 0, Duration::from_secs(1));
    assert_eq!(
        failure(fixture.scheduler.enqueue(fixture.request("denied", "a"))).await,
        PlatformErrorCode::ResourceExhausted
    );
    let snapshot = fixture.scheduler.observations(CellClass::Tiny);
    assert_eq!(snapshot.available, 1);
    assert_eq!(snapshot.active_leases, 0);
    assert_eq!(snapshot.queue_depth, 0);
    assert_eq!(snapshot.granted, 0);
    fixture.assert_no_quota();
}

#[tokio::test(start_paused = true)]
async fn configured_class_capacity_and_granted_budgets_are_enforced_independently() {
    let fixture = Fixture::new(2, 2, Duration::from_secs(1));
    let scheduler = &fixture.scheduler;
    let first = complete(scheduler.enqueue(fixture.request("tiny-one", "a"))).await;
    let second = complete(scheduler.enqueue(fixture.request("tiny-two", "b"))).await;
    let small =
        complete(scheduler.enqueue(fixture.custom_request("small", "c", 10, 60_000, 65_537).0))
            .await;
    assert_eq!(first.lease().class, CellClass::Tiny);
    assert_eq!(second.lease().class, CellClass::Tiny);
    assert_eq!(small.lease().class, CellClass::Small);
    assert_eq!(
        small.lease().granted_budget,
        *small.permit().admission().granted_budget()
    );
    assert_eq!(
        small.permit().admission().granted_budget().memory_bytes,
        65_537
    );
    assert_eq!(scheduler.observations(CellClass::Tiny).capacity, 2);
    assert_eq!(scheduler.observations(CellClass::Tiny).available, 0);
    assert_eq!(scheduler.observations(CellClass::Small).capacity, 1);
    let mut queued = scheduler.enqueue(fixture.request("tiny-three", "a"));
    register(&mut queued);
    assert_eq!(scheduler.observations(CellClass::Tiny).queue_depth, 1);
    small.release().await.unwrap();
    assert_eq!(scheduler.observations(CellClass::Small).available, 1);
    assert_eq!(scheduler.observations(CellClass::Tiny).queue_depth, 1);
    first.release().await.unwrap();
    complete(queued).await.release().await.unwrap();
    second.release().await.unwrap();
    fixture.assert_no_quota();
}

#[tokio::test(start_paused = true)]
async fn exact_queue_bound_rejects_without_losing_the_earlier_reservations() {
    let fixture = Fixture::new(1, 2, Duration::from_secs(1));
    let scheduler = &fixture.scheduler;
    let held = complete(scheduler.enqueue(fixture.request("held", "a"))).await;
    let mut pending = vec![
        scheduler.enqueue(fixture.request("queued-one", "a")),
        scheduler.enqueue(fixture.request("queued-two", "b")),
    ];
    for future in &mut pending {
        register(future);
    }
    assert_eq!(
        failure(scheduler.enqueue(fixture.request("overflow", "c"))).await,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(fixture.quotas.usage().unwrap().active_activations, 3);
    assert_eq!(fixture.quotas.usage().unwrap().queued_activations, 2);
    assert_eq!(scheduler.observations(CellClass::Tiny).queue_depth, 2);
    assert_eq!(scheduler.observations(CellClass::Tiny).queued_tenants, 2);
    assert!(scheduler.observations(CellClass::Tiny).rejected >= 1);
    held.release().await.unwrap();
    while !pending.is_empty() {
        next(&mut pending).await.release().await.unwrap();
    }
    assert_eq!(scheduler.observations(CellClass::Tiny).queue_depth, 0);
    assert_eq!(scheduler.observations(CellClass::Tiny).queued_tenants, 0);
    fixture.assert_no_quota();
}

#[tokio::test(start_paused = true)]
async fn round_robin_tenants_prevents_a_noisy_neighbor_from_taking_every_handoff() {
    let fixture = Fixture::new(1, 8, Duration::from_secs(1));
    let scheduler = &fixture.scheduler;
    let held = complete(scheduler.enqueue(fixture.request("held", "c"))).await;
    let mut pending = Vec::new();
    for (id, tenant) in [
        ("a-one", "a"),
        ("a-two", "a"),
        ("a-three", "a"),
        ("a-four", "a"),
        ("b-one", "b"),
        ("b-two", "b"),
    ] {
        let mut future = scheduler.enqueue(fixture.request(id, tenant));
        register(&mut future);
        pending.push(future);
    }
    held.release().await.unwrap();
    let mut tenants = Vec::new();
    while !pending.is_empty() {
        let activation = next(&mut pending).await;
        tenants.push(activation.permit().admission().tenant().0.clone());
        activation.release().await.unwrap();
    }
    assert_ne!(tenants[0], tenants[1]);
    assert_ne!(tenants[2], tenants[3]);
    assert_eq!(
        tenants[..4].iter().filter(|tenant| *tenant == "b").count(),
        2
    );
    fixture.assert_no_quota();
}

#[tokio::test(start_paused = true)]
async fn one_tenant_uses_priority_then_deadline_then_enqueue_order() {
    let fixture = Fixture::new(1, 8, Duration::from_secs(1));
    let scheduler = &fixture.scheduler;
    let held = complete(scheduler.enqueue(fixture.request("held", "c"))).await;
    let mut pending = Vec::new();
    for (id, priority, deadline) in [
        ("low", 1, 2_000),
        ("high-later", 9, 5_000),
        ("high-first", 9, 3_000),
        ("high-tie", 9, 3_000),
    ] {
        let mut future = scheduler.enqueue(
            fixture
                .custom_request(id, "a", priority, deadline, 65_536)
                .0,
        );
        register(&mut future);
        pending.push(future);
    }
    held.release().await.unwrap();
    let mut order = Vec::new();
    while !pending.is_empty() {
        let activation = next(&mut pending).await;
        order.push(activation.permit().admission().activation_id().0.clone());
        activation.release().await.unwrap();
    }
    assert_eq!(order, ["high-first", "high-tie", "high-later", "low"]);
    fixture.assert_no_quota();
}

#[tokio::test(start_paused = true)]
async fn aged_request_precedes_new_high_priority_work_and_wait_metrics_use_monotonic_time() {
    let fixture = Fixture::new(1, 4, Duration::from_millis(50));
    let scheduler = &fixture.scheduler;
    let held = complete(scheduler.enqueue(fixture.request("held", "c"))).await;
    let mut old = scheduler.enqueue(fixture.custom_request("aged", "a", 1, 5_000, 65_536).0);
    register(&mut old);
    tokio::time::advance(Duration::from_millis(60)).await;
    assert!(
        scheduler
            .observations(CellClass::Tiny)
            .oldest_lease_age_micros
            >= 60_000
    );
    let mut recent = scheduler.enqueue(fixture.custom_request("recent", "a", 200, 5_000, 65_536).0);
    register(&mut recent);
    let mut pending = vec![old, recent];
    held.release().await.unwrap();
    let first = next(&mut pending).await;
    assert_eq!(first.permit().admission().activation_id().0, "aged");
    first.release().await.unwrap();
    next(&mut pending).await.release().await.unwrap();
    let snapshot = scheduler.observations(CellClass::Tiny);
    assert!(snapshot.total_wait_micros >= 60_000);
    assert!(snapshot.max_wait_micros >= 60_000);
    assert_eq!(snapshot.oldest_lease_age_micros, 0);
    fixture.assert_no_quota();
}

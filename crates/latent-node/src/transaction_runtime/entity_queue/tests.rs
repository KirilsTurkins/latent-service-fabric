use super::*;
use latent_core::{EntityKey, StateNamespaceId, TenantId};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::time::Duration;

fn limits() -> EntityLaneLimits {
    EntityLaneLimits {
        global_queued: 16,
        tenant_queued: 8,
        entity_queued: 4,
        global_keys: 8,
        tenant_keys: 4,
        global_active: 4,
        tenant_active: 2,
        global_bytes: 64 * 1024,
        tenant_bytes: 32 * 1024,
        entity_bytes: 16 * 1024,
        scope_bytes: 256,
        command_identity_bytes: 64,
        maximum_wait_age: Duration::from_millis(100),
    }
}

fn scope(tenant: &str, entity: &str) -> EntityScope {
    EntityScope::new(
        TenantId(tenant.into()),
        StateNamespaceId("orders".into()),
        1,
        EntityKey(entity.into()),
    )
    .unwrap()
}

fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(3)
}

fn permit() -> NativeBufferPermit {
    use latent_core::native_capacity::{
        NativeAdmissionClass, NativeBufferClass, NativeCapacityLimits, NativeCapacityOwner,
        NativeReservationRequest,
    };
    let owner = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    let reservation = owner
        .reserve(
            NativeAdmissionClass::Ordinary,
            NativeReservationRequest {
                request_bytes: 16384,
                ..Default::default()
            },
            deadline(),
        )
        .unwrap();
    reservation
        .reserve_buffer(NativeBufferClass::Request, 8192)
        .unwrap()
}

async fn queued(queue: &EntityQueue, expected: usize) {
    tokio::time::timeout(Duration::from_secs(2), async {
        while queue.lanes.snapshot().unwrap().queued != expected {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
}

#[tokio::test]
#[expect(
    clippy::too_many_lines,
    reason = "Exercise duplicate ownership, conflict, bounds, and cancellation together"
)]
async fn duplicate_waiters_are_authorized_bounded_and_cancel_independently() {
    let mut bounds = limits();
    bounds.entity_queued = 1;
    let queue =
        Arc::new(EntityQueue::new(bounds, Arc::new(latent_core::SystemActivationClock)).unwrap());
    let key = CommandIdentity::parse_hex(&"11".repeat(32)).unwrap();
    let fingerprint = CommandIdentity::parse_hex(&"22".repeat(32)).unwrap();
    let other = CommandIdentity::parse_hex(&"33".repeat(32)).unwrap();
    let owner = queue
        .acquire_for_command(
            scope("tenant-a", "hot"),
            vec![1],
            64,
            deadline(),
            Arc::new(|| true),
            permit(),
            Some((key, fingerprint, [0; 32], None)),
            false,
            None,
        )
        .await
        .unwrap();
    let unauthorized = queue
        .acquire_for_command(
            scope("tenant-a", "hot"),
            vec![2],
            64,
            deadline(),
            Arc::new(|| true),
            permit(),
            Some((key, other, [0; 32], None)),
            false,
            None,
        )
        .await;
    assert!(matches!(
        unauthorized,
        Err(QueueError::DuplicateNeedsAuthorization { .. })
    ));
    let conflict = queue
        .acquire_for_command(
            scope("tenant-a", "hot"),
            vec![3],
            64,
            deadline(),
            Arc::new(|| true),
            permit(),
            Some((key, other, [0; 32], None)),
            true,
            None,
        )
        .await;
    assert!(matches!(conflict, Err(QueueError::DuplicateConflict)));
    let waiting_queue = Arc::clone(&queue);
    let waiter = tokio::spawn(async move {
        waiting_queue
            .acquire_for_command(
                scope("tenant-a", "hot"),
                vec![4],
                64,
                deadline(),
                Arc::new(|| true),
                permit(),
                Some((key, fingerprint, [0; 32], None)),
                true,
                None,
            )
            .await
    });
    tokio::time::timeout(Duration::from_secs(2), async {
        while queue.duplicate_waiters.lock().unwrap().is_empty() {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    let excess = queue
        .acquire_for_command(
            scope("tenant-a", "hot"),
            vec![5],
            64,
            deadline(),
            Arc::new(|| true),
            permit(),
            Some((key, fingerprint, [0; 32], None)),
            true,
            None,
        )
        .await;
    assert!(matches!(excess, Err(QueueError::DuplicateCapacity)));
    let cold = queue
        .acquire(
            scope("tenant-a", "cold"),
            vec![6],
            64,
            deadline(),
            Arc::new(|| true),
            permit(),
        )
        .await
        .unwrap();
    waiter.abort();
    assert!(waiter.await.is_err_and(|error| error.is_cancelled()));
    assert!(queue.duplicate_waiters.lock().unwrap().is_empty());
    assert_eq!(queue.commands.lock().unwrap().len(), 1);
    drop((owner, cold));
    assert!(queue.commands.lock().unwrap().is_empty());
}

#[tokio::test]
async fn duplicate_does_not_become_owner_when_the_unclaimed_owner_retires() {
    let queue =
        Arc::new(EntityQueue::new(limits(), Arc::new(latent_core::SystemActivationClock)).unwrap());
    let key = CommandIdentity::parse_hex(&"44".repeat(32)).unwrap();
    let fingerprint = CommandIdentity::parse_hex(&"55".repeat(32)).unwrap();
    let owner = queue
        .acquire_for_command(
            scope("tenant-a", "hot"),
            vec![1],
            64,
            deadline(),
            Arc::new(|| true),
            permit(),
            Some((key, fingerprint, [0; 32], None)),
            false,
            None,
        )
        .await
        .unwrap();
    let waiting_queue = Arc::clone(&queue);
    let waiter = tokio::spawn(async move {
        waiting_queue
            .acquire_for_command(
                scope("tenant-a", "hot"),
                vec![2],
                64,
                deadline(),
                Arc::new(|| true),
                permit(),
                Some((key, fingerprint, [0; 32], None)),
                true,
                None,
            )
            .await
    });
    tokio::time::timeout(Duration::from_secs(2), async {
        while queue.duplicate_waiters.lock().unwrap().is_empty() {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    drop(owner);
    let result = tokio::time::timeout(Duration::from_secs(2), waiter)
        .await
        .unwrap()
        .unwrap();
    assert!(matches!(result, Err(QueueError::OriginalOwnerEnded)));
    assert_eq!(queue.snapshot().active, 0);
    assert!(queue.commands.lock().unwrap().is_empty());
    assert!(queue.duplicate_waiters.lock().unwrap().is_empty());
}

#[tokio::test]
async fn source_pin_survives_owner_loss_during_duplicate_authorization() {
    let queue = EntityQueue::new(limits(), Arc::new(latent_core::SystemActivationClock)).unwrap();
    let key = CommandIdentity::parse_hex(&"66".repeat(32)).unwrap();
    let fingerprint = CommandIdentity::parse_hex(&"77".repeat(32)).unwrap();
    let owner = queue
        .acquire_for_command(
            scope("tenant-a", "hot"),
            vec![1],
            64,
            deadline(),
            Arc::new(|| true),
            permit(),
            Some((key, fingerprint, [1; 32], None)),
            false,
            None,
        )
        .await
        .unwrap();
    let probe = queue
        .acquire_for_command(
            scope("tenant-a", "hot"),
            vec![2],
            64,
            deadline(),
            Arc::new(|| true),
            permit(),
            Some((key, fingerprint, [2; 32], None)),
            false,
            None,
        )
        .await;
    let Err(QueueError::DuplicateNeedsAuthorization {
        source,
        owner: generation,
    }) = probe
    else {
        panic!("duplicate must capture the original owner before authorization");
    };
    assert_eq!(source, [1; 32]);
    drop(owner);
    let resumed = queue
        .acquire_for_command(
            scope("tenant-a", "hot"),
            vec![2],
            64,
            deadline(),
            Arc::new(|| true),
            permit(),
            Some((key, fingerprint, [2; 32], None)),
            true,
            Some((generation, source)),
        )
        .await;
    assert!(matches!(resumed, Err(QueueError::OriginalOwnerEnded)));
    assert!(queue.commands.lock().unwrap().is_empty());
    assert_eq!(queue.snapshot().active, 0);
}

#[tokio::test]
async fn shared_dispatch_preserves_physical_owner_and_allows_cold_key_progress() {
    let queue =
        Arc::new(EntityQueue::new(limits(), Arc::new(latent_core::SystemActivationClock)).unwrap());
    let original = queue
        .acquire(
            scope("tenant-a", "hot"),
            vec![1],
            64,
            deadline(),
            Arc::new(|| true),
            permit(),
        )
        .await
        .unwrap();
    let clone = Arc::clone(&queue);
    let waiting = tokio::spawn(async move {
        clone
            .acquire(
                scope("tenant-a", "hot"),
                vec![2],
                64,
                deadline(),
                Arc::new(|| true),
                permit(),
            )
            .await
    });
    queued(&queue, 1).await;
    let cold = queue
        .acquire(
            scope("tenant-b", "cold"),
            vec![3],
            64,
            deadline(),
            Arc::new(|| true),
            permit(),
        )
        .await
        .unwrap();
    assert_eq!(queue.lanes.snapshot().unwrap().active, 2);
    let retained = original.clone();
    drop(original);
    assert!(!waiting.is_finished());
    drop(retained);
    let next = tokio::time::timeout(Duration::from_secs(2), waiting)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    drop((next, cold));
    assert_eq!(queue.lanes.snapshot().unwrap().active, 0);
}

#[tokio::test]
async fn cancelled_waiter_refunds_queue_without_releasing_live_owner() {
    let queue =
        Arc::new(EntityQueue::new(limits(), Arc::new(latent_core::SystemActivationClock)).unwrap());
    let original = queue
        .acquire(
            scope("tenant-a", "hot"),
            vec![1],
            64,
            deadline(),
            Arc::new(|| true),
            permit(),
        )
        .await
        .unwrap();
    let clone = Arc::clone(&queue);
    let waiting = tokio::spawn(async move {
        clone
            .acquire(
                scope("tenant-a", "hot"),
                vec![2],
                64,
                deadline(),
                Arc::new(|| true),
                permit(),
            )
            .await
    });
    queued(&queue, 1).await;
    waiting.abort();
    assert!(waiting.await.is_err_and(|error| error.is_cancelled()));
    assert_eq!(queue.lanes.snapshot().unwrap().queued, 0);
    assert_eq!(queue.lanes.snapshot().unwrap().active, 1);
    drop(original);
    assert_eq!(queue.lanes.snapshot().unwrap().active, 0);
}

#[tokio::test]
async fn prepaid_native_charge_survives_until_last_physical_owner_is_dropped() {
    use latent_core::native_capacity::{
        NativeAdmissionClass, NativeBufferClass, NativeCapacityLimits, NativeCapacityOwner,
        NativeReservationRequest,
    };
    let native = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    let reservation = native
        .reserve(
            NativeAdmissionClass::Ordinary,
            NativeReservationRequest {
                request_bytes: 16384,
                ..Default::default()
            },
            deadline(),
        )
        .unwrap();
    let charged = reservation
        .reserve_buffer(NativeBufferClass::Request, 8192)
        .unwrap();
    let queue = EntityQueue::new(limits(), Arc::new(latent_core::SystemActivationClock)).unwrap();
    let lease = queue
        .acquire(
            scope("tenant-a", "hot"),
            vec![1],
            64,
            deadline(),
            Arc::new(|| true),
            charged,
        )
        .await
        .unwrap();
    drop(reservation);
    let retained = lease.clone();
    drop(lease);
    assert!(!native.snapshot().unwrap().physically_retired());
    assert_eq!(queue.lanes.snapshot().unwrap().active, 1);
    drop(retained);
    assert!(native.snapshot().unwrap().physically_retired());
    assert_eq!(queue.lanes.snapshot().unwrap().active, 0);
}

#[tokio::test]
async fn undersized_native_charge_is_rejected_before_lane_admission() {
    use latent_core::native_capacity::{
        NativeAdmissionClass, NativeBufferClass, NativeCapacityLimits, NativeCapacityOwner,
        NativeReservationRequest,
    };
    let native = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    let reservation = native
        .reserve(
            NativeAdmissionClass::Ordinary,
            NativeReservationRequest {
                request_bytes: 16384,
                ..Default::default()
            },
            deadline(),
        )
        .unwrap();
    let charged = reservation
        .reserve_buffer(NativeBufferClass::Request, 1)
        .unwrap();
    let queue = EntityQueue::new(limits(), Arc::new(latent_core::SystemActivationClock)).unwrap();
    let result = queue
        .acquire(
            scope("tenant-a", "hot"),
            vec![1],
            64,
            deadline(),
            Arc::new(|| true),
            charged,
        )
        .await;
    assert!(matches!(result, Err(QueueError::Unavailable)));
    assert_eq!(queue.lanes.snapshot().unwrap().keys, 0);
    drop(reservation);
    assert!(native.snapshot().unwrap().physically_retired());
}

#[tokio::test]
async fn cancelling_a_queued_command_refunds_its_actual_native_reservation() {
    use latent_core::native_capacity::{
        NativeAdmissionClass, NativeBufferClass, NativeCapacityLimits, NativeCapacityOwner,
        NativeReservationRequest,
    };
    let queue =
        Arc::new(EntityQueue::new(limits(), Arc::new(latent_core::SystemActivationClock)).unwrap());
    let active = queue
        .acquire(
            scope("tenant-a", "hot"),
            vec![1],
            64,
            deadline(),
            Arc::new(|| true),
            permit(),
        )
        .await
        .unwrap();
    let native = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    let reservation = native
        .reserve(
            NativeAdmissionClass::Ordinary,
            NativeReservationRequest {
                request_bytes: 16384,
                ..Default::default()
            },
            deadline(),
        )
        .unwrap();
    let charged = reservation
        .reserve_buffer(NativeBufferClass::Request, 8192)
        .unwrap();
    drop(reservation);
    let waiting_queue = Arc::clone(&queue);
    let waiting = tokio::spawn(async move {
        waiting_queue
            .acquire(
                scope("tenant-a", "hot"),
                vec![2],
                64,
                deadline(),
                Arc::new(|| true),
                charged,
            )
            .await
    });
    queued(&queue, 1).await;
    assert!(!native.snapshot().unwrap().physically_retired());
    waiting.abort();
    assert!(waiting.await.is_err_and(|error| error.is_cancelled()));
    assert!(native.snapshot().unwrap().physically_retired());
    assert_eq!(queue.lanes.snapshot().unwrap().active, 1);
    drop(active);
}

#[tokio::test]
async fn queued_authority_and_wait_age_are_rechecked_before_execution() {
    let queue =
        Arc::new(EntityQueue::new(limits(), Arc::new(latent_core::SystemActivationClock)).unwrap());
    let original = queue
        .acquire(
            scope("tenant-a", "hot"),
            vec![1],
            64,
            deadline(),
            Arc::new(|| true),
            permit(),
        )
        .await
        .unwrap();
    let current = Arc::new(AtomicBool::new(true));
    let check = Arc::clone(&current);
    let clone = Arc::clone(&queue);
    let waiting = tokio::spawn(async move {
        clone
            .acquire(
                scope("tenant-a", "hot"),
                vec![2],
                64,
                deadline(),
                Arc::new(move || check.load(Ordering::SeqCst)),
                permit(),
            )
            .await
    });
    queued(&queue, 1).await;
    current.store(false, Ordering::SeqCst);
    drop(original);
    assert!(matches!(
        waiting.await.unwrap(),
        Err(QueueError::Rejected(EntityRejection::AuthorityChanged))
    ));

    let owner = queue
        .acquire(
            scope("tenant-a", "hot"),
            vec![3],
            64,
            deadline(),
            Arc::new(|| true),
            permit(),
        )
        .await
        .unwrap();
    let result = queue
        .acquire(
            scope("tenant-a", "hot"),
            vec![4],
            64,
            deadline(),
            Arc::new(|| true),
            permit(),
        )
        .await;
    assert!(matches!(
        result,
        Err(QueueError::Rejected(EntityRejection::WaitExpired))
    ));
    assert_eq!(queue.lanes.snapshot().unwrap().active, 1);
    drop(owner);
}

#[tokio::test]
async fn queued_wait_age_uses_the_original_injected_clock() {
    struct FakeClock {
        start: Instant,
        elapsed_millis: AtomicU64,
    }
    impl ActivationClock for FakeClock {
        fn sample(&self) -> latent_core::ClockSample {
            latent_core::ClockSample::new(0, self.monotonic_now())
        }
        fn monotonic_now(&self) -> Instant {
            self.start + Duration::from_millis(self.elapsed_millis.load(Ordering::SeqCst))
        }
    }
    let start = Instant::now();
    let clock = Arc::new(FakeClock {
        start,
        elapsed_millis: AtomicU64::new(0),
    });
    let queue = Arc::new(EntityQueue::new(limits(), clock.clone()).unwrap());
    let owner = queue
        .acquire(
            scope("tenant-a", "hot"),
            vec![1],
            64,
            start + Duration::from_secs(3),
            Arc::new(|| true),
            permit(),
        )
        .await
        .unwrap();
    let waiting_queue = Arc::clone(&queue);
    let waiter = tokio::spawn(async move {
        waiting_queue
            .acquire(
                scope("tenant-a", "hot"),
                vec![2],
                64,
                start + Duration::from_secs(3),
                Arc::new(|| true),
                permit(),
            )
            .await
    });
    queued(&queue, 1).await;
    clock.elapsed_millis.store(101, Ordering::SeqCst);
    let result = tokio::time::timeout(Duration::from_secs(2), waiter)
        .await
        .unwrap()
        .unwrap();
    assert!(matches!(
        result,
        Err(QueueError::Rejected(EntityRejection::WaitExpired))
    ));
    assert_eq!(queue.lanes.snapshot().unwrap().active, 1);
    drop(owner);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn concurrent_cancellation_and_owner_retirement_reclaim_all_lane_metadata() {
    for iteration in 0..50_u8 {
        let queue = Arc::new(
            EntityQueue::new(limits(), Arc::new(latent_core::SystemActivationClock)).unwrap(),
        );
        let owner = queue
            .acquire(
                scope("tenant-a", "hot"),
                vec![iteration, 0],
                64,
                deadline(),
                Arc::new(|| true),
                permit(),
            )
            .await
            .unwrap();
        let mut waiters = Vec::new();
        for index in 1..=4_u8 {
            let queue = Arc::clone(&queue);
            waiters.push(tokio::spawn(async move {
                queue
                    .acquire(
                        scope("tenant-a", "hot"),
                        vec![iteration, index],
                        64,
                        deadline(),
                        Arc::new(|| true),
                        permit(),
                    )
                    .await
                    .map(drop)
            }));
        }
        queued(&queue, 4).await;
        waiters[0].abort();
        waiters[2].abort();
        drop(owner);
        for waiter in waiters {
            match tokio::time::timeout(Duration::from_secs(2), waiter)
                .await
                .unwrap()
            {
                Ok(Ok(())) => {}
                Err(error) if error.is_cancelled() => {}
                Ok(Err(error)) => panic!("live waiter failed after owner retirement: {error:?}"),
                Err(error) => panic!("waiter task failed: {error}"),
            }
        }
        let snapshot = queue.lanes.snapshot().unwrap();
        assert_eq!((snapshot.keys, snapshot.queued, snapshot.active), (0, 0, 0));
        assert_eq!(snapshot.retained_bytes(), 0);
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn cancellation_during_authority_check_cannot_release_selected_owner_early() {
    use std::sync::{mpsc, Barrier};

    let queue =
        Arc::new(EntityQueue::new(limits(), Arc::new(latent_core::SystemActivationClock)).unwrap());
    let (entered_send, entered_receive) = mpsc::sync_channel(1);
    let release = Arc::new(Barrier::new(2));
    let authority_release = Arc::clone(&release);
    let selected_queue = Arc::clone(&queue);
    let selected = tokio::spawn(async move {
        selected_queue
            .acquire(
                scope("tenant-a", "hot"),
                vec![1],
                64,
                deadline(),
                Arc::new(move || {
                    entered_send.send(()).unwrap();
                    authority_release.wait();
                    true
                }),
                permit(),
            )
            .await
    });
    entered_receive
        .recv_timeout(Duration::from_secs(2))
        .unwrap();
    selected.abort();
    assert_eq!(queue.lanes.snapshot().unwrap().active, 1);

    let next_queue = Arc::clone(&queue);
    let next = tokio::spawn(async move {
        next_queue
            .acquire(
                scope("tenant-a", "hot"),
                vec![2],
                64,
                deadline(),
                Arc::new(|| true),
                permit(),
            )
            .await
    });
    queued(&queue, 1).await;
    assert!(!next.is_finished());
    release.wait();
    let _ = selected.await;
    let owner = tokio::time::timeout(Duration::from_secs(2), next)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    drop(owner);
    let snapshot = queue.lanes.snapshot().unwrap();
    assert_eq!((snapshot.keys, snapshot.queued, snapshot.active), (0, 0, 0));
}

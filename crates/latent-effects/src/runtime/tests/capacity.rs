use super::*;
use latent_core::native_capacity::{
    NativeAdmissionClass, NativeReservationRequest, NATIVE_RESERVATION_METADATA_BYTES,
};

async fn observed_pending(owner: &DispatcherOwner, pending: u64) {
    with_watchdog(WATCHDOG, async {
        loop {
            let snapshot = owner.snapshot().unwrap();
            if snapshot.counts_observed_at_millis == 100 && snapshot.durable.pending == pending {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await;
}

#[tokio::test]
async fn ordinary_byte_pressure_rejects_before_claim_even_with_a_spare_shared_slot() {
    let bound = super::super::capacity::ATTEMPT_NATIVE_BYTES + NATIVE_RESERVATION_METADATA_BYTES;
    let mut limits = NativeCapacityLimits::default();
    limits.ordinary.slots = 2;
    limits.ordinary.bytes = bound;
    limits.ordinary.maximum_reservation_bytes = bound;
    let fixture = Fixture::with_capacity(NativeCapacityOwner::new(limits).unwrap()).await;
    let authority = fixture
        .seed(4, "tenant-a", "publication", profile("test.v1"))
        .await;
    let other = fixture
        .capacity
        .reserve(
            NativeAdmissionClass::Ordinary,
            NativeReservationRequest::default(),
            Instant::now() + WATCHDOG,
        )
        .unwrap();
    let (adapter, mut entered) = Adapter::new("test.v1", Some("tenant-a"));
    let mut owner = fixture
        .start(config(), vec![adapter.clone()], None)
        .await
        .unwrap();
    observed_pending(&owner, 1).await;
    assert_eq!(fixture.capacity.snapshot().unwrap().ordinary.slots, 1);
    assert_eq!(fixture.record(&authority).await.attempts(), 0);
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 0);
    let recovery = fixture
        .capacity
        .reserve(
            NativeAdmissionClass::Recovery,
            NativeReservationRequest::default(),
            Instant::now() + WATCHDOG,
        )
        .unwrap();
    assert_eq!(fixture.capacity.snapshot().unwrap().recovery.slots, 1);
    drop(other);
    owner.wake();
    let parked = event(&mut entered).await;
    assert_eq!(fixture.capacity.snapshot().unwrap().ordinary.bytes, bound);
    drop(recovery);
    owner.close();
    adapter.gates.release(parked.ticket.unwrap()).unwrap();
    assert!(
        owner
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    assert!(fixture.capacity.snapshot().unwrap().physically_retired());
    fixture.finish().await;
}

#[tokio::test]
async fn foreign_global_owner_cannot_claim_against_another_protected_store_capacity_binding() {
    let fixture = Fixture::new().await;
    let authority = fixture
        .seed(5, "tenant-a", "publication", profile("test.v1"))
        .await;
    let (adapter, _entered) = Adapter::new("test.v1", None);
    let mut owner = fixture
        .start_unbound(config(), vec![adapter.clone()], None)
        .await
        .unwrap();
    let foreign = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    owner.bind_native_capacity(&foreign).unwrap();
    owner.wake();
    with_watchdog(WATCHDOG, async {
        loop {
            if owner.snapshot().unwrap().failure == Some("configuration") {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await;
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 0);
    assert_eq!(fixture.record(&authority).await.attempts(), 0);
    assert!(foreign.snapshot().unwrap().physically_retired());
    let report = owner.shutdown(Instant::now() + WATCHDOG).await.unwrap();
    assert!(!report.clean && report.physically_retired);
    assert!(fixture.capacity.snapshot().unwrap().physically_retired());
    fixture.finish().await;
}

#[tokio::test]
async fn unbound_dispatcher_leaves_due_payload_unclaimed_until_exact_global_owner_is_installed() {
    let fixture = Fixture::new().await;
    let authority = fixture
        .seed(1, "tenant-a", "publication", profile("test.v1"))
        .await;
    let (adapter, mut entered) = Adapter::new("test.v1", Some("tenant-a"));
    let mut owner = fixture
        .start_unbound(config(), vec![adapter.clone()], None)
        .await
        .unwrap();
    observed_pending(&owner, 1).await;
    let pending = fixture.record(&authority).await;
    assert_eq!(pending.disposition(), Disposition::Pending);
    assert_eq!(pending.attempts(), 0);
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 0);
    assert_eq!(fixture.capacity.snapshot().unwrap().ordinary.slots, 0);
    owner.bind_native_capacity(&fixture.capacity).unwrap();
    owner.wake();
    let parked = event(&mut entered).await;
    assert_eq!(fixture.capacity.snapshot().unwrap().ordinary.slots, 1);
    assert!(
        fixture.capacity.snapshot().unwrap().ordinary.bytes
            >= super::super::capacity::ATTEMPT_NATIVE_BYTES
    );
    owner.pause();
    adapter.gates.release(parked.ticket.unwrap()).unwrap();
    assert!(
        owner
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    assert_eq!(fixture.capacity.snapshot().unwrap().ordinary.slots, 0);
    assert_eq!(fixture.record(&authority).await.attempts(), 1);
    fixture.finish().await;
}

#[tokio::test]
async fn full_shared_ordinary_slots_leave_effect_pending_and_preserve_actual_recovery_engine_lane()
{
    let mut limits = NativeCapacityLimits::default();
    limits.ordinary.slots = 1;
    let fixture = Fixture::with_capacity(NativeCapacityOwner::new(limits).unwrap()).await;
    let authority = fixture
        .seed(2, "tenant-a", "publication", profile("test.v1"))
        .await;
    let original = fixture
        .capacity
        .reserve(
            NativeAdmissionClass::Ordinary,
            NativeReservationRequest::default(),
            Instant::now() + WATCHDOG,
        )
        .unwrap();
    let (adapter, mut entered) = Adapter::new("test.v1", Some("tenant-a"));
    let mut owner = fixture
        .start(config(), vec![adapter.clone()], None)
        .await
        .unwrap();
    observed_pending(&owner, 1).await;
    assert_eq!(fixture.record(&authority).await.attempts(), 0);
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 0);
    let gates = Rendezvous::new(3);
    let storage = super::pressure::block_storage(&fixture, &gates);
    let recovery = Arc::new(
        fixture
            .capacity
            .reserve(
                NativeAdmissionClass::Recovery,
                NativeReservationRequest {
                    work_bytes: 128 * 1024,
                    ..NativeReservationRequest::default()
                },
                Instant::now() + WATCHDOG,
            )
            .unwrap(),
    );
    let pin = fixture
        .store
        .reserve_recovery_operation_retaining(recovery.clone())
        .unwrap();
    let key = effect_row_key(&authority.link().effect).unwrap();
    let retained = Arc::clone(&recovery);
    let recovered = fixture
        .store
        .with_store(StoreIoKind::RecoveryRead, 128 * 1024, move |store| {
            retained.with_live(|| ()).unwrap();
            let bytes = store.snapshot()?.get(&key)?.unwrap();
            Ok(EffectRecord::decode(&bytes).unwrap().attempts())
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    assert_eq!(recovered, 0);
    assert_eq!(fixture.capacity.snapshot().unwrap().ordinary.slots, 1);
    assert_eq!(fixture.capacity.snapshot().unwrap().recovery.slots, 1);
    pin.retire().await; // Retirement itself uses the physically reserved lane.
    drop(recovery);
    assert_eq!(fixture.capacity.snapshot().unwrap().recovery.slots, 0);
    for ticket in storage {
        gates.release(ticket).unwrap();
    }
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 0);
    drop(original);
    owner.wake();
    let parked = event(&mut entered).await;
    let charge = fixture.capacity.snapshot().unwrap().ordinary;
    assert_eq!(charge.slots, 1);
    assert_eq!(
        charge.bytes,
        super::super::capacity::ATTEMPT_NATIVE_BYTES + NATIVE_RESERVATION_METADATA_BYTES
    );
    owner.close();
    adapter.gates.release(parked.ticket.unwrap()).unwrap();
    assert!(
        owner
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    assert_eq!(
        fixture.record(&authority).await.disposition(),
        Disposition::ProviderAcknowledged
    );
    assert!(fixture.capacity.snapshot().unwrap().physically_retired());
    fixture.finish().await;
}

#[tokio::test]
async fn queued_attempt_keeps_original_native_deadline_and_never_claims_after_expiry() {
    use latent_core::test_support::TestClock;
    let clock = TestClock::new(100, Instant::now(), 1);
    let capacity =
        NativeCapacityOwner::with_clock(NativeCapacityLimits::default(), Arc::new(clock.clone()))
            .unwrap();
    let fixture = Fixture::with_capacity(capacity).await;
    let authority = fixture
        .seed(3, "tenant-a", "publication", profile("test.v1"))
        .await;
    let (adapter, _entered) = Adapter::new("test.v1", None);
    let mut owner = fixture
        .start(
            DispatcherConfig {
                start_paused: true,
                ..config()
            },
            vec![adapter.clone()],
            None,
        )
        .await
        .unwrap();
    let gates = Rendezvous::new(2);
    let (notice, receiver) = std::sync::mpsc::channel();
    for _ in 0..2 {
        let gates = gates.clone();
        let notice = notice.clone();
        drop(
            owner
                .jobs
                .submit(StoreIoKind::Read, 0, move |_| {
                    let (registration, mut work) = gates.track(()).unwrap();
                    work.commit(Stage::Entered).unwrap();
                    latent_core::test_support::block_on(with_watchdog(WATCHDOG, async {
                        let mut pause = Box::pin(work.pause());
                        PollProbe::default().pending(pause.as_mut());
                        notice
                            .send(gates.blocked(registration, Stage::Entered).unwrap())
                            .unwrap();
                        pause.await;
                    }));
                })
                .unwrap(),
        );
    }
    let tickets: Vec<_> = (0..2)
        .map(|_| receiver.recv_timeout(WATCHDOG).unwrap())
        .collect();
    owner.resume().unwrap();
    with_watchdog(WATCHDOG, async {
        loop {
            if owner.snapshot().unwrap().queued == 1
                && fixture.capacity.snapshot().unwrap().ordinary.slots == 1
            {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await;
    clock.advance(Duration::from_secs(11));
    assert_eq!(fixture.capacity.snapshot().unwrap().ordinary.slots, 1);
    for ticket in tickets {
        gates.release(ticket).unwrap();
    }
    with_watchdog(WATCHDOG, async {
        loop {
            if owner.snapshot().unwrap().accepted_effects == 0
                && fixture.capacity.snapshot().unwrap().ordinary.slots == 0
            {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await;
    assert_eq!(fixture.record(&authority).await.attempts(), 0);
    assert_eq!(
        fixture.record(&authority).await.disposition(),
        Disposition::Pending
    );
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 0);
    assert!(
        owner
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    fixture.finish().await;
}

#[tokio::test]
async fn ordinary_operation_pin_retains_original_native_buffer_until_actual_reserved_retirement() {
    use latent_core::native_capacity::NativeBufferClass;
    let fixture = Fixture::new().await;
    let reservation = fixture
        .capacity
        .reserve(
            NativeAdmissionClass::Ordinary,
            NativeReservationRequest {
                request_bytes: 1024,
                ..NativeReservationRequest::default()
            },
            Instant::now() + WATCHDOG,
        )
        .unwrap();
    let buffer = Arc::new(
        reservation
            .allocate_bytes(NativeBufferClass::Request, 1024)
            .unwrap(),
    );
    let pin = fixture
        .store
        .reserve_operation_retaining(buffer.clone())
        .unwrap();
    drop(buffer);
    drop(reservation);
    let gates = Rendezvous::new(3);
    let storage = super::pressure::block_storage(&fixture, &gates);
    let mut retirement = Box::pin(pin.retire());
    PollProbe::default().pending(retirement.as_mut());
    assert_eq!(fixture.capacity.snapshot().unwrap().ordinary.slots, 1);
    assert_eq!(
        fixture.capacity.snapshot().unwrap().ordinary.bytes,
        1024 + NATIVE_RESERVATION_METADATA_BYTES
    );
    for ticket in storage {
        gates.release(ticket).unwrap();
    }
    with_watchdog(WATCHDOG, retirement).await;
    assert!(fixture.capacity.snapshot().unwrap().physically_retired());
    fixture.finish().await;
}

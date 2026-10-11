use super::*;

#[tokio::test]
async fn live_provider_owner_blocks_alias_epoch_recovery_and_deadline_never_resends() {
    let fixture = Fixture::new().await;
    let authority = fixture
        .seed(1, "tenant-a", "old-publication", profile("test.v1"))
        .await;
    let (adapter, mut entered) = Adapter::new("test.v1", Some("tenant-a"));
    let mut dispatcher = fixture
        .start(config(), vec![adapter.clone()], None)
        .await
        .unwrap();
    let parked = event(&mut entered).await;
    assert_eq!(parked.effect, authority.link().effect);
    assert_eq!(
        fixture.record(&authority).await.disposition(),
        Disposition::Dispatching
    );
    assert_eq!(dispatcher.snapshot().unwrap().physical_owners, 1);
    let alias = fixture
        .start(config(), vec![adapter.clone()], Some((1, 100)))
        .await;
    assert!(matches!(
        alias,
        Err(DispatcherError::ProtectedStore(ProtectedStoreError::Store(
            latent_state::embedded::StoreError::Conflict
        )))
    ));
    fixture.clock.millis.store(70_000, Ordering::SeqCst);
    dispatcher.wake();
    let report = dispatcher.shutdown(Instant::now()).await.unwrap();
    assert!(!report.clean);
    assert!(!report.physically_retired);
    assert_eq!(report.snapshot.physical_owners, 1);
    assert!(report.snapshot.retained_attempt_bytes >= DispatcherConfig::ATTEMPT_BYTES);
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 1);
    assert_eq!(adapter.physical.load(Ordering::SeqCst), 1);
    assert_eq!(fixture.capacity.snapshot().unwrap().ordinary.slots, 1);
    adapter.gates.release(parked.ticket.unwrap()).unwrap();
    let late = with_watchdog(WATCHDOG, dispatcher.shutdown(Instant::now() + WATCHDOG))
        .await
        .unwrap();
    assert!(!late.clean);
    assert!(late.physically_retired, "{late:?}");
    assert!(fixture.capacity.snapshot().unwrap().physically_retired());
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 1);
    adapter.gates.require_retired(parked.registration).unwrap();
    assert_eq!(
        fixture.record(&authority).await.disposition(),
        Disposition::ProviderAcknowledged
    );
    fixture.finish().await;
}

#[tokio::test]
async fn dropped_dispatcher_waiter_keeps_provider_and_root_until_actual_record_and_cleanup() {
    let fixture = Fixture::new().await;
    let authority = fixture
        .seed(2, "tenant-a", "old-publication", profile("test.v1"))
        .await;
    let (adapter, mut entered) = Adapter::new("test.v1", Some("tenant-a"));
    let dispatcher = fixture
        .start(config(), vec![adapter.clone()], None)
        .await
        .unwrap();
    let parked = event(&mut entered).await;
    drop(dispatcher);
    assert_eq!(adapter.physical.load(Ordering::SeqCst), 1);
    assert!(matches!(
        fixture
            .start(config(), vec![adapter.clone()], Some((1, 100)))
            .await,
        Err(DispatcherError::ProtectedStore(ProtectedStoreError::Store(
            latent_state::embedded::StoreError::Conflict
        )))
    ));
    adapter.gates.release(parked.ticket.unwrap()).unwrap();
    wait_disposition(&fixture, &authority, Disposition::ProviderAcknowledged).await;
    with_watchdog(WATCHDOG, async {
        loop {
            match fixture.store.reserve_dispatcher() {
                Ok(job) => match job.await.unwrap() {
                    Ok(role) => {
                        role.retire().await;
                        break;
                    }
                    Err(ProtectedStoreError::Store(
                        latent_state::embedded::StoreError::Conflict,
                    )) => {}
                    Err(error) => panic!("unexpected registration failure {error:?}"),
                },
                Err(error) => panic!("unexpected admission failure {error:?}"),
            }
            tokio::task::yield_now().await;
        }
    })
    .await;
    adapter.gates.require_retired(parked.registration).unwrap();
    assert_eq!(fixture.authority.owners().unwrap().physical, 0);
    fixture.finish().await;
}

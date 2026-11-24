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

#[tokio::test]
async fn linked_effect_keeps_the_verified_reader_through_provider_and_receipt() {
    use latent_state::payload_references::{
        LocalPayloadIdentity, PayloadOwner, PayloadOwnerKind, PayloadReference,
        PreparedPayloadReferences,
    };
    use sha2::{Digest, Sha256};

    struct Reader(Arc<AtomicUsize>);
    impl Drop for Reader {
        fn drop(&mut self) {
            self.0.fetch_sub(1, Ordering::SeqCst);
        }
    }

    let fixture = Fixture::new().await;
    let authority = fixture
        .seed(1, "tenant-a", "old-publication", profile("test.v1"))
        .await;
    let scope = authority.scope();
    let reference = PayloadReference {
        owner: PayloadOwner {
            tenant: scope.tenant.clone(),
            namespace: scope.namespace.clone(),
            incarnation: scope.incarnation,
            kind: PayloadOwnerKind::Effect,
            identity: crate::effect_identity::parse(&authority.link().effect).unwrap(),
            generation: authority.link().attempt,
            format: authority.profile().payload_format.clone(),
        },
        payload: LocalPayloadIdentity {
            tenant: scope.tenant.clone(),
            provider: "blob-a".into(),
            provider_epoch: 1,
            provider_configuration: [17; 32],
            blob_namespace: "blobs".into(),
            digest: Sha256::digest(b"committed payload 1").into(),
            size: authority.payload_bytes(),
            media_type: "application/octet-stream".into(),
        },
    };
    let exact = reference.clone();
    fixture
        .store
        .with_store(StoreIoKind::Write, 1024 * 1024, move |store| {
            let view = store.snapshot()?;
            let refs = PreparedPayloadReferences::prepare(&view, &[(None, Some(reference))])?;
            let mut plan = AtomicBatch::default();
            refs.append_to(&mut plan)?;
            drop(view);
            store.apply(plan)?;
            Ok(())
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();

    let (adapter, mut entered) = Adapter::new("test.v1", Some("tenant-a"));
    let reader_count = Arc::new(AtomicUsize::new(0));
    let current = Arc::clone(&reader_count);
    let verifier: Arc<DispatchPayloadVerifier> = Arc::new(move |view, key, bytes, checkpoint| {
        checkpoint()?;
        latent_state::payload_references::validate_row(view, key, bytes)?;
        assert_eq!(PayloadReference::decode(bytes)?, exact);
        assert_eq!(current.fetch_add(1, Ordering::SeqCst), 0);
        Ok(Box::new(Reader(Arc::clone(&current))) as DispatchPayloadPin)
    });
    let mut dispatcher = DispatcherOwner::start_with_startup_suppression(
        config(),
        fixture.store.clone(),
        fixture.authority.clone(),
        vec![adapter.clone()],
        fixture.clock.clone(),
        None,
        tokio::runtime::Handle::current(),
        Some(verifier),
    )
    .await
    .unwrap();
    dispatcher.bind_native_capacity(&fixture.capacity).unwrap();
    dispatcher.release_startup().unwrap();

    let parked = event(&mut entered).await;
    assert_eq!(parked.effect, authority.link().effect);
    assert_eq!(reader_count.load(Ordering::SeqCst), 1);
    assert_eq!(
        fixture.record(&authority).await.disposition(),
        Disposition::Dispatching
    );
    adapter.gates.release(parked.ticket.unwrap()).unwrap();
    wait_disposition(&fixture, &authority, Disposition::ProviderAcknowledged).await;
    let report = dispatcher
        .shutdown(Instant::now() + WATCHDOG)
        .await
        .unwrap();
    assert!(report.clean && report.physically_retired);
    assert_eq!(reader_count.load(Ordering::SeqCst), 0);
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 1);
    fixture.finish().await;
}

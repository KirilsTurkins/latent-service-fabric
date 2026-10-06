use super::*;

#[tokio::test]
async fn persisted_owner_history_requires_external_checkpoint_before_new_epoch_or_claim() {
    let fixture = Fixture::new().await;
    let authority = fixture
        .seed(3, "tenant-a", "old-publication", profile("test.v1"))
        .await;
    let (adapter, mut entered) = Adapter::new("test.v1", None);
    let mut dispatcher = fixture
        .start(config(), vec![adapter.clone()], None)
        .await
        .unwrap();
    event(&mut entered).await;
    wait_disposition(&fixture, &authority, Disposition::ProviderAcknowledged).await;
    assert!(
        dispatcher
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    assert!(matches!(
        fixture.start(config(), vec![adapter.clone()], None).await,
        Err(DispatcherError::CheckpointRequired)
    ));
    let mut replacement = fixture
        .start(config(), vec![adapter.clone()], Some((1, 100)))
        .await
        .unwrap();
    assert_eq!(
        replacement
            .required_profile_page(None, 1, 4096)
            .await
            .unwrap()
            .rows[0]
            .command,
        "command-3"
    );
    assert!(
        replacement
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 1);
    fixture.finish().await;
    let reopened = Arc::new(Fixture::open(fixture.config.clone()).await);
    reopened.bind_native_capacity(&fixture.capacity).unwrap();
    let mut after_restart = DispatcherOwner::start(
        config(),
        Arc::clone(&reopened),
        fixture.authority.clone(),
        vec![adapter.clone()],
        fixture.clock.clone(),
        Some((2, 100)),
    )
    .await
    .unwrap();
    after_restart
        .bind_native_capacity(&fixture.capacity)
        .unwrap();
    assert!(
        after_restart
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 1);
    let deadline = Instant::now() + WATCHDOG;
    assert!(
        reopened
            .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
            .unwrap()
            .await
            .clean
    );
}

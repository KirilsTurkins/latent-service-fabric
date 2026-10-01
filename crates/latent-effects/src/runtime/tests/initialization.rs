use super::*;

#[tokio::test]
async fn fresh_native_checkpoint_starts_once_and_reopen_preserves_original_owner_floor() {
    let fixture = Fixture::new().await;
    let mut original = fixture
        .start(config(), vec![], Some((1, 100)))
        .await
        .unwrap();
    let source = original.command_admission_source();
    let work = source.capture().unwrap();
    assert_eq!(work.owner_epoch(), 1);
    assert_eq!(work.captured_time().unix_millis, 100);
    work.retire();
    assert!(
        original
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    assert!(source.capture().is_err());
    fixture.finish().await;
    let reopened = Arc::new(Fixture::open(fixture.config.clone()).await);
    fixture.clock.millis.store(101, Ordering::SeqCst);
    let mut replacement = DispatcherOwner::start(
        config(),
        Arc::clone(&reopened),
        fixture.authority.clone(),
        vec![],
        fixture.clock.clone(),
        Some((1, 100)),
    )
    .await
    .unwrap();
    let work = replacement.command_admission().unwrap();
    assert_eq!(work.owner_epoch(), 2);
    assert_eq!(work.captured_time().unix_millis, 101);
    work.retire();
    assert!(
        replacement
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    let deadline = Instant::now() + WATCHDOG;
    assert!(
        reopened
            .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
            .unwrap()
            .await
            .clean
    );
    reopened.reap_retired_threads().unwrap();
}

#[tokio::test]
async fn fresh_native_checkpoint_refuses_higher_epoch_future_floor_and_discontinuity() {
    for changed in 0..3 {
        let fixture = Fixture::new().await;
        let checkpoint = match changed {
            0 => (2, 100),
            1 => (1, 101),
            _ => {
                fixture.clock.continuous.store(false, Ordering::SeqCst);
                (1, 100)
            }
        };
        let error = fixture
            .start(config(), vec![], Some(checkpoint))
            .await
            .err()
            .unwrap();
        if changed == 2 {
            assert!(matches!(
                error,
                DispatcherError::Authority(AuthorityError::ClockDiscontinuity)
            ));
        } else {
            assert!(matches!(
                error,
                DispatcherError::Store(crate::dispatch_store::DispatchStoreError::StaleEpoch)
            ));
        }
        assert_eq!(fixture.authority.owners().unwrap().physical, 0);
        fixture.finish().await;
    }
}

#[tokio::test]
async fn reopened_missing_dispatch_owner_refuses_initial_checkpoint_even_with_empty_table() {
    let fixture = Fixture::new().await;
    let mut original = fixture
        .start(config(), vec![], Some((1, 100)))
        .await
        .unwrap();
    assert!(
        original
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    let owner_key = latent_state::embedded::RowKey {
        family: latent_state::embedded::Family::Maintenance,
        key: b"dispatch-owner-v1\0".to_vec(),
    };
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: owner_key,
                value: None,
            }],
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    fixture.finish().await;
    let reopened = Arc::new(Fixture::open(fixture.config.clone()).await);
    assert!(reopened
        .with_store(StoreIoKind::Read, 1024, |store| store
            .snapshot()?
            .is_empty())
        .unwrap()
        .await
        .unwrap()
        .unwrap());
    let error = DispatcherOwner::start(
        config(),
        Arc::clone(&reopened),
        fixture.authority.clone(),
        vec![],
        fixture.clock.clone(),
        Some((1, 100)),
    )
    .await
    .err()
    .unwrap();
    assert!(matches!(
        error,
        DispatcherError::Store(crate::dispatch_store::DispatchStoreError::StaleEpoch)
    ));
    let deadline = Instant::now() + WATCHDOG;
    assert!(
        reopened
            .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
            .unwrap()
            .await
            .clean
    );
    reopened.reap_retired_threads().unwrap();
}

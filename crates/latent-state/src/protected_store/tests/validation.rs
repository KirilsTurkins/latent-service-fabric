use super::*;

#[test]
fn unsupported_nonempty_logical_families_fail_readiness_without_data_reset() {
    let (_root, config) = fixture();
    let owner = start(config.clone());
    wait(owner.apply(batch(b"unknown-logical-record")).unwrap())
        .unwrap()
        .unwrap();
    assert!(finish(&owner).clean);
    assert_eq!(
        failed_start(config.clone()),
        ProtectedStoreError::Store(StoreError::UnsupportedFormat)
    );
    let reopened = start(config);
    let view = wait(reopened.open_view().unwrap()).unwrap().unwrap();
    let (view, values) = read(&reopened, view);
    assert_eq!(values, vec![Some(b"unknown-logical-record".to_vec()); 3]);
    drop(view);
    assert!(finish(&reopened).clean);
}

#[test]
fn bounded_startup_codec_validation_visits_every_row_across_page_continuations() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    let (_root, config) = fixture();
    let owner = start(config.clone());
    for range in [0..256, 256..300] {
        wait(
            owner
                .apply(AtomicBatch {
                    expectations: vec![],
                    mutations: range
                        .map(|index| RowMutation {
                            key: key(Family::State, &format!("row-{index:03}")),
                            value: Some(b"encoded".to_vec()),
                        })
                        .collect(),
                })
                .unwrap(),
        )
        .unwrap()
        .unwrap();
    }
    assert!(finish(&owner).clean);
    let seen = Arc::new(AtomicUsize::new(0));
    let validator_seen = Arc::clone(&seen);
    let startup = ProtectedStoreOwner::start_validated(config.clone(), 0, move |key, value| {
        assert_eq!(key.family, Family::State);
        assert_eq!(value, b"encoded");
        validator_seen.fetch_add(1, Ordering::SeqCst);
        Ok(())
    })
    .unwrap();
    let reopened = wait(startup).unwrap();
    assert_eq!(seen.load(Ordering::SeqCst), 300);
    assert!(finish(&reopened).clean);
    let mut denied = Box::pin(
        ProtectedStoreOwner::start_validated(config, 0, |_, _| Err(StoreError::Corrupt)).unwrap(),
    );
    assert!(matches!(
        wait(denied.as_mut()),
        Err(ProtectedStoreError::Store(StoreError::Corrupt))
    ));
    let report = wait(
        denied
            .drain_async(Instant::now() + WATCHDOG, std::future::pending())
            .unwrap(),
    );
    assert!(!report.clean);
    assert!(report.snapshot.physically_retired());
}

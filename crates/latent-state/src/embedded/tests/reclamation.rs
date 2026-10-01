use super::*;

#[test]
fn reclamation_waits_for_actual_native_view_drop_even_after_snapshot_expiry() {
    let dir = tempfile::tempdir().unwrap();
    let store =
        EmbeddedStore::open_file(file(&dir.path().join("store.redb")), StoreLimits::default())
            .unwrap();
    store.apply(bundle("retained")).unwrap();
    let mut reader = store.snapshot().unwrap();
    reader.opened = Instant::now().checked_sub(Duration::from_secs(61)).unwrap();
    assert_eq!(
        reader.get(&key(Family::State, "command-1")),
        Err(StoreError::SnapshotExpired)
    );
    let deletion = || AtomicBatch {
        expectations: vec![ExpectedRow {
            key: key(Family::State, "command-1"),
            value: Some(b"retained".to_vec()),
        }],
        mutations: vec![RowMutation {
            key: key(Family::State, "command-1"),
            value: None,
        }],
    };
    assert_eq!(
        store.apply_reclamation_fenced(deletion(), || Ok::<_, StoreError>(())),
        Err(FencedStoreError::Store(StoreError::Capacity)),
    );
    assert_eq!(store.live_views(), 1);
    drop(reader);
    store
        .apply_reclamation_fenced(deletion(), || {
            assert!(matches!(store.snapshot(), Err(StoreError::Capacity)));
            assert_eq!(store.live_views(), 0);
            Ok::<_, StoreError>(())
        })
        .unwrap();
    assert_eq!(
        store
            .snapshot()
            .unwrap()
            .get(&key(Family::State, "command-1")),
        Ok(None)
    );
}

#[test]
fn failed_reclamation_fence_keeps_rows_and_reopens_original_snapshot_admission() {
    let dir = tempfile::tempdir().unwrap();
    let store =
        EmbeddedStore::open_file(file(&dir.path().join("store.redb")), StoreLimits::default())
            .unwrap();
    store.apply(bundle("original")).unwrap();
    assert_eq!(
        store.apply_reclamation_fenced(bundle("replacement"), || {
            assert!(matches!(store.snapshot(), Err(StoreError::Capacity)));
            Err::<(), _>(StoreError::Conflict)
        }),
        Err(FencedStoreError::Fence(StoreError::Conflict))
    );
    let reader = store.snapshot().unwrap();
    assert_eq!(
        reader.get(&key(Family::State, "command-1")),
        Ok(Some(b"original".to_vec()))
    );
    assert_eq!(store.live_views(), 1);
}

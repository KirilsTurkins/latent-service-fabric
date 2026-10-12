use super::*;

#[test]
fn finite_engine_qualification_records_actual_commit_conflict_snapshot_and_recovery_costs() {
    use latent_test_process::{CurrentProcessProbe, ResourceProbe};
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("measured.redb");
    let limits = StoreLimits {
        maximum_view_age: Duration::from_millis(20),
        ..StoreLimits::default()
    };
    let start = Instant::now();
    let mut store = EmbeddedStore::open_file(file(&path), limits).unwrap();
    let initialize = start.elapsed().as_micros();
    let start = Instant::now();
    for index in 0..32 {
        let mut batch = bundle("value");
        for row in &mut batch.mutations {
            row.key.key = format!("command-{index:02}").into_bytes();
        }
        store.apply(batch).unwrap();
    }
    let sequential = start.elapsed().as_micros();
    let mut snapshot = store.snapshot().unwrap();
    let start = Instant::now();
    store.apply(bundle("new")).unwrap();
    let snapshot_writer = start.elapsed().as_micros();
    // Snapshot consistency and its unchanged 20 ms age boundary are distinct
    // from the real writer duration, which may exceed 20 ms on a loaded host.
    let row = key(Family::Command, "command-1");
    assert_eq!(snapshot.get_at_age(&row, Duration::ZERO), Ok(None));
    assert_eq!(snapshot.get_at_age(&row, limits.maximum_view_age), Ok(None));
    let conflict = AtomicBatch {
        expectations: vec![ExpectedRow {
            key: key(Family::Command, "command-1"),
            value: None,
        }],
        mutations: bundle("stale").mutations,
    };
    let start = Instant::now();
    assert_eq!(store.apply(conflict), Err(StoreError::Conflict));
    let conflict_cost = start.elapsed().as_micros();
    assert_eq!(
        snapshot.get_at_age(&row, limits.maximum_view_age + Duration::from_nanos(1)),
        Err(StoreError::SnapshotExpired)
    );
    snapshot.opened -= limits.maximum_view_age + Duration::from_nanos(1);
    assert_eq!(snapshot.get(&row), Err(StoreError::SnapshotExpired));
    assert_eq!(store.compact(), Err(StoreError::Capacity));
    drop(snapshot);
    let start = Instant::now();
    store.compact().unwrap();
    let compact = start.elapsed().as_micros();
    drop(store);
    let start = Instant::now();
    let backup = dir.path().join("backup.redb");
    let backup_bytes = std::fs::copy(&path, &backup).unwrap();
    file(&backup).sync_all().unwrap();
    let backup_cost = start.elapsed().as_micros();
    let start = Instant::now();
    let restored = EmbeddedStore::open_file(file(&backup), limits).unwrap();
    let reopen = start.elapsed().as_micros();
    assert_eq!(
        restored
            .snapshot()
            .unwrap()
            .get_at_age(&row, Duration::ZERO),
        Ok(Some(b"new".to_vec()))
    );
    let resources = CurrentProcessProbe.capture().unwrap();
    println!(
        "LSF_STORE_QUALIFICATION {}",
        serde_json::json!({
            "schemaVersion":"latent.storage.qualification.v1","engine":"redb","engineVersion":"4.3.0",
            "durability":"immediate","cacheBytes":limits.cache_bytes,"sequentialCommits":32,
            "initializeMicros":initialize,"sequentialMicros":sequential,"writerWithReadViewMicros":snapshot_writer,
            "conflictMicros":conflict_cost,"compactionMicros":compact,"closedBackupMicros":backup_cost,
            "backupBytes":backup_bytes,"reopenMicros":reopen,"snapshotAgeBoundMillis":20,
            "snapshotAgeObservation":"controlled-age-boundary",
            "resources":resources,"processCrashTests":2,"powerLossQualified":false,
            "productionStoreOwnerQualified":false,"networkFilesystemQualified":false
        })
    );
}

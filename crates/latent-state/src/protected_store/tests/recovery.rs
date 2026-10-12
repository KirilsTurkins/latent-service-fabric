use super::*;
use redb::ReadableDatabase;

#[test]
fn malformed_and_unsupported_formats_fail_readiness_without_empty_replacement() {
    let (root, config) = fixture();
    let path = root.path().join(&config.file_name);
    fs::write(&path, b"malformed-existing-store").unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
    assert_eq!(
        failed_start(config.clone()),
        ProtectedStoreError::Store(StoreError::Corrupt)
    );
    assert_eq!(fs::read(&path).unwrap(), b"malformed-existing-store");
    fs::remove_file(&path).unwrap(); // exclusively owned failed fixture, fully retired
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(&path)
        .unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
    let db = redb::Database::builder().create_file(file).unwrap();
    let tx = db.begin_write().unwrap();
    {
        let mut table = tx
            .open_table(redb::TableDefinition::<&str, &[u8]>::new("format"))
            .unwrap();
        table
            .insert("schema", b"latent.transaction-store.v999".as_slice())
            .unwrap();
    }
    tx.commit().unwrap();
    drop(db);
    assert_eq!(
        failed_start(config),
        ProtectedStoreError::Store(StoreError::UnsupportedFormat)
    );
    let db = redb::Database::builder().open(path).unwrap();
    let read = db.begin_read().unwrap();
    let table = read
        .open_table(redb::TableDefinition::<&str, &[u8]>::new("format"))
        .unwrap();
    assert_eq!(
        table.get("schema").unwrap().unwrap().value(),
        b"latent.transaction-store.v999"
    );
}

#[test]
fn unsupported_filesystem_and_unsafe_configuration_never_create_a_store() {
    let (_root, mut config) = fixture();
    config.file_name = "../escape".into();
    assert!(matches!(
        ProtectedStoreOwner::start(config.clone()),
        Err(ProtectedStoreError::InvalidConfiguration)
    ));
    config.file_name = "store.redb".into();
    config.io.workers = 33;
    assert!(matches!(
        ProtectedStoreOwner::start(config),
        Err(ProtectedStoreError::InvalidConfiguration)
    ));
    // Linux tmpfs is explicitly outside the qualified ext4 local profile.
    let unsupported = tempfile::tempdir_in("/dev/shm").unwrap();
    fs::set_permissions(unsupported.path(), fs::Permissions::from_mode(0o700)).unwrap();
    let mut config = ProtectedStoreConfig::bounded_linux(unsupported.path().to_path_buf());
    config.create_if_missing = true;
    assert_eq!(
        failed_start(config.clone()),
        ProtectedStoreError::UnsupportedFilesystem
    );
    assert!(!unsupported.path().join(config.file_name).exists());
}

#[test]
fn protected_root_permissions_and_substituted_paths_gate_initialization_and_live_jobs() {
    let (root, config) = fixture();
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o777)).unwrap();
    assert_eq!(
        failed_start(config.clone()),
        ProtectedStoreError::UnsafeRoot
    );
    assert!(!root.path().join(&config.file_name).exists());
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).unwrap();
    let owner = start(config.clone());
    fs::set_permissions(
        root.path().join(&config.file_name),
        fs::Permissions::from_mode(0o644),
    )
    .unwrap();
    assert_eq!(
        wait(owner.apply(batch(b"denied")).unwrap()).unwrap(),
        Err(ProtectedStoreError::UnsafeRoot)
    );
    assert!(owner.snapshot().unwrap().quarantined);
    assert!(!finish(&owner).clean);
    fs::set_permissions(
        root.path().join(&config.file_name),
        fs::Permissions::from_mode(0o600),
    )
    .unwrap();
    let reopened = start(config);
    let view = wait(reopened.open_view().unwrap()).unwrap().unwrap();
    let (view, values) = read(&reopened, view);
    assert_eq!(values, vec![None; 3]);
    drop(view);
    assert!(finish(&reopened).clean);
}

#[test]
fn exclusive_root_owner_failure_keeps_first_engine_usable_and_data_intact() {
    let (_root, config) = fixture();
    let first = start(config.clone());
    assert!(matches!(
        failed_start(config.clone()),
        ProtectedStoreError::Store(_)
    ));
    let mut alternate = config.clone();
    alternate.file_name = "second-database.redb".into();
    assert_eq!(
        failed_start(alternate.clone()),
        ProtectedStoreError::Store(StoreError::Unavailable)
    );
    assert!(!alternate.root.join(alternate.file_name).exists());
    wait(first.apply(batch(b"sole-owner")).unwrap())
        .unwrap()
        .unwrap();
    assert!(finish(&first).clean);
    let reopened = start(config);
    let view = wait(reopened.open_view().unwrap()).unwrap().unwrap();
    let (view, values) = read(&reopened, view);
    assert_eq!(values, vec![Some(b"sole-owner".to_vec()); 3]);
    drop(view);
    assert!(finish(&reopened).clean);
}

#[test]
fn actual_backend_sync_failure_is_uncertain_gated_and_recovers_one_atomic_bundle() {
    let (_root, config) = fixture();
    let owner = start(config.clone());
    wait(
        owner
            .ready
            .submit(StoreIoKind::Read, 0, |store| store.status.fail_next_sync())
            .unwrap(),
    )
    .unwrap();
    assert_eq!(
        wait(owner.apply(batch(b"uncertain")).unwrap()).unwrap(),
        Err(ProtectedStoreError::Store(StoreError::CommitUncertain))
    );
    assert!(owner.snapshot().unwrap().quarantined);
    assert!(matches!(
        owner.apply(batch(b"forbidden")),
        Err(ProtectedStoreError::Store(StoreError::CommitUncertain))
    ));
    let report = finish(&owner);
    assert!(!report.clean);
    assert!(report.snapshot.physically_retired());
    let recovered = start(config);
    let view = wait(recovered.open_view().unwrap()).unwrap().unwrap();
    let (view, values) = read(&recovered, view);
    assert!(values.iter().all(|value| value == &values[0]));
    assert!(values[0].is_none() || values[0] == Some(b"uncertain".to_vec()));
    drop(view);
    assert!(finish(&recovered).clean);
}

#[test]
fn physical_file_ceiling_refuses_growth_and_never_claims_aborted_commit() {
    let (root, mut config) = fixture();
    config.maximum_file_bytes = 2 * 1024 * 1024;
    let owner = start(config.clone());
    let result = wait(owner.apply(batch(&vec![3; 1024 * 1024])).unwrap()).unwrap();
    assert!(matches!(
        result,
        Err(ProtectedStoreError::Store(
            StoreError::Unavailable | StoreError::CommitUncertain
        ))
    ));
    assert!(owner.snapshot().unwrap().quarantined);
    assert!(
        fs::metadata(root.path().join(config.file_name))
            .unwrap()
            .len()
            <= config.maximum_file_bytes
    );
    assert!(!finish(&owner).clean);
}

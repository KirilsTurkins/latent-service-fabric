use super::*;
use crate::embedded::format::{self as disk_format, Checkpoint, State};
use redb::ReadableTableMetadata;

fn native_builder() -> redb::Builder {
    let mut builder = Database::builder();
    builder.set_cache_size(StoreLimits::default().cache_bytes);
    builder
}

fn legacy(path: &std::path::Path) -> Database {
    let db = native_builder().create_file(file(path)).unwrap();
    disk_format::initialize(&db).unwrap();
    let mut tx = db.begin_write().unwrap();
    tx.set_durability(Durability::Immediate).unwrap();
    {
        let mut rows = tx.open_table(ROWS).unwrap();
        for family in [Family::State, Family::Command, Family::Outbox] {
            let key = key(family, "command-1")
                .encoded(StoreLimits::default())
                .unwrap();
            rows.insert(key.as_slice(), b"original".as_slice()).unwrap();
        }
    }
    tx.commit().unwrap();
    db
}

fn description(db: &Database) -> Vec<(String, Vec<u8>)> {
    let tx = db.begin_read().unwrap();
    let meta = tx.open_table(META).unwrap();
    meta.iter()
        .unwrap()
        .map(|row| {
            let (key, value) = row.unwrap();
            assert!(key.value().len() <= 128 && value.value().len() <= 4096);
            (key.value().to_owned(), value.value().to_vec())
        })
        .collect()
}

#[test]
fn v1_upgrade_preserves_original_rows_and_existing_read_views() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("store.redb");
    let store = EmbeddedStore {
        db: RwLock::new(legacy(&path)),
        file_status: None,
        limits: StoreLimits::default(),
        views: Arc::new(AtomicUsize::new(0)),
        quarantined: AtomicBool::new(false),
        reclamation: AtomicBool::new(false),
    };
    assert_eq!(
        disk_format::inspect(&store.database().unwrap()),
        Ok(State::Legacy)
    );
    let original = store.snapshot().unwrap();
    let mut checkpoints = Vec::with_capacity(2);
    disk_format::upgrade(&store.database().unwrap(), &mut |stage| {
        checkpoints.push(stage)
    })
    .unwrap();
    assert_eq!(
        checkpoints,
        vec![
            Checkpoint::UpgradeIntentDurable,
            Checkpoint::CurrentSchemaDurable
        ]
    );
    assert_eq!(
        disk_format::inspect(&store.database().unwrap()),
        Ok(State::Current)
    );
    let published = description(&store.database().unwrap());
    disk_format::upgrade(&store.database().unwrap(), &mut |_| {
        panic!("current format attempted another upgrade")
    })
    .unwrap();
    assert_eq!(description(&store.database().unwrap()), published);
    let current = store.snapshot().unwrap();
    for family in [Family::State, Family::Command, Family::Outbox] {
        assert_eq!(
            original.get(&key(family, "command-1")),
            Ok(Some(b"original".to_vec()))
        );
        assert_eq!(
            current.get(&key(family, "command-1")),
            Ok(Some(b"original".to_vec()))
        );
    }
    assert_eq!(store.views.load(Ordering::Acquire), 2);
    drop((original, current));
    assert_eq!(store.views.load(Ordering::Acquire), 0);
    drop(store);
    let reopened = EmbeddedStore::open_file(file(&path), StoreLimits::default()).unwrap();
    assert_eq!(
        disk_format::inspect(&reopened.database().unwrap()),
        Ok(State::Current)
    );
    assert!(description(&reopened.database().unwrap())
        .iter()
        .all(|(key, _)| key != "upgrade"));
}

#[test]
fn malformed_inconsistent_and_unknown_upgrade_metadata_refuses_without_rewriting_rows() {
    for variant in 0..9 {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("store.redb");
        let db = legacy(&path);
        let tx = db.begin_write().unwrap();
        {
            let mut meta = tx.open_table(META).unwrap();
            match variant {
                0 => {
                    meta.insert("upgrade", b"wrong-stage".as_slice()).unwrap();
                }
                1 => {
                    meta.insert("schema", disk_format::V2).unwrap();
                }
                2 => {
                    meta.insert("schema", disk_format::V2).unwrap();
                    meta.insert("record-layout", disk_format::LAYOUT).unwrap();
                    meta.insert("upgrade", disk_format::UPGRADE).unwrap();
                }
                3 => {
                    meta.insert("record-layout", disk_format::LAYOUT).unwrap();
                }
                4 => {
                    meta.insert("schema", disk_format::V2).unwrap();
                    meta.insert("record-layout", b"unknown-layout".as_slice())
                        .unwrap();
                }
                5 => {
                    meta.insert("schema", b"latent.transaction-store.v999".as_slice())
                        .unwrap();
                }
                6 => {
                    meta.insert("upgrade", vec![0u8; 4096].as_slice()).unwrap();
                }
                7 => {
                    meta.insert("unrecognized-progress", b"retain".as_slice())
                        .unwrap();
                }
                8 => {
                    meta.insert("schema", disk_format::V2).unwrap();
                    meta.insert("record-layout", disk_format::LAYOUT).unwrap();
                    meta.insert("upgrade", disk_format::UPGRADE).unwrap();
                    meta.insert("unrecognized-progress", b"retain".as_slice())
                        .unwrap();
                }
                _ => unreachable!(),
            }
        }
        tx.commit().unwrap();
        let original = description(&db);
        drop(db);
        assert!(matches!(
            EmbeddedStore::open_file(file(&path), StoreLimits::default()),
            Err(StoreError::Corrupt | StoreError::UnsupportedFormat)
        ));
        let db = native_builder().create_file(file(&path)).unwrap();
        assert_eq!(description(&db), original);
        let tx = db.begin_read().unwrap();
        let rows = tx.open_table(ROWS).unwrap();
        assert_eq!(rows.len().unwrap(), 3);
        for row in rows.iter().unwrap() {
            assert_eq!(row.unwrap().1.value(), b"original");
        }
    }
}

#[test]
fn original_row_ceiling_is_checked_before_any_upgrade_intent() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("store.redb");
    drop(legacy(&path));
    assert!(matches!(
        EmbeddedStore::open_file(
            file(&path),
            StoreLimits {
                maximum_rows: 2,
                ..StoreLimits::default()
            }
        ),
        Err(StoreError::Capacity)
    ));
    let db = native_builder().create_file(file(&path)).unwrap();
    assert_eq!(disk_format::inspect(&db), Ok(State::Legacy));
    assert_eq!(
        description(&db),
        vec![("schema".into(), disk_format::V1.to_vec())]
    );
}

#[test]
fn owned_format_upgrade_child() {
    let Ok(root) = std::env::var("LATENT_FORMAT_CHILD_ROOT") else {
        return;
    };
    let wanted = std::env::var("LATENT_FORMAT_CHILD_STAGE").unwrap();
    let path = std::path::Path::new(&root).join("store.redb");
    let was_empty = path.metadata().map_or(true, |metadata| metadata.len() == 0);
    let db = native_builder().create_file(file(&path)).unwrap();
    EmbeddedStore::open_database_with_checkpoint(db, StoreLimits::default(), was_empty, |stage| {
        let name = match stage {
            Checkpoint::NewEngineOpened => "engine",
            Checkpoint::InitialSchemaDurable => "seed",
            Checkpoint::UpgradeIntentDurable => "intent",
            Checkpoint::CurrentSchemaDurable => "current",
        };
        if name == wanted {
            use std::io::Write;
            println!("STORE_FORMAT_READY");
            std::io::stdout().flush().unwrap();
            // Same finite barrier as the original owned commit-child test.
            std::thread::park_timeout(Duration::from_secs(30));
        }
    })
    .unwrap();
}

async fn interrupt(path: &std::path::Path, stage: &str) {
    use latent_test_process::process::{OwnedProcess, ProcessLimits};
    let mut command = std::process::Command::new(std::env::current_exe().unwrap());
    command
        .args([
            "--exact",
            "embedded::tests::format::owned_format_upgrade_child",
            "--nocapture",
        ])
        .env("LATENT_FORMAT_CHILD_ROOT", path)
        .env("LATENT_FORMAT_CHILD_STAGE", stage);
    let child = OwnedProcess::spawn(command, ProcessLimits::default()).unwrap();
    let deadline = Instant::now() + Duration::from_secs(4);
    loop {
        let stdout = child.stdout_snapshot().unwrap();
        if stdout
            .windows(b"STORE_FORMAT_READY".len())
            .any(|bytes| bytes == b"STORE_FORMAT_READY")
        {
            break;
        }
        assert!(
            Instant::now() < deadline,
            "owned child did not reach actual format boundary: {stage}"
        );
        tokio::time::sleep(Duration::from_millis(5)).await;
    }
    let retired = child.terminate().await.unwrap();
    assert!(!retired.status.success());
}

#[tokio::test]
async fn interrupted_first_creation_refuses_unseeded_engine_and_recovers_durable_stages() {
    for stage in ["engine", "seed", "intent", "current"] {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("store.redb");
        interrupt(directory.path(), stage).await;
        let original_bytes = path.metadata().unwrap().len();
        assert!(original_bytes > 0);
        if stage == "engine" {
            // Native redb owns a real header, but no trusted application schema
            // was committed. Existing failed bytes must never become an empty
            // Ready store merely because its format table is absent.
            assert!(matches!(
                EmbeddedStore::open_file(file(&path), StoreLimits::default()),
                Err(StoreError::UnsupportedFormat)
            ));
            let db = native_builder().create_file(file(&path)).unwrap();
            assert!(db.begin_read().unwrap().open_table(META).is_err());
            assert!(path.metadata().unwrap().len() > 0);
        } else {
            let store = EmbeddedStore::open_file(file(&path), StoreLimits::default()).unwrap();
            assert_eq!(
                disk_format::inspect(&store.database().unwrap()),
                Ok(State::Current)
            );
            assert!(description(&store.database().unwrap())
                .iter()
                .all(|(key, _)| key != "upgrade"));
            let page = store
                .snapshot()
                .unwrap()
                .scan_after(Family::State, b"", None, 8, 1024)
                .unwrap();
            assert!(page.rows.is_empty());
            assert!(page.resume.is_none());
        }
    }
}

#[tokio::test]
async fn interrupted_v1_upgrade_reopens_same_business_rows_and_never_downgrades() {
    for stage in ["intent", "current"] {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("store.redb");
        drop(legacy(&path));
        interrupt(directory.path(), stage).await;
        let db = native_builder().create_file(file(&path)).unwrap();
        assert_eq!(
            disk_format::inspect(&db),
            Ok(if stage == "intent" {
                State::UpgradePending
            } else {
                State::Current
            })
        );
        drop(db);
        let store = EmbeddedStore::open_file(file(&path), StoreLimits::default()).unwrap();
        assert_eq!(
            disk_format::inspect(&store.database().unwrap()),
            Ok(State::Current)
        );
        let view = store.snapshot().unwrap();
        for family in [Family::State, Family::Command, Family::Outbox] {
            assert_eq!(
                view.get(&key(family, "command-1")),
                Ok(Some(b"original".to_vec()))
            );
        }
        assert!(description(&store.database().unwrap())
            .iter()
            .all(|(key, _)| key != "upgrade"));
    }
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[test]
fn backend_sync_failure_during_upgrade_refuses_readiness_and_requires_exact_reopen() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("store.redb");
    drop(legacy(&path));
    let (backend, status) = bounded_file::BoundedFile::new(file(&path), 256 * 1024 * 1024).unwrap();
    let db = native_builder().create_with_backend(backend).unwrap();
    let result =
        EmbeddedStore::open_database_with_checkpoint(db, StoreLimits::default(), false, |stage| {
            if stage == Checkpoint::UpgradeIntentDurable {
                status.fail_next_sync();
            }
        });
    assert!(matches!(result, Err(StoreError::CommitUncertain)));
    assert!(status.close_observed());
    let reopened = EmbeddedStore::open_file(file(&path), StoreLimits::default()).unwrap();
    assert_eq!(
        disk_format::inspect(&reopened.database().unwrap()),
        Ok(State::Current)
    );
    let view = reopened.snapshot().unwrap();
    for family in [Family::State, Family::Command, Family::Outbox] {
        assert_eq!(
            view.get(&key(family, "command-1")),
            Ok(Some(b"original".to_vec()))
        );
    }
}

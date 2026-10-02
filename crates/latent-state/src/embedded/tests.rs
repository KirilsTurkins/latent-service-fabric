use super::*;
use std::fs::OpenOptions;

mod measurement;
mod writers;

fn file(path: &std::path::Path) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path)
        .unwrap()
}
fn key(family: Family, id: &str) -> RowKey {
    RowKey {
        family,
        key: id.as_bytes().to_vec(),
    }
}
fn bundle(value: &str) -> AtomicBatch {
    AtomicBatch {
        expectations: vec![],
        mutations: [Family::State, Family::Command, Family::Outbox]
            .into_iter()
            .map(|family| RowMutation {
                key: key(family, "command-1"),
                value: Some(value.as_bytes().to_vec()),
            })
            .collect(),
    }
}

#[test]
fn final_acceptance_rejection_aborts_every_staged_family_before_flush() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("fenced.redb");
    let store = EmbeddedStore::open_file(file(&path), StoreLimits::default()).unwrap();
    let mut accepted = 0;
    assert_eq!(
        store.apply_fenced(bundle("must-not-persist"), || {
            accepted += 1;
            Err("revoked")
        }),
        Err(FencedStoreError::Fence("revoked"))
    );
    assert_eq!(accepted, 1);
    for family in [Family::State, Family::Command, Family::Outbox] {
        assert_eq!(
            store.snapshot().unwrap().get(&key(family, "command-1")),
            Ok(None)
        );
    }
    drop(store);
    let reopened = EmbeddedStore::open_file(file(&path), StoreLimits::default()).unwrap();
    assert_eq!(
        reopened
            .snapshot()
            .unwrap()
            .get(&key(Family::Command, "command-1")),
        Ok(None)
    );
    reopened
        .apply_fenced(bundle("accepted"), || Ok::<(), &str>(()))
        .unwrap();
    assert_eq!(
        reopened
            .snapshot()
            .unwrap()
            .get(&key(Family::Outbox, "command-1")),
        Ok(Some(b"accepted".to_vec()))
    );
}

#[test]
fn occ_and_capacity_failures_do_not_consume_final_commit_acceptance() {
    let dir = tempfile::tempdir().unwrap();
    let store = EmbeddedStore::open_file(
        file(&dir.path().join("fenced.redb")),
        StoreLimits {
            maximum_rows: 3,
            ..StoreLimits::default()
        },
    )
    .unwrap();
    store.apply(bundle("first")).unwrap();
    let calls = std::cell::Cell::new(0);
    let mut conflicting = bundle("second");
    conflicting.expectations.push(ExpectedRow {
        key: key(Family::Command, "command-1"),
        value: None,
    });
    assert_eq!(
        store.apply_fenced(conflicting, || {
            calls.set(calls.get() + 1);
            Ok::<(), &str>(())
        }),
        Err(FencedStoreError::Store(StoreError::Conflict))
    );
    let excessive = AtomicBatch {
        expectations: vec![],
        mutations: vec![RowMutation {
            key: key(Family::State, "extra"),
            value: Some(vec![1]),
        }],
    };
    assert_eq!(
        store.apply_fenced(excessive, || {
            calls.set(calls.get() + 1);
            Ok::<(), &str>(())
        }),
        Err(FencedStoreError::Store(StoreError::Capacity))
    );
    assert_eq!(calls.get(), 0);
    assert_eq!(
        store.snapshot().unwrap().get(&key(Family::State, "extra")),
        Ok(None)
    );
}

#[test]
fn coherent_prefix_pages_resume_exactly_and_refuse_unrepresentable_first_row() {
    let dir = tempfile::tempdir().unwrap();
    let store =
        EmbeddedStore::open_file(file(&dir.path().join("pages.redb")), StoreLimits::default())
            .unwrap();
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: ["aa", "ab", "ac", "b"]
                .into_iter()
                .map(|id| RowMutation {
                    key: key(Family::State, id),
                    value: Some(vec![1; 3]),
                })
                .collect(),
        })
        .unwrap();
    let view = store.snapshot().unwrap();
    let first = view.scan_after(Family::State, b"a", None, 1, 100).unwrap();
    assert_eq!(first.rows[0].0.key, b"aa");
    assert_eq!(first.resume.as_deref(), Some(b"aa".as_slice()));
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: key(Family::State, "ad"),
                value: Some(vec![2]),
            }],
        })
        .unwrap();
    let second = view
        .scan_after(Family::State, b"a", first.resume.as_deref(), 2, 100)
        .unwrap();
    assert_eq!(
        second
            .rows
            .iter()
            .map(|(key, _)| key.key.clone())
            .collect::<Vec<_>>(),
        vec![b"ab".to_vec(), b"ac".to_vec()]
    );
    assert_eq!(second.resume, None);
    assert_eq!(
        view.scan_after(Family::State, b"a", Some(b"b"), 1, 100),
        Err(StoreError::Invalid)
    );
    assert_eq!(
        view.scan_after(Family::State, b"a", None, 1, 5),
        Err(StoreError::Capacity)
    );
    assert!(view
        .scan_after(Family::State, b"z", None, 1, 5)
        .unwrap()
        .rows
        .is_empty());
}

#[test]
fn state_command_and_outbox_have_one_atomic_snapshot_and_reopen_identity() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("store.redb");
    let store = EmbeddedStore::open_file(file(&path), StoreLimits::default()).unwrap();
    let before = store.snapshot().unwrap();
    store.apply(bundle("committed")).unwrap();
    for family in [Family::State, Family::Command, Family::Outbox] {
        assert_eq!(before.get(&key(family, "command-1")), Ok(None));
    }
    let after = store.snapshot().unwrap();
    for family in [Family::State, Family::Command, Family::Outbox] {
        assert_eq!(
            after.get(&key(family, "command-1")),
            Ok(Some(b"committed".to_vec()))
        );
    }
    drop(before);
    drop(after);
    drop(store);
    let store = EmbeddedStore::open_file(file(&path), StoreLimits::default()).unwrap();
    assert_eq!(
        store
            .snapshot()
            .unwrap()
            .get(&key(Family::Command, "command-1")),
        Ok(Some(b"committed".to_vec()))
    );
}

#[test]
fn conflicting_and_over_budget_batches_abort_all_families() {
    let dir = tempfile::tempdir().unwrap();
    let limits = StoreLimits {
        maximum_rows: 3,
        ..StoreLimits::default()
    };
    let store = EmbeddedStore::open_file(file(&dir.path().join("store.redb")), limits).unwrap();
    store.apply(bundle("first")).unwrap();
    let mut wrong = bundle("wrong");
    wrong.expectations.push(ExpectedRow {
        key: key(Family::State, "command-1"),
        value: Some(b"stale".to_vec()),
    });
    assert_eq!(store.apply(wrong), Err(StoreError::Conflict));
    let mut over = bundle("wrong");
    over.mutations.push(RowMutation {
        key: key(Family::Inbox, "receipt"),
        value: Some(vec![1]),
    });
    assert_eq!(store.apply(over), Err(StoreError::Capacity));
    let snapshot = store.snapshot().unwrap();
    for family in [Family::State, Family::Command, Family::Outbox] {
        assert_eq!(
            snapshot.get(&key(family, "command-1")),
            Ok(Some(b"first".to_vec()))
        );
    }
    assert_eq!(snapshot.get(&key(Family::Inbox, "receipt")), Ok(None));
}

#[test]
fn read_views_duplicates_and_prefix_scan_are_bounded() {
    let dir = tempfile::tempdir().unwrap();
    let limits = StoreLimits {
        maximum_read_views: 1,
        ..StoreLimits::default()
    };
    let store = EmbeddedStore::open_file(file(&dir.path().join("store.redb")), limits).unwrap();
    let view = store.snapshot().unwrap();
    assert!(matches!(store.snapshot(), Err(StoreError::Capacity)));
    assert_eq!(store.live_views(), 1);
    drop(view);
    assert_eq!(store.live_views(), 0);
    let mut duplicate = bundle("x");
    duplicate.mutations.push(duplicate.mutations[0].clone());
    assert_eq!(store.apply(duplicate), Err(StoreError::Invalid));
    store.apply(bundle("x")).unwrap();
    let view = store.snapshot().unwrap();
    assert_eq!(
        view.scan(Family::State, b"command", 1, 1024).unwrap().len(),
        1
    );
    assert!(view
        .scan(Family::State, b"other", 1, 1024)
        .unwrap()
        .is_empty());
    assert_eq!(
        view.scan(Family::State, b"", 257, 1024),
        Err(StoreError::Invalid)
    );
}

#[test]
fn corrupt_bytes_and_concurrent_process_ownership_never_reset_the_store() {
    use std::io::Write;
    let dir = tempfile::tempdir().unwrap();
    let bad = dir.path().join("bad.redb");
    file(&bad).write_all(b"existing corrupt record").unwrap();
    assert!(matches!(
        EmbeddedStore::open_file(file(&bad), StoreLimits::default()),
        Err(StoreError::Corrupt)
    ));
    assert_eq!(std::fs::read(&bad).unwrap(), b"existing corrupt record");
    let path = dir.path().join("store.redb");
    let store = EmbeddedStore::open_file(file(&path), StoreLimits::default()).unwrap();
    assert!(EmbeddedStore::open_file(file(&path), StoreLimits::default()).is_err());
    store.apply(bundle("still-owned")).unwrap();
}

#[test]
fn closed_store_backup_compaction_and_independent_writer_rows_preserve_receipts() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("store.redb");
    let mut store = EmbeddedStore::open_file(file(&path), StoreLimits::default()).unwrap();
    store.apply(bundle("first")).unwrap();
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: key(Family::State, "independent"),
                value: Some(b"second".to_vec()),
            }],
        })
        .unwrap();
    let view = store.snapshot().unwrap();
    assert_eq!(store.compact(), Err(StoreError::Capacity));
    drop(view);
    store.compact().unwrap();
    drop(store);
    let backup = dir.path().join("backup.redb");
    std::fs::copy(&path, &backup).unwrap();
    let restored = EmbeddedStore::open_file(file(&backup), StoreLimits::default()).unwrap();
    assert_eq!(
        restored
            .snapshot()
            .unwrap()
            .get(&key(Family::Command, "command-1")),
        Ok(Some(b"first".to_vec()))
    );
    assert_eq!(
        restored
            .snapshot()
            .unwrap()
            .get(&key(Family::State, "independent")),
        Ok(Some(b"second".to_vec()))
    );
}

// Invoked only as a bounded owned child by the test below. This is a test-only
// barrier at the physical transaction boundary, not a production failpoint.
#[test]
fn owned_commit_child() {
    let Ok(root) = std::env::var("LATENT_STORE_CHILD_ROOT") else {
        return;
    };
    let after = std::env::var("LATENT_STORE_CHILD_AFTER").unwrap() == "true";
    let store = EmbeddedStore::open_file(
        file(&std::path::Path::new(&root).join("store.redb")),
        StoreLimits::default(),
    )
    .unwrap();
    store
        .apply_with_checkpoint(bundle("durable"), |committed| {
            if committed == after {
                use std::io::Write;
                println!("STORE_COMMIT_READY");
                std::io::stdout().flush().unwrap();
                std::thread::park_timeout(Duration::from_secs(30));
            }
        })
        .unwrap();
}

#[tokio::test]
async fn owned_process_termination_before_and_after_commit_recovers_all_or_none() {
    use latent_test_process::process::{OwnedProcess, ProcessLimits};
    use std::process::Command;
    for after in [false, true] {
        let dir = tempfile::tempdir().unwrap();
        let mut command = Command::new(std::env::current_exe().unwrap());
        command
            .args([
                "--exact",
                "embedded::tests::owned_commit_child",
                "--nocapture",
            ])
            .env("LATENT_STORE_CHILD_ROOT", dir.path())
            .env("LATENT_STORE_CHILD_AFTER", after.to_string());
        let child = OwnedProcess::spawn(command, ProcessLimits::default()).unwrap();
        let deadline = Instant::now() + Duration::from_secs(4);
        loop {
            let stdout = child.stdout_snapshot().unwrap();
            if stdout
                .windows(b"STORE_COMMIT_READY".len())
                .any(|v| v == b"STORE_COMMIT_READY")
            {
                break;
            }
            assert!(
                Instant::now() < deadline,
                "owned child did not reach commit barrier"
            );
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
        let retired = child.terminate().await.unwrap();
        assert!(!retired.status.success());
        let store =
            EmbeddedStore::open_file(file(&dir.path().join("store.redb")), StoreLimits::default())
                .unwrap();
        let view = store.snapshot().unwrap();
        for family in [Family::State, Family::Command, Family::Outbox] {
            assert_eq!(
                view.get(&key(family, "command-1")),
                Ok(after.then(|| b"durable".to_vec()))
            );
        }
    }
}

use super::*;
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};

fn limits() -> CompactionLimits {
    CompactionLimits {
        deadline: Instant::now() + Duration::from_secs(5),
        maximum_read_bytes: 64 * 1024 * 1024,
        maximum_write_bytes: 64 * 1024 * 1024,
        maximum_io_operations: 8192,
        maximum_scratch_bytes: 8 * 1024 * 1024,
        maximum_growth_bytes: 2 * 1024 * 1024,
    }
}

fn retained(path: &std::path::Path) -> (EmbeddedStore, StoreFileStatus) {
    let (store, status) =
        EmbeddedStore::open_bounded_file(file(path), StoreLimits::default(), 16 * 1024 * 1024)
            .unwrap();
    store.apply(bundle("retained-business-result")).unwrap();
    (store, status)
}

#[test]
fn bounded_compaction_preserves_business_rows_and_reports_actual_physical_bounds() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("bounded-compact.redb");
    let (mut store, status) = retained(&path);
    assert_eq!(store.compact(), Err(StoreError::Invalid));
    let before = store
        .snapshot()
        .unwrap()
        .scan(Family::Command, b"", 8, 65536)
        .unwrap();
    let checked = ExpectedRow {
        key: key(Family::Command, "command-1"),
        value: Some(b"retained-business-result".to_vec()),
    };
    let mut accepted = 0;
    let bound = limits();
    let report = store
        .compact_fenced(bound, &[checked], || {
            accepted += 1;
            Ok::<_, StoreError>(())
        })
        .unwrap();
    assert_eq!(accepted, 1);
    assert!(report.engine_started && report.engine_completed && report.stop.is_none());
    assert!(report.changed.is_some());
    assert!(report.io_operations > 0 && report.io_operations <= bound.maximum_io_operations);
    assert!(report.read_bytes <= bound.maximum_read_bytes);
    assert!(report.write_bytes > 0 && report.write_bytes <= bound.maximum_write_bytes);
    assert!(report.peak_file_bytes <= report.file_bytes_before + bound.maximum_growth_bytes);
    assert!(report.scratch_requirement_bytes <= report.scratch_limit_bytes);
    assert!(report.elapsed_micros <= 5_000_000);
    assert_eq!(status.last_compaction().unwrap(), Some(report));
    assert_eq!(
        store
            .snapshot()
            .unwrap()
            .scan(Family::Command, b"", 8, 65536)
            .unwrap(),
        before
    );
    drop(store);
    assert!(!status.close_failed());
    let reopened = EmbeddedStore::open_file(file(&path), StoreLimits::default()).unwrap();
    assert_eq!(
        reopened
            .snapshot()
            .unwrap()
            .scan(Family::Command, b"", 8, 65536)
            .unwrap(),
        before
    );
}

#[test]
fn bounded_compaction_refuses_live_views_active_writer_stale_rows_and_revoked_fence() {
    let directory = tempfile::tempdir().unwrap();
    let (store, status) = retained(&directory.path().join("fenced-compact.redb"));
    let accepted = AtomicUsize::new(0);
    let fence = || {
        accepted.fetch_add(1, Ordering::Relaxed);
        Ok::<_, StoreError>(())
    };
    let view = store.snapshot().unwrap();
    assert_eq!(
        store.compact_fenced(limits(), &[], fence),
        Err(FencedStoreError::Store(StoreError::Capacity))
    );
    drop(view);
    std::thread::scope(|scope| {
        let (started, running) = std::sync::mpsc::channel();
        let (release, ready) = std::sync::mpsc::channel();
        let store = &store;
        let writer = scope.spawn(move || {
            store.apply_fenced(AtomicBatch::default(), || {
                started.send(()).unwrap();
                ready.recv_timeout(Duration::from_secs(2)).unwrap();
                Ok::<_, StoreError>(())
            })
        });
        running.recv_timeout(Duration::from_secs(2)).unwrap();
        assert_eq!(
            store.compact_fenced(limits(), &[], fence),
            Err(FencedStoreError::Store(StoreError::Capacity))
        );
        release.send(()).unwrap();
        writer.join().unwrap().unwrap();
    });
    assert_eq!(accepted.load(Ordering::Relaxed), 0);
    let stale = ExpectedRow {
        key: key(Family::Command, "command-1"),
        value: Some(b"wrong".to_vec()),
    };
    assert_eq!(
        store.compact_fenced(limits(), &[stale], fence),
        Err(FencedStoreError::Store(StoreError::Conflict))
    );
    assert_eq!(accepted.load(Ordering::Relaxed), 0);
    assert_eq!(
        store.compact_fenced(limits(), &[], || Err(StoreError::Conflict)),
        Err(FencedStoreError::Fence(StoreError::Conflict))
    );
    let report = status.last_compaction().unwrap().unwrap();
    assert!(!report.engine_started && !report.engine_completed);
    assert_eq!(report.changed, Some(false));
    assert_eq!(report.stop, Some(CompactionStop::PreflightRefusal));
    assert_eq!(
        store
            .snapshot()
            .unwrap()
            .get(&key(Family::Command, "command-1")),
        Ok(Some(b"retained-business-result".to_vec()))
    );
}

#[test]
fn exhausted_compaction_io_holds_engine_and_preserves_prior_commits_on_reopen() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("exhausted-compact.redb");
    let (store, status) = retained(&path);
    let mut bound = limits();
    bound.maximum_io_operations = 1;
    assert!(store
        .compact_fenced(bound, &[], || Ok::<_, StoreError>(()))
        .is_err());
    let report = status.last_compaction().unwrap().unwrap();
    assert_eq!(report.stop, Some(CompactionStop::OperationBudget));
    assert!(report.io_operations <= 1);
    assert!(!report.engine_completed);
    assert_eq!(store.snapshot().err(), Some(StoreError::Unavailable));
    drop(store);
    let reopened = EmbeddedStore::open_file(file(&path), StoreLimits::default()).unwrap();
    assert_eq!(
        reopened
            .snapshot()
            .unwrap()
            .get(&key(Family::Command, "command-1")),
        Ok(Some(b"retained-business-result".to_vec()))
    );
}

#[test]
fn interrupted_compaction_sync_and_late_native_return_never_claim_clean_completion() {
    let directory = tempfile::tempdir().unwrap();
    for late in [false, true] {
        let path = directory.path().join(if late {
            "late-compact.redb"
        } else {
            "sync-compact.redb"
        });
        let (store, status) = retained(&path);
        let mut bound = limits();
        if late {
            status.delay_next_compaction_sync(1200);
            bound.deadline = Instant::now() + Duration::from_secs(1);
        } else {
            status.fail_next_compaction_sync();
        }
        assert_eq!(
            store.compact_fenced(bound, &[], || Ok::<_, StoreError>(())),
            Err(FencedStoreError::Store(StoreError::CommitUncertain))
        );
        let report = status.last_compaction().unwrap().unwrap();
        assert!(report.engine_started);
        assert_eq!(
            report.stop,
            Some(if late {
                CompactionStop::Deadline
            } else {
                CompactionStop::PhysicalFailure
            })
        );
        if !report.engine_completed {
            assert_eq!(report.changed, None);
        }
        if late {
            assert!(report.elapsed_micros >= 1_000_000);
        }
        assert_eq!(store.snapshot().err(), Some(StoreError::Unavailable));
        drop(store);
        let reopened = EmbeddedStore::open_file(file(&path), StoreLimits::default()).unwrap();
        assert_eq!(
            reopened
                .snapshot()
                .unwrap()
                .get(&key(Family::Command, "command-1")),
            Ok(Some(b"retained-business-result".to_vec()))
        );
    }
}

#[test]
fn compaction_backend_growth_and_byte_budgets_refuse_before_physical_io() {
    use crate::embedded::bounded_file::BoundedFile;
    use redb::StorageBackend;
    let directory = tempfile::tempdir().unwrap();
    for (write_limit, growth_limit, expected) in [
        (64, 0, CompactionStop::GrowthBudget),
        (1, 4096, CompactionStop::WriteBudget),
    ] {
        let path = directory.path().join(format!("backend-{write_limit}.bin"));
        let (backend, status) = BoundedFile::new(file(&path), 4096).unwrap();
        let mut bound = limits();
        bound.maximum_write_bytes = write_limit;
        bound.maximum_growth_bytes = growth_limit;
        let mut lease = status.begin_compaction(bound).unwrap();
        lease.started();
        assert!(backend.write(0, &[7; 32]).is_err());
        let report = lease.finish(false, None);
        assert_eq!(report.stop, Some(expected));
        assert_eq!(std::fs::metadata(&path).unwrap().len(), 0);
        assert_eq!(report.write_bytes, 0);
    }
    let (store, status) = retained(&directory.path().join("scratch-compact.redb"));
    let mut bound = limits();
    bound.maximum_scratch_bytes = 256 * 1024;
    let accepted = Arc::new(AtomicUsize::new(0));
    assert_eq!(
        store.compact_fenced(bound, &[], || {
            accepted.fetch_add(1, Ordering::Relaxed);
            Ok::<_, StoreError>(())
        }),
        Err(FencedStoreError::Store(StoreError::Capacity))
    );
    assert_eq!(accepted.load(Ordering::Relaxed), 0);
    assert!(status.last_compaction().unwrap().is_none());
    assert!(store.snapshot().is_ok());
}

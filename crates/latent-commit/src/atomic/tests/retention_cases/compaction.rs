use super::*;
use latent_state::embedded::{CompactionLimits, StoreFileStatus};
use std::{
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
    time::{Duration, Instant},
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
fn bounded_fixture(
    name: &str,
) -> (
    tempfile::TempDir,
    EmbeddedStore,
    StoreFileStatus,
    CommandRecord,
    ResultMaintenanceOwner,
    MaintenanceCompactionScope,
) {
    let (dir, store, effects) = setup();
    let record = completed(&store, &effects, name);
    let owner = ResultMaintenanceOwner::default();
    owner
        .anchor(&store, None, observation(2100, 0), maintenance)
        .unwrap();
    drop(store);
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(dir.path().join("state.redb"))
        .unwrap();
    let (store, status) =
        EmbeddedStore::open_bounded_file(file, StoreLimits::default(), 16 * 1024 * 1024).unwrap();
    let namespace = NamespaceRecord::decode(
        &store
            .snapshot()
            .unwrap()
            .get(&namespace_key())
            .unwrap()
            .unwrap(),
    )
    .unwrap();
    let scope = MaintenanceCompactionScope {
        tenant: namespace.tenant,
        namespace: namespace.id,
        expected: namespace.version,
    };
    (dir, store, status, record, owner, scope)
}

#[test]
fn compaction_borrows_the_original_shared_maintenance_guard_and_preserves_linked_evidence() {
    let (_dir, store, status, record, owner, scope) = bounded_fixture("shared-compactor");
    let before = store.snapshot().unwrap();
    let keys = [
        crate::atomic::command_row_key(record.id),
        result_row_key(record.id, record.attempt),
        latent_effects::dispatch_store::effect_row_key(&record.effects[0].hex()).unwrap(),
        latent_effects::dispatch_store::effect_payload_key(&record.effects[0].hex()).unwrap(),
        MaintenanceProgress::key(),
    ];
    let bytes: Vec<_> = keys.iter().map(|key| before.get(key).unwrap()).collect();
    drop(before);
    let calls = Arc::new(AtomicUsize::new(0));
    std::thread::scope(|threads| {
        let (started, ready) = std::sync::mpsc::channel();
        let (release, resume) = std::sync::mpsc::channel();
        let owned_calls = calls.clone();
        let borrowed_store = &store;
        let borrowed_owner = &owner;
        let borrowed_scope = &scope;
        let worker = threads.spawn(move || {
            borrowed_owner.compact(
                borrowed_store,
                borrowed_scope,
                limits(),
                observation(2200, 100),
                |namespace| {
                    assert_eq!(namespace.version, borrowed_scope.expected);
                    if owned_calls.fetch_add(1, Ordering::Relaxed) == 1 {
                        started.send(()).unwrap();
                        resume.recv_timeout(Duration::from_secs(2)).unwrap();
                    }
                    Ok(())
                },
            )
        });
        ready.recv_timeout(Duration::from_secs(2)).unwrap();
        assert_eq!(
            owner.step(&store, observation(2200, 100), maintenance),
            Err(AtomicError::InProgress)
        );
        release.send(()).unwrap();
        let report = worker.join().unwrap().unwrap();
        assert!(report.engine_completed && report.stop.is_none());
        assert_eq!(status.last_compaction().unwrap(), Some(report));
    });
    assert_eq!(calls.load(Ordering::Relaxed), 2);
    let after = store.snapshot().unwrap();
    for (key, bytes) in keys.iter().zip(bytes) {
        assert_eq!(after.get(key).unwrap(), bytes);
    }
    validate_view(&after, foreign_codec).unwrap();
    drop(after);
    assert!(owner
        .step(&store, observation(2200, 100), maintenance)
        .is_ok());
}

#[test]
fn compaction_refuses_stale_clock_history_restore_and_last_fence_revocation_without_reclamation() {
    for changed in 0..5 {
        let (_dir, store, status, record, owner, mut scope) =
            bounded_fixture(&format!("compaction-guard-{changed}"));
        let body = result_bytes(&store, &record);
        let mut clock = observation(2200, 100);
        let calls = AtomicUsize::new(0);
        if changed == 0 {
            scope.expected.generation += 1;
        }
        if changed == 1 {
            clock.boot = [8; 32];
        }
        if changed == 2 {
            let namespace = NamespaceRecord::decode(
                &store
                    .snapshot()
                    .unwrap()
                    .get(&namespace_key())
                    .unwrap()
                    .unwrap(),
            )
            .unwrap();
            let mut history =
                latent_state::namespace::history::NamespaceHistory::initial(&namespace);
            history.status =
                latent_state::namespace::history::HistoryStatus::ReconciliationRequired;
            store
                .apply(AtomicBatch {
                    expectations: vec![],
                    mutations: vec![RowMutation {
                        key: latent_state::namespace::history::history_key(
                            &scope.tenant,
                            &scope.namespace,
                            scope.expected.incarnation,
                        )
                        .unwrap(),
                        value: Some(history.encode().unwrap()),
                    }],
                })
                .unwrap();
        }
        if changed == 3 {
            store
                .apply(
                    latent_state::recovery::RecoveryGuard::staging([1; 32], [2; 32], [3; 32])
                        .unwrap()
                        .prepare_staging()
                        .unwrap(),
                )
                .unwrap();
        }
        let result = owner.compact(&store, &scope, limits(), clock, |_| {
            let seen = calls.fetch_add(1, Ordering::Relaxed);
            if changed == 4 && seen == 1 {
                return Err(AtomicError::PermissionDenied);
            }
            Ok(())
        });
        assert_eq!(
            result,
            Err(match changed {
                0 => AtomicError::Conflict,
                1 => AtomicError::RecoveryRequired,
                4 => AtomicError::PermissionDenied,
                _ => AtomicError::Unavailable,
            })
        );
        assert_eq!(result_bytes(&store, &record), body);
        if let Some(report) = status.last_compaction().unwrap() {
            assert!(!report.engine_started);
            assert_eq!(report.changed, Some(false));
        }
        assert!(calls.load(Ordering::Relaxed) <= 2);
    }
}

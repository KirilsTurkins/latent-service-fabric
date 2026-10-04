//! Real ext4 Fresh/import/custody schedules. Controlled installed owners do not
//! qualify live Kernel adoption, authenticated operator access or effect resume.
use super::*;
use crate::{
    embedded::ReadView,
    namespace::history::NamespaceHistory,
    protected_store::{
        ProtectedRestoreDestinationConfig, ProtectedRestoreStageJob, RestoreStageError,
        RestoreStageOwners, RestoreStageRequest, RestoreWriteKind,
    },
    recovery::{RecoveryGuard, RecoveryStatus},
    store_identity::StoreIdentity,
};
use fixture::StageOwners;
use std::path::Path;

fn destination(
    root: &Path,
    checkpoint: &Path,
    cache_bytes: usize,
) -> ProtectedRestoreDestinationConfig {
    let mut store = ProtectedStoreConfig::bounded_linux(root.to_path_buf());
    store.engine.cache_bytes = cache_bytes; // Explicit reviewed fixture, no default shrink.
    store.create_if_missing = true;
    ProtectedRestoreDestinationConfig {
        store,
        checkpoint: ProtectedCheckpointConfig {
            root: checkpoint.to_path_buf(),
        },
        identity: StoreIdentity::new("physical-restore-destination".into()).unwrap(),
    }
}

fn prepare(
    setup: &Setup,
    destination: ProtectedRestoreDestinationConfig,
) -> (
    ProtectedSnapshot,
    ProtectedRestoreInput,
    Arc<StageOwners>,
    RestoreStageRequest,
) {
    let (exported, owners, request) = setup.checkpoint();
    setup.retire(exported);
    let snapshot = setup.plan_restore(destination, &owners).unwrap();
    let (snapshot, reviewed) = wait(
        setup
            .owner
            .review_restore_window(snapshot, restore_input(&request), owners.clone())
            .unwrap(),
    )
    .unwrap();
    let input = reviewed.unwrap().unwrap();
    let request = RestoreStageRequest {
        operation_id: "restore-original-backup".into(),
        operator_id: "restore-operator".into(),
        runtime_digest: input.snapshot().manifest.metadata.runtime_digest,
        loss_window_acknowledgement: input.window().digest().unwrap(),
    };
    (
        snapshot,
        input,
        Arc::new(StageOwners::new(setup, &owners)),
        request,
    )
}

fn job(
    setup: &Setup,
    snapshot: ProtectedSnapshot,
    input: ProtectedRestoreInput,
    owners: &Arc<StageOwners>,
    request: RestoreStageRequest,
) -> ProtectedRestoreStageJob {
    setup
        .owner
        .stage_restore(
            snapshot,
            input,
            request,
            Arc::clone(owners) as Arc<dyn RestoreStageOwners>,
        )
        .unwrap()
}

fn inspect(
    setup: &Setup,
    snapshot: ProtectedSnapshot,
    inspect: impl FnOnce(&ReadView) -> Result<(), StoreError> + Send + 'static,
) -> ProtectedSnapshot {
    let job = setup
        .owner
        .with_physical_custody(snapshot.custody, 256 * 1024, move |file, _| {
            file.as_ref()
                .ok_or(StoreError::Invalid)?
                .restore
                .lock()
                .map_err(|_| StoreError::Unavailable)?
                .inspect_for_tests(inspect)
        })
        .unwrap();
    let (custody, checked) = wait(job).unwrap();
    checked.unwrap();
    ProtectedSnapshot { custody }
}

#[test]
fn original_authenticated_snapshot_imports_only_into_private_fresh_paused_destination() {
    let setup = Setup::with_restore_destination();
    let (root, _) = super::super::fixture();
    let (checkpoint, _) = super::super::fixture();
    let config = destination(root.path(), checkpoint.path(), 4 * 1024 * 1024);
    let (snapshot, input, owners, request) = prepare(&setup, config);
    let reviewed_history = input.window().namespaces()[0].proposed_history().unwrap();
    let previous_epoch = input.window().namespaces()[0]
        .current()
        .decode()
        .unwrap()
        .1
        .recovery_epoch;
    let source_before = fs::read(setup.source_path()).unwrap();
    let archive_before = fs::read(setup.checkpoint_path()).unwrap();
    let (snapshot, restored) = wait(job(&setup, snapshot, input, &owners, request)).unwrap();
    let restored = restored.unwrap().unwrap();
    assert!(restored.imported_rows() > 0);
    assert_eq!(
        restored.checkpoint().identity().as_str(),
        "physical-restore-destination"
    );
    assert_eq!(restored.checkpoint().protected_clock_epoch(), 1);
    assert_eq!(restored.checkpoint().dispatch_owner_epoch(), 7);
    assert_eq!(owners.verified.load(Ordering::SeqCst), 1);
    let operation = restored.operation_digest();
    let snapshot_digest = restored.checkpoint().encode();
    assert_eq!(
        fs::read(checkpoint.path().join("transaction-checkpoint.v1")).unwrap(),
        snapshot_digest
    );
    let snapshot = inspect(&setup, snapshot, move |view| {
        let guard = RecoveryGuard::capture(view)?.unwrap();
        assert_eq!(guard.status(), RecoveryStatus::ReconciliationRequired);
        assert_eq!(guard.operation_digest(), operation);
        assert!(crate::recovery::require_ready(view).is_err());
        let key = crate::namespace::history::history_key(
            &reviewed_history.tenant,
            &reviewed_history.namespace,
            reviewed_history.incarnation,
        )
        .unwrap();
        let actual = NamespaceHistory::decode(&view.get(&key)?.unwrap()).unwrap();
        assert_eq!(actual, reviewed_history);
        assert!(actual.recovery_epoch > previous_epoch);
        let rows = view.scan_after(Family::State, b"state-v1\0", None, 2, 4096)?;
        assert_eq!(rows.rows.len(), 1);
        let (key, bytes) = &rows.rows[0];
        assert_eq!(
            crate::session::inspect_cell(view, key, bytes)?
                .value
                .unwrap()
                .bytes,
            u64::MAX.to_le_bytes()
        );
        Ok(())
    });
    assert_eq!(fs::read(setup.source_path()).unwrap(), source_before);
    assert_eq!(fs::read(setup.checkpoint_path()).unwrap(), archive_before);
    assert!(setup.owner.snapshot().unwrap().custody_active);
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 1);
    restored.check().unwrap();
    drop(restored);
    setup.retire(snapshot);
    setup.require_census();
    assert_eq!(setup.owner.failure(), None);
    assert!(finish(&setup.owner).clean);
}

#[test]
fn fresh_restore_refuses_old_empty_unknown_and_linked_root_entries_without_overwrite() {
    for kind in 0..3 {
        let setup = Setup::with_restore_destination();
        let (root, _) = super::super::fixture();
        let (checkpoint, _) = super::super::fixture();
        let path = root.path().join("old-entry");
        match kind {
            0 => fs::write(&path, b"").unwrap(),
            1 => fs::create_dir(&path).unwrap(),
            _ => std::os::unix::fs::symlink("absent", &path).unwrap(),
        }
        let (snapshot, input, owners, request) = prepare(
            &setup,
            destination(root.path(), checkpoint.path(), 4 * 1024 * 1024),
        );
        let (snapshot, refused) = wait(job(&setup, snapshot, input, &owners, request)).unwrap();
        assert!(matches!(
            refused.unwrap(),
            Err(RestoreStageError::Destination(
                ProtectedStoreError::UnsafeRoot
            ))
        ));
        assert!(!root.path().join("transaction-state.redb").exists());
        assert!(!checkpoint.path().join("transaction-checkpoint.v1").exists());
        assert!(fs::symlink_metadata(&path).is_ok());
        if kind == 0 {
            assert_eq!(fs::read(&path).unwrap(), b"");
        }
        assert_eq!(setup.owner.failure(), None);
        setup.retire(snapshot);
        setup.require_census();
        assert!(finish(&setup.owner).clean);
    }
}

#[test]
fn separate_checkpoint_must_be_physically_fresh_and_never_reuses_an_empty_old_file() {
    let setup = Setup::with_restore_destination();
    let (root, _) = super::super::fixture();
    let (checkpoint, _) = super::super::fixture();
    let old = checkpoint.path().join("transaction-checkpoint.v1");
    fs::write(&old, b"").unwrap();
    let (snapshot, input, owners, request) = prepare(
        &setup,
        destination(root.path(), checkpoint.path(), 4 * 1024 * 1024),
    );
    let source_before = fs::read(setup.source_path()).unwrap();
    let (snapshot, refused) = wait(job(&setup, snapshot, input, &owners, request)).unwrap();
    assert!(matches!(
        refused.unwrap(),
        Err(RestoreStageError::Checkpoint(StoreError::Conflict))
    ));
    assert_eq!(fs::read(&old).unwrap(), b"");
    assert!(!checkpoint
        .path()
        .join("transaction-checkpoint-owner.lock")
        .exists());
    assert_eq!(fs::read(setup.source_path()).unwrap(), source_before);
    assert_eq!(setup.owner.failure(), None);
    setup.retire(snapshot);
    setup.require_census();
    assert!(finish(&setup.owner).clean);
}

#[test]
fn import_writer_rechecks_each_original_owner_and_keeps_partial_staging_closed() {
    for owner in 1..=4 {
        let setup = Setup::with_restore_destination();
        let (root, _) = super::super::fixture();
        let (checkpoint, _) = super::super::fixture();
        let (snapshot, input, owners, request) = prepare(
            &setup,
            destination(root.path(), checkpoint.path(), 4 * 1024 * 1024),
        );
        let (gates, receiver) = owners.pause_kind(RestoreWriteKind::ImportRow);
        let work = job(&setup, snapshot, input, &owners, request);
        let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
        owners.revoked.store(owner, Ordering::SeqCst);
        gates.release(ticket).unwrap();
        let (snapshot, refused) = wait(work).unwrap();
        assert!(matches!(
            refused.unwrap(),
            Err(RestoreStageError::Review(StoreError::Unavailable))
        ));
        let snapshot = inspect(&setup, snapshot, |view| {
            assert_eq!(
                RecoveryGuard::capture(view)?.unwrap().status(),
                RecoveryStatus::Staging
            );
            assert!(crate::recovery::require_ready(view).is_err());
            Ok(())
        });
        assert_eq!(
            fs::read(checkpoint.path().join("transaction-checkpoint.v1")).unwrap(),
            b""
        );
        assert_eq!(owners.verified.load(Ordering::SeqCst), 0);
        assert_eq!(setup.owner.failure(), None);
        setup.retire(snapshot);
        setup.require_census();
        assert!(finish(&setup.owner).clean);
    }
}

#[test]
fn final_checkpoint_fence_rechecks_role_audit_controls_and_clock_without_sealing() {
    for owner in 1..=4 {
        let setup = Setup::with_restore_destination();
        let (root, _) = super::super::fixture();
        let (checkpoint, _) = super::super::fixture();
        let (snapshot, input, owners, request) = prepare(
            &setup,
            destination(root.path(), checkpoint.path(), 4 * 1024 * 1024),
        );
        let (gates, receiver) = owners.pause_kind(RestoreWriteKind::SealCheckpoint);
        let work = job(&setup, snapshot, input, &owners, request);
        let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
        owners.revoked.store(owner, Ordering::SeqCst);
        gates.release(ticket).unwrap();
        let (snapshot, refused) = wait(work).unwrap();
        assert!(matches!(
            refused.unwrap(),
            Err(RestoreStageError::Checkpoint(StoreError::Unavailable))
        ));
        assert_eq!(
            fs::read(checkpoint.path().join("transaction-checkpoint.v1")).unwrap(),
            b""
        );
        let snapshot = inspect(&setup, snapshot, |view| {
            assert_eq!(
                RecoveryGuard::capture(view)?.unwrap().status(),
                RecoveryStatus::ReconciliationRequired
            );
            assert!(crate::recovery::require_ready(view).is_err());
            Ok(())
        });
        assert_eq!(setup.owner.failure(), None);
        setup.retire(snapshot);
        setup.require_census();
        assert!(finish(&setup.owner).clean);
    }
}

#[test]
fn ignored_original_native_fence_cannot_initialize_restore_identity_or_receipt() {
    let setup = Setup::with_restore_destination();
    let (root, _) = super::super::fixture();
    let (checkpoint, _) = super::super::fixture();
    let (snapshot, input, owners, request) = prepare(
        &setup,
        destination(root.path(), checkpoint.path(), 4 * 1024 * 1024),
    );
    owners.ignored_gate.store(true, Ordering::SeqCst);
    let (snapshot, refused) = wait(job(&setup, snapshot, input, &owners, request)).unwrap();
    assert!(matches!(
        refused.unwrap(),
        Err(RestoreStageError::Destination(ProtectedStoreError::Store(
            StoreError::Invalid
        )))
    ));
    assert_eq!(owners.writes.load(Ordering::SeqCst), 0);
    assert!(!checkpoint.path().join("transaction-checkpoint.v1").exists());
    assert_eq!(setup.owner.failure(), None);
    setup.retire(snapshot);
    setup.require_census();
    assert!(finish(&setup.owner).clean);
}

#[test]
fn restore_cache_precharge_refuses_original_work_or_io_pressure_before_any_destination_io() {
    for pressure in 0..2 {
        let setup = if pressure == 0 {
            Setup::with_restore_response()
        } else {
            Setup::with_restore_destination()
        };
        let (root, _) = super::super::fixture();
        let (checkpoint, _) = super::super::fixture();
        let (exported, owners, _) = setup.checkpoint();
        setup.retire(exported);
        let cache = if pressure == 0 {
            4 * 1024 * 1024
        } else {
            8 * 1024 * 1024
        };
        assert!(setup
            .plan_restore(destination(root.path(), checkpoint.path(), cache), &owners)
            .is_err());
        assert_eq!(fs::read_dir(root.path()).unwrap().count(), 0);
        assert_eq!(fs::read_dir(checkpoint.path()).unwrap().count(), 0);
        assert!(!setup.owner.snapshot().unwrap().custody_active);
        assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 1);
        assert_eq!(setup.owner.failure(), None);
        setup.require_census();
        assert!(finish(&setup.owner).clean);
    }
}

#[test]
fn detached_import_waiter_keeps_actual_fresh_engine_file_and_original_native_until_retirement() {
    let mut setup = Setup::with_restore_destination();
    let (root, _) = super::super::fixture();
    let (checkpoint, _) = super::super::fixture();
    let (snapshot, input, owners, request) = prepare(
        &setup,
        destination(root.path(), checkpoint.path(), 4 * 1024 * 1024),
    );
    let (gates, receiver) = owners.pause_kind(RestoreWriteKind::ImportRow);
    let weak_original = Arc::downgrade(setup.original());
    let weak_owners = Arc::downgrade(&owners);
    let work = job(&setup, snapshot, input, &owners, request);
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    drop(work);
    drop(owners);
    setup.release_original();
    setup.owner.close();
    let mut drain = Box::pin(
        setup
            .owner
            .drain_async(Instant::now() + WATCHDOG, std::future::pending())
            .unwrap(),
    );
    PollProbe::default().pending(drain.as_mut());
    assert!(weak_original.upgrade().is_some());
    assert!(weak_owners.upgrade().is_some());
    assert!(root.path().join("transaction-state.redb").exists());
    assert!(setup.owner.snapshot().unwrap().custody_active);
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 1);
    gates.release(ticket).unwrap();
    let shutdown = wait(drain);
    assert!(shutdown.clean);
    assert!(shutdown.snapshot.physically_retired());
    assert!(weak_original.upgrade().is_none());
    assert!(weak_owners.upgrade().is_none());
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 0);
}

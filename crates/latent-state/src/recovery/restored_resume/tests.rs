//! Actual engine and canonical receipt controls. Physical custody and current
//! authorization are exercised separately by the protected owner schedules.
use super::*;
use crate::{
    embedded::{AtomicBatch, FencedStoreError, RowMutation},
    namespace::{history::history_key, namespace_record_key, NamespaceTransition},
    recovery::{
        migration::{tests::fixture::Fixture, AggregateMigrationRecipe, MigrationPhase},
        namespace_resume::{NamespaceRecoveryView, NamespaceResumePlan, NamespaceResumeRequest},
        restore::RestoreWindow,
        resume::{MigrationResumePlan, MigrationResumeRequest},
        snapshot::inspect_snapshot,
        RecoveryGuard,
    },
};
use std::io::Cursor;

struct Restored {
    fixture: Fixture,
    snapshot: SnapshotReceipt,
    progress_digest: [u8; 32],
    request: RestoredMigrationResumeRequest,
}

fn deadline() -> std::time::Instant {
    std::time::Instant::now() + std::time::Duration::from_secs(20)
}

fn restored(reviewed: bool) -> Restored {
    let fixture = Fixture::new(AggregateMigrationRecipe::JavaAggregate, true);
    fixture.apply(MigrationPhase::Stage);
    fixture.apply(MigrationPhase::Complete);
    let progress_digest = Sha256::digest(fixture.progress_bytes()).into();
    let mut metadata = fixture.metadata.clone();
    metadata.tenant = fixture.request.scope.tenant.0.clone();
    metadata.operation_id = "migrated-backup".into();
    let archive = fixture.export(metadata);
    let view = fixture.store.snapshot().unwrap();
    let snapshot = inspect_snapshot(&mut Cursor::new(archive), deadline(), |key, bytes| {
        crate::recovery::migration::tests::fixture::row(&view, key, bytes)
    })
    .unwrap();
    let window = RestoreWindow::capture(&view, &snapshot, deadline(), || Ok(())).unwrap();
    let history = window.namespaces()[0].proposed_history().unwrap();
    let history_key =
        history_key(&history.tenant, &history.namespace, history.incarnation).unwrap();
    drop(view);
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: history_key,
                value: Some(history.encode().unwrap()),
            }],
        })
        .unwrap();
    let guard =
        RecoveryGuard::staging([51; 32], snapshot.snapshot_digest, window.digest().unwrap())
            .unwrap();
    fixture
        .store
        .apply(guard.prepare_staging().unwrap())
        .unwrap();
    fixture
        .store
        .apply(guard.prepare_completed().unwrap())
        .unwrap();
    let view = fixture.store.snapshot().unwrap();
    if reviewed {
        let guard = RecoveryGuard::capture(&view).unwrap().unwrap();
        let batch = guard
            .prepare_reviewed(&view, [52; 32], |_, _, _| Ok(()))
            .unwrap();
        drop(view);
        fixture.store.apply(batch).unwrap();
    } else {
        drop(view);
    }
    let view = fixture.store.snapshot().unwrap();
    let current =
        NamespaceRecoveryView::capture(&view, &history.tenant, &history.namespace).unwrap();
    let request = RestoredMigrationResumeRequest {
        scope: current.scope(),
        operation_id: "activate-restored-migration".into(),
        operator_id: fixture.request.operator_id.clone(),
        migration_operation_id: fixture.request.operation_id.clone(),
        expected_view: current.view_token().unwrap(),
        snapshot_digest: snapshot.snapshot_digest,
        manifest_digest: snapshot.manifest_digest,
        restore_operation_digest: [51; 32],
        window_digest: window.digest().unwrap(),
        review_digest: [52; 32],
    };
    drop(view);
    Restored {
        fixture,
        snapshot,
        progress_digest,
        request,
    }
}

fn plan(
    fixture: &Restored,
    request: &RestoredMigrationResumeRequest,
) -> Result<RestoredMigrationResumePlan, StoreError> {
    RestoredMigrationResumePlan::prepare(
        &fixture.fixture.store.snapshot().unwrap(),
        request,
        &fixture.snapshot,
        fixture.progress_digest,
        &fixture.fixture.schema,
        |_, _, observed| {
            assert!(observed.progress.completed());
            assert_eq!(
                observed.snapshot.snapshot_digest,
                fixture.snapshot.snapshot_digest
            );
            Ok(())
        },
    )
}

#[test]
#[expect(
    clippy::too_many_lines,
    reason = "One immutable replay schedule keeps both prior resume refusals, exact accounting and later quiesce observable"
)]
fn restored_java_migration_activates_once_preserves_original_refusals_and_lost_response() {
    let fixture = restored(true);
    let view = fixture.fixture.store.snapshot().unwrap();
    let generic = NamespaceResumeRequest {
        scope: fixture.request.scope.clone(),
        operation_id: "generic-resume".into(),
        operator_id: fixture.request.operator_id.clone(),
        expected_view: fixture.request.expected_view.clone(),
        review_digest: fixture.request.review_digest,
    };
    assert!(matches!(
        NamespaceResumePlan::prepare(&view, &generic, |_, _, _| Ok(())),
        Err(StoreError::UnsupportedFormat)
    ));
    let original = MigrationResumeRequest {
        scope: generic.scope,
        operation_id: "original-migration-resume".into(),
        operator_id: generic.operator_id,
        expected_view: generic.expected_view,
        migration: fixture.fixture.request.clone(),
        review_digest: [91; 32],
    };
    assert!(MigrationResumePlan::prepare(
        &view,
        &original,
        &fixture.fixture.schema,
        deadline(),
        |_, _, _| Ok(())
    )
    .is_err());
    let before = crate::tenant::inspect(&view, &fixture.request.scope.tenant)
        .unwrap()
        .unwrap();
    drop(view);
    let state = fixture.fixture.state_row();
    let progress = fixture.fixture.progress_bytes();
    let prepared = plan(&fixture, &fixture.request).unwrap();
    assert!(!prepared.replayed());
    let receipt = prepared.receipt().encode().unwrap();
    assert!(receipt.starts_with(b"RMA\x01"));
    assert!(NamespaceResumeReceipt::decode(&receipt).is_err());
    fixture
        .fixture
        .store
        .apply_fenced(prepared.into_batch(), || Ok::<(), StoreError>(()))
        .unwrap();
    let view = fixture.fixture.store.snapshot().unwrap();
    let active = NamespaceRecoveryView::capture(
        &view,
        &fixture.request.scope.tenant,
        &fixture.request.scope.namespace,
    )
    .unwrap();
    assert_eq!(
        active.namespace.status,
        crate::namespace::NamespaceStatus::Active
    );
    assert_eq!(
        active.history.status,
        crate::namespace::history::HistoryStatus::Ready
    );
    assert_eq!(active.history.epochs.recovery, 2);
    let after = crate::tenant::inspect(&view, &fixture.request.scope.tenant)
        .unwrap()
        .unwrap();
    assert_eq!(after.usage.metadata_rows, before.usage.metadata_rows + 1);
    let quiesced = active
        .namespace
        .transition(active.namespace.version, &NamespaceTransition::Quiesce, 0)
        .unwrap();
    drop(view);
    fixture
        .fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: RowKey {
                    family: Family::Namespace,
                    key: namespace_record_key(&quiesced.tenant, &quiesced.id).unwrap(),
                },
                value: Some(quiesced.encode().unwrap()),
            }],
        })
        .unwrap();
    let replay = plan(&fixture, &fixture.request).unwrap();
    assert!(replay.replayed());
    assert_eq!(replay.receipt().encode().unwrap(), receipt);
    fixture.fixture.store.apply(replay.into_batch()).unwrap();
    let view = fixture.fixture.store.snapshot().unwrap();
    let current = NamespaceRecoveryView::capture(
        &view,
        &fixture.request.scope.tenant,
        &fixture.request.scope.namespace,
    )
    .unwrap();
    assert_eq!(current.namespace, quiesced);
    assert_eq!(
        crate::tenant::inspect(&view, &fixture.request.scope.tenant)
            .unwrap()
            .unwrap()
            .usage,
        after.usage
    );
    drop(view);
    let current_state = fixture.fixture.state_row();
    assert_eq!(current_state.key, state.key);
    assert_eq!(current_state.value, state.value);
    assert_eq!(fixture.fixture.progress_bytes(), progress);
    fixture.fixture.require_census();
}

#[test]
fn restored_activation_requires_exact_review_window_guard_source_and_original_migration() {
    let pending = restored(false);
    assert!(matches!(
        plan(&pending, &pending.request),
        Err(StoreError::Unavailable)
    ));
    let fixture = restored(true);
    for index in 0..9 {
        let mut request = fixture.request.clone();
        match index {
            0 => request.snapshot_digest = [71; 32],
            1 => request.manifest_digest = [72; 32],
            2 => request.restore_operation_digest = [73; 32],
            3 => request.window_digest = [74; 32],
            4 => request.review_digest = [75; 32],
            5 => request.migration_operation_id = "other-migration".into(),
            6 => request.operator_id = "other-operator".into(),
            7 => request.expected_view[10] ^= 1,
            _ => request.scope.incarnation += 1,
        }
        assert!(plan(&fixture, &request).is_err(), "changed fence {index}");
    }
    let view = fixture.fixture.store.snapshot().unwrap();
    assert!(RestoredMigrationResumePlan::prepare(
        &view,
        &fixture.request,
        &fixture.snapshot,
        [76; 32],
        &fixture.fixture.schema,
        |_, _, _| Ok(())
    )
    .is_err());
    assert!(matches!(
        RestoredMigrationResumePlan::prepare(
            &view,
            &fixture.request,
            &fixture.snapshot,
            fixture.progress_digest,
            &fixture.fixture.schema,
            |_, _, _| Err(StoreError::Unavailable)
        ),
        Err(StoreError::Unavailable)
    ));
    let prepared = plan(&fixture, &fixture.request).unwrap();
    drop(view);
    assert!(matches!(
        fixture
            .fixture
            .store
            .apply_fenced(prepared.into_batch(), || Err(StoreError::Unavailable)),
        Err(FencedStoreError::Fence(StoreError::Unavailable))
    ));
    assert!(plan(&fixture, &fixture.request).is_ok());
    fixture.fixture.require_census();
}

#[test]
fn restored_activation_cas_rejects_changed_review_and_receipt_codec_refuses_aliases() {
    let fixture = restored(true);
    let prepared = plan(&fixture, &fixture.request).unwrap();
    let bytes = prepared.receipt().encode().unwrap();
    let key = fixture.request.receipt_key().unwrap();
    RestoredMigrationResumeReceipt::validate_row(&key, &bytes).unwrap();
    for length in [0, 4, 259, bytes.len() - 1] {
        assert!(RestoredMigrationResumeReceipt::decode(&bytes[..length]).is_err());
    }
    let mut trailing = bytes.clone();
    trailing.push(0);
    assert!(RestoredMigrationResumeReceipt::decode(&trailing).is_err());
    let mut zero = bytes.clone();
    zero[4..36].fill(0);
    assert!(RestoredMigrationResumeReceipt::decode(&zero).is_err());
    let mut alias = key;
    alias.key[0] ^= 1;
    assert!(RestoredMigrationResumeReceipt::validate_row(&alias, &bytes).is_err());
    let view = fixture.fixture.store.snapshot().unwrap();
    let guard = RecoveryGuard::capture(&view).unwrap().unwrap();
    let changed =
        RecoveryGuard::staging([81; 32], guard.snapshot_digest(), guard.window_digest()).unwrap();
    drop(view);
    fixture
        .fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: crate::recovery::guard_key(),
                value: Some(changed.encode().unwrap()),
            }],
        })
        .unwrap();
    assert!(matches!(
        fixture.fixture.store.apply(prepared.into_batch()),
        Err(StoreError::Conflict)
    ));
    assert!(fixture
        .fixture
        .store
        .snapshot()
        .unwrap()
        .get(&fixture.request.receipt_key().unwrap())
        .unwrap()
        .is_none());
}

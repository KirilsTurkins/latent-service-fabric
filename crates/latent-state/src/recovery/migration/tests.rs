use super::super::{
    resume::{NamespaceResumePlan, NamespaceResumeRequest},
    snapshot::{export_snapshot, RequiredArtifact, SnapshotClosure, SnapshotMetadata},
};
use super::*;
use crate::{
    embedded::{EmbeddedStore, Family, FencedStoreError, RowKey, StoreLimits},
    namespace::{
        catalog::NamespaceCatalog,
        compatibility::{RetainedCount, RetainedInventory, SchemaDeclaration},
        NamespacePins, NamespaceQuota, NamespaceTransition,
    },
    session::{SessionLimits, StateError, StateMode, StateScope, StateSession},
};
use latent_core::{transaction_contract::Value, StateNamespaceId, TenantId};
use std::io::Cursor;
use std::time::Duration;

struct Fixture {
    store: EmbeddedStore,
    root: tempfile::TempDir,
    request: AggregateMigrationRequest,
    schema: ReviewedSchema,
    checkpoint: Vec<u8>,
}
fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(20)
}
fn open(root: &std::path::Path, new: bool) -> EmbeddedStore {
    let mut options = std::fs::OpenOptions::new();
    options.read(true).write(true);
    if new {
        options.create_new(true);
    }
    EmbeddedStore::open_file(
        options.open(root.join("migration.redb")).unwrap(),
        StoreLimits {
            cache_bytes: 1024 * 1024,
            ..StoreLimits::default()
        },
    )
    .unwrap()
}
fn schema(package: [u8; 32]) -> ReviewedSchema {
    let (v1, v2) = schema_ids().unwrap();
    ReviewedSchema::accept_with(
        SchemaDeclaration {
            package_digest: package,
            readers: vec![v1, v2.clone()],
            writers: vec![v2],
        },
        package,
        [44; 32],
        |_, _, _| Ok(()),
    )
    .unwrap()
}
fn artifacts() -> Vec<RequiredArtifact> {
    vec![
        RequiredArtifact {
            identity: schema_ids().unwrap().0.as_str().into(),
            digest: Sha256::digest(V1).into(),
        },
        RequiredArtifact {
            identity: schema_ids().unwrap().1.as_str().into(),
            digest: Sha256::digest(V2).into(),
        },
        RequiredArtifact {
            identity: "lsf.aggregate-migration.v1".into(),
            digest: Sha256::digest(RECIPE).into(),
        },
        RequiredArtifact {
            identity: checkpoint::package_identity(&[43; 32]),
            digest: [43; 32],
        },
    ]
}
fn validate_row(view: &ReadView, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    if key.key.starts_with(PROGRESS_PREFIX) {
        AggregateMigrationProgress::validate_row(key, bytes)
    } else if key.key.starts_with(super::super::resume::RECEIPT_PREFIX) {
        super::super::resume::NamespaceResumeReceipt::validate_row(key, bytes)
    } else if key.family == Family::Namespace {
        NamespaceCatalog::validate_row(key, bytes).map_err(|_| StoreError::Corrupt)
    } else {
        crate::session::validate_row(view, key, bytes)
    }
}
fn closure(view: &ReadView) -> Result<SnapshotClosure, StoreError> {
    let mut inventory = RetainedInventory::default();
    super::super::snapshot::visit_view(view, deadline(), |_, key, bytes| {
        validate_row(view, key, bytes)?;
        if key.key.starts_with(PROGRESS_PREFIX) {
            let p = AggregateMigrationProgress::decode(bytes)?;
            inventory
                .observe(
                    retained_format(),
                    RetainedCount {
                        rows: 1,
                        bytes: bytes.len() as u64,
                        unresolved: u64::from(!p.completed()),
                    },
                )
                .map_err(|_| StoreError::Capacity)?;
        }
        Ok(())
    })?;
    Ok(SnapshotClosure {
        inventory,
        required_artifacts: artifacts(),
    })
}
fn fixture() -> Fixture {
    fixture_with_count(u64::MAX.to_le_bytes().to_vec(), NamespaceQuota::default())
}
fn fixture_with_count(count: Vec<u8>, quota: NamespaceQuota) -> Fixture {
    let root = tempfile::tempdir().unwrap();
    let store = open(root.path(), true);
    let namespace = NamespaceRecord::create(
        TenantId("tenant".into()),
        StateNamespaceId("aggregate".into()),
        schema_ids().unwrap().0.as_str().into(),
        quota,
    )
    .unwrap();
    let scope = StateScope {
        tenant: namespace.tenant.clone(),
        namespace: namespace.id.clone(),
        incarnation: 1,
        state_schema: namespace.state_schema.clone(),
        entity: None,
        mode: StateMode::Command,
    };
    let key = RowKey {
        family: Family::Namespace,
        key: namespace_record_key(&scope.tenant, &scope.namespace).unwrap(),
    };
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: key.clone(),
                value: Some(namespace.encode().unwrap()),
            }],
        })
        .unwrap();
    initialize_count(&store, &scope, count);
    let view = store.snapshot().unwrap();
    let before = view.get(&key).unwrap().unwrap();
    let n = NamespaceRecord::decode(&before).unwrap();
    let quiesced = n
        .transition(n.version, &NamespaceTransition::Quiesce, 0)
        .unwrap();
    drop(view);
    store
        .apply(AtomicBatch {
            expectations: vec![ExpectedRow {
                key: key.clone(),
                value: Some(before),
            }],
            mutations: vec![RowMutation {
                key,
                value: Some(quiesced.encode().unwrap()),
            }],
        })
        .unwrap();
    let mut checkpoint = vec![];
    let receipt = export_snapshot(
        &store,
        SnapshotMetadata {
            tenant: "tenant".into(),
            operation_id: "checkpoint".into(),
            operator_id: "operator".into(),
            runtime_digest: [42; 32],
            decoder_formats: vec![retained_format()],
            required_artifacts: artifacts(),
        },
        &mut checkpoint,
        deadline(),
        closure,
        |_| Ok(()),
    )
    .unwrap();
    let view = store.snapshot().unwrap();
    let observation =
        NamespaceRecoveryView::capture(&view, &scope.tenant, &scope.namespace).unwrap();
    Fixture {
        store,
        root,
        request: AggregateMigrationRequest {
            scope,
            operation_id: "migrate-1".into(),
            operator_id: "operator".into(),
            expected_view: observation.view_token().unwrap(),
            checkpoint_digest: receipt.snapshot_digest,
            checkpoint_manifest_digest: receipt.manifest_digest,
            package_digest: [43; 32],
            review_digest: [45; 32],
        },
        schema: schema([43; 32]),
        checkpoint,
    }
}
fn initialize_count(store: &EmbeddedStore, scope: &StateScope, count: Vec<u8>) {
    let view = store.snapshot().unwrap();
    let mut session =
        StateSession::open(
            &view,
            scope.clone(),
            SessionLimits::default(),
            |_, _| Ok(()),
        )
        .unwrap();
    session
        .put(
            &view,
            b"count".to_vec(),
            Value {
                bytes: count,
                media_type: "application/vnd.lsf.aggregate-v1".into(),
                metadata: vec![],
            },
            |_, _| Ok(()),
        )
        .unwrap();
    let mut batch = AtomicBatch::default();
    session
        .seal(&view, |_, _| Ok(()))
        .unwrap()
        .append_to(&mut batch, NamespacePins::default())
        .unwrap();
    drop(view);
    store.apply(batch).unwrap();
}

fn checkpoint(f: &Fixture, view: &ReadView) -> VerifiedMigrationCheckpoint {
    VerifiedMigrationCheckpoint::inspect(
        view,
        &mut Cursor::new(&f.checkpoint),
        deadline(),
        |key, bytes| validate_row(view, key, bytes),
        closure,
        |_| Ok(()),
    )
    .unwrap()
}
fn prepare(f: &Fixture) -> AggregateMigrationPlan {
    let view = f.store.snapshot().unwrap();
    let checkpoint = checkpoint(f, &view);
    AggregateMigrationPlan::prepare(
        &view,
        &f.request,
        &checkpoint,
        &f.schema,
        if view
            .get(&f.request.progress_key().unwrap())
            .unwrap()
            .is_none()
        {
            MigrationAction::Stage
        } else {
            MigrationAction::Complete
        },
        deadline(),
        |_, _, _| Ok(()),
    )
    .unwrap()
}
fn activate(f: &Fixture) -> NamespaceRecord {
    let view = f.store.snapshot().unwrap();
    let observed =
        NamespaceRecoveryView::capture(&view, &f.request.scope.tenant, &f.request.scope.namespace)
            .unwrap();
    let request = NamespaceResumeRequest {
        scope: observed.scope(),
        operation_id: "resume-v2".into(),
        operator_id: "operator".into(),
        expected_view: observed.view_token().unwrap(),
        review_digest: [46; 32],
    };
    let plan = NamespaceResumePlan::prepare(&view, &request, |_, _, _| Ok(())).unwrap();
    let namespace = plan.receipt().namespace().clone();
    drop(view);
    f.store.apply(plan.into_batch()).unwrap();
    namespace
}

#[test]
fn fixed_aggregate_migration_resumes_durable_stage_after_engine_restart_and_changes_actual_format()
{
    let mut f = fixture();
    let stage = prepare(&f);
    assert_eq!(stage.action(), MigrationAction::Stage);
    f.store.apply(stage.into_batch()).unwrap();
    let view = f.store.snapshot().unwrap();
    let observed =
        NamespaceRecoveryView::capture(&view, &f.request.scope.tenant, &f.request.scope.namespace)
            .unwrap();
    assert_eq!(
        require_resume_ready(&view, &observed.namespace),
        Err(StoreError::Unavailable)
    );
    assert!(matches!(
        StateSession::open(
            &view,
            f.request.scope.clone(),
            SessionLimits::default(),
            |_, _| Ok(())
        ),
        Err(StateError::PermissionDenied)
    ));
    drop(view);
    // Retire the actual engine; no private status or state-cell mutation.
    let old = f.store;
    drop(old);
    f.store = open(f.root.path(), false);
    let complete = prepare(&f);
    assert_eq!(complete.action(), MigrationAction::Complete);
    let receipt = complete.progress().clone();
    let encoded = receipt.encode().unwrap();
    f.store.apply(complete.into_batch()).unwrap();
    let observed = receipt.result_namespace().unwrap();
    assert_eq!(observed.status, NamespaceStatus::Quiescing);
    assert_eq!(observed.version.incarnation, 1);
    assert_eq!(receipt.result_history().unwrap().epochs.schema, 2);
    assert_eq!(receipt.result_history().unwrap().epochs.recovery, 1);
    assert_old_rollback_refused(&f, &observed);
    let active = activate(&f);
    assert_actual_tagged_value(&f, &active);
    let replay = prepare(&f);
    assert_eq!(replay.action(), MigrationAction::Replay);
    assert_eq!(replay.progress().encode().unwrap(), encoded);
    f.store.apply(replay.into_batch()).unwrap();
    assert_eq!(
        NamespaceRecoveryView::capture(&f.store.snapshot().unwrap(), &active.tenant, &active.id)
            .unwrap()
            .namespace,
        active
    );
}
fn assert_old_rollback_refused(f: &Fixture, namespace: &NamespaceRecord) {
    let v1 = schema_ids().unwrap().0;
    let old = ReviewedSchema::accept_with(
        SchemaDeclaration {
            package_digest: [41; 32],
            readers: vec![v1.clone()],
            writers: vec![v1],
        },
        [41; 32],
        [40; 32],
        |_, _, _| Ok(()),
    )
    .unwrap();
    assert_eq!(
        old.require_namespace(namespace),
        Err(crate::namespace::NamespaceError::UnsupportedFormat)
    );
    assert!(crate::namespace::compatibility::require_composition(
        namespace,
        &[old, f.schema.clone()]
    )
    .is_err());
}
fn assert_actual_tagged_value(f: &Fixture, namespace: &NamespaceRecord) {
    let view = f.store.snapshot().unwrap();
    let mut scope = f.request.scope.clone();
    scope.state_schema = namespace.state_schema.clone();
    assert!(matches!(
        StateSession::open(
            &view,
            f.request.scope.clone(),
            SessionLimits::default(),
            |_, _| Ok(())
        ),
        Err(StateError::PermissionDenied)
    ));
    let mut session =
        StateSession::open(
            &view,
            scope.clone(),
            SessionLimits::default(),
            |_, _| Ok(()),
        )
        .unwrap();
    let value = session
        .get(&view, b"count", |_, _| Ok(()))
        .unwrap()
        .unwrap()
        .value;
    assert_eq!(
        value.bytes,
        [b"AG\x02\0".as_slice(), &u64::MAX.to_le_bytes()].concat()
    );
    assert_eq!(value.media_type, "application/vnd.lsf.aggregate-v2");
    assert!(session
        .view_identity()
        .require_minimum(&scope, &f.request.expected_view)
        .is_err());
}

#[test]
fn fixed_migration_checkpoint_detects_changed_linked_rows_and_final_revocation_without_upgrading_data(
) {
    let f = fixture();
    let stage = prepare(&f);
    assert_eq!(
        f.store
            .apply_fenced(stage.into_batch(), || Err(StoreError::Unavailable)),
        Err(FencedStoreError::Fence(StoreError::Unavailable))
    );
    assert!(f
        .store
        .snapshot()
        .unwrap()
        .get(&f.request.progress_key().unwrap())
        .unwrap()
        .is_none());
    f.store.apply(prepare(&f).into_batch()).unwrap();
    let complete = prepare(&f);
    assert_eq!(
        f.store
            .apply_fenced(complete.into_batch(), || Err(StoreError::Unavailable)),
        Err(FencedStoreError::Fence(StoreError::Unavailable))
    );
    let key = RowKey {
        family: Family::Attempt,
        key: b"changed-linked-history".to_vec(),
    };
    f.store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key,
                value: Some(vec![1]),
            }],
        })
        .unwrap();
    let view = f.store.snapshot().unwrap();
    // The full canonical checkpoint comparison covers non-namespace families.
    let inspected = VerifiedMigrationCheckpoint::inspect(
        &view,
        &mut Cursor::new(&f.checkpoint),
        deadline(),
        |key, bytes| validate_row(&view, key, bytes),
        |_| {
            Ok(SnapshotClosure {
                inventory: RetainedInventory::default(),
                required_artifacts: artifacts(),
            })
        },
        |_| Ok(()),
    )
    .unwrap();
    assert!(matches!(
        AggregateMigrationPlan::prepare(
            &view,
            &f.request,
            &inspected,
            &f.schema,
            MigrationAction::Complete,
            deadline(),
            |_, _, _| Ok(())
        ),
        Err(StoreError::Conflict)
    ));
    let actual =
        NamespaceRecoveryView::capture(&view, &f.request.scope.tenant, &f.request.scope.namespace)
            .unwrap();
    assert_eq!(
        actual.namespace.state_schema,
        schema_ids().unwrap().0.as_str()
    );
    assert_eq!(actual.history.epochs.schema, 1);
    assert_eq!(
        require_resume_ready(&view, &actual.namespace),
        Err(StoreError::Unavailable)
    );
}

#[test]
fn fixed_migration_rejects_corrupt_checkpoint_wrong_scope_package_and_changed_operation_inputs() {
    let f = fixture();
    let view = f.store.snapshot().unwrap();
    let mut corrupted = f.checkpoint.clone();
    corrupted[64] ^= 1;
    assert!(VerifiedMigrationCheckpoint::inspect(
        &view,
        &mut Cursor::new(corrupted),
        deadline(),
        |key, bytes| validate_row(&view, key, bytes),
        closure,
        |_| Ok(())
    )
    .is_err());
    let inspected = checkpoint(&f, &view);
    let mut wrong = f.request.clone();
    wrong.scope.tenant = TenantId("other".into());
    assert_eq!(wrong.validate(), Err(StoreError::Invalid));
    let other = schema([47; 32]);
    assert!(AggregateMigrationPlan::prepare(
        &view,
        &f.request,
        &inspected,
        &other,
        MigrationAction::Stage,
        deadline(),
        |_, _, _| Ok(())
    )
    .is_err());
    drop(view);
    f.store.apply(prepare(&f).into_batch()).unwrap();
    let view = f.store.snapshot().unwrap();
    let checkpoint = checkpoint(&f, &view);
    let mut changed = f.request.clone();
    changed.review_digest = [48; 32];
    assert!(matches!(
        AggregateMigrationPlan::prepare(
            &view,
            &changed,
            &checkpoint,
            &f.schema,
            MigrationAction::Complete,
            deadline(),
            |_, _, _| Ok(())
        ),
        Err(StoreError::Conflict)
    ));
    let row = view
        .get(&f.request.progress_key().unwrap())
        .unwrap()
        .unwrap();
    let mut trailing = row.clone();
    trailing.push(b' ');
    assert_eq!(
        AggregateMigrationProgress::decode(&trailing),
        Err(StoreError::Corrupt)
    );
    assert!(AggregateMigrationProgress::decode(&row[..row.len() - 1]).is_err());
}

#[test]
fn fixed_migration_refuses_oversized_cell_and_quota_before_durable_stage() {
    // A valid shared state value is outside this tiny fixed recipe's input
    // ceiling. Refusal occurs in the engine scan before the value is decoded.
    let oversized = fixture_with_count(vec![7; 8192], NamespaceQuota::default());
    // The original shared codec uses 65 bytes for this exact count key/value.
    // The tagged value needs four more; both checkpoints are otherwise valid.
    let quota = fixture_with_count(
        u64::MAX.to_le_bytes().to_vec(),
        NamespaceQuota {
            state_bytes: 65,
            ..NamespaceQuota::default()
        },
    );
    for f in [oversized, quota] {
        let view = f.store.snapshot().unwrap();
        let before = NamespaceRecoveryView::capture(
            &view,
            &f.request.scope.tenant,
            &f.request.scope.namespace,
        )
        .unwrap();
        let inspected = checkpoint(&f, &view);
        assert!(matches!(
            AggregateMigrationPlan::prepare(
                &view,
                &f.request,
                &inspected,
                &f.schema,
                MigrationAction::Stage,
                deadline(),
                |_, _, _| Ok(())
            ),
            Err(StoreError::Capacity)
        ));
        assert!(view
            .get(&f.request.progress_key().unwrap())
            .unwrap()
            .is_none());
        let after = NamespaceRecoveryView::capture(
            &view,
            &f.request.scope.tenant,
            &f.request.scope.namespace,
        )
        .unwrap();
        assert_eq!(after.namespace, before.namespace);
        assert_eq!(after.history, before.history);
        assert_eq!(after.guard, before.guard);
    }
}

#[test]
fn migration_row_dispatch_preserves_foreign_bytes_and_rejects_malformed_owned_progress() {
    let f = fixture();
    let progress = prepare(&f).progress().encode().unwrap();
    let key = f.request.progress_key().unwrap();
    AggregateMigrationProgress::validate_row(&key, &progress).unwrap();

    let foreign = RowKey {
        family: Family::Maintenance,
        key: b"dispatch-owner-v1\0".to_vec(),
    };
    for bytes in [b"LDO\0\x01".as_slice(), b"{}", &progress] {
        assert_eq!(
            AggregateMigrationProgress::validate_row(&foreign, bytes),
            Err(StoreError::UnsupportedFormat)
        );
    }
    let wrong_family = RowKey {
        family: Family::State,
        key: key.key.clone(),
    };
    assert_eq!(
        AggregateMigrationProgress::validate_row(&wrong_family, &progress),
        Err(StoreError::UnsupportedFormat)
    );
    for bytes in [
        b"LDO\0\x01".as_slice(),
        b"{}",
        &progress[..progress.len() - 1],
    ] {
        assert_eq!(
            AggregateMigrationProgress::validate_row(&key, bytes),
            Err(StoreError::Corrupt)
        );
    }
    let mut wrong_identity = key;
    *wrong_identity.key.last_mut().unwrap() ^= 1;
    assert_eq!(
        AggregateMigrationProgress::validate_row(&wrong_identity, &progress),
        Err(StoreError::Corrupt)
    );
}

//! Actual current HTTP dispatcher plus an explicit original-v1 offline fixture.
//! Synthetic installed codecs do not qualify a released node or guest workflow.
use super::{fixture::*, proxy::Fault};
use latent_effects::{
    authority::{DurableEffectAuthority, EffectAuthorityOwner},
    dispatch::{Disposition, EffectRecord},
    dispatch_store::DispatchCatalog,
    recovery_close::{ClosePlan, CloseReceipt},
    runtime::{DeferredEffectAdapter, EffectTimeSource},
};
use latent_state::{
    embedded::{AtomicBatch, ExpectedRow, Family, RowKey, RowMutation, StoreError},
    namespace::{namespace_record_key, NamespaceRecord, NamespaceTransition},
    protected_store::{ProtectedStoreConfig, ProtectedStoreOwner},
    recovery::v1::{
        offline::{
            OfflineRecoverySource, OfflineRestoreRequest, RecoveryCodecs, RecoveryReviewRequest,
            RetainedReconciliationRequest, SnapshotFile,
        },
        restore::RestoreRequest,
        resume::NamespaceResumeRequest,
        RecoveryStatus,
    },
    store_io::StoreIoKind,
};
use std::{fs, os::unix::fs::PermissionsExt, sync::Arc, time::Instant};

mod close;
mod codecs;

struct Workload {
    authority: DurableEffectAuthority,
    command: Vec<u8>,
}

fn private_root() -> tempfile::TempDir {
    let root = tempfile::tempdir().unwrap();
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).unwrap();
    root
}

async fn namespace(fixture: &Fixture, transition: NamespaceTransition) {
    call(&fixture.store, StoreIoKind::Write, move |db| {
        let view = db.snapshot().unwrap();
        let key = RowKey {
            family: Family::Namespace,
            key: namespace_record_key(&scope().tenant, &scope().namespace).unwrap(),
        };
        let old = view.get(&key).unwrap().unwrap();
        let namespace = NamespaceRecord::decode(&old).unwrap();
        let next = namespace
            .transition(namespace.version, &transition, 0)
            .unwrap();
        drop(view);
        db.apply(AtomicBatch {
            expectations: vec![ExpectedRow {
                key: key.clone(),
                value: Some(old),
            }],
            mutations: vec![RowMutation {
                key,
                value: Some(next.encode().unwrap()),
            }],
        })
        .unwrap();
    })
    .await;
}

async fn offline(
    config: &ProtectedStoreConfig,
    codecs: Arc<codecs::Codecs>,
    review: bool,
) -> OfflineRecoverySource {
    let mut config = config.clone();
    config.create_if_missing = false;
    if review {
        OfflineRecoverySource::start_review(config, "tests".into(), codecs)
    } else {
        OfflineRecoverySource::start(config, "tests".into(), codecs)
    }
    .unwrap()
    .await
    .unwrap()
}

async fn retire(source: OfflineRecoverySource) {
    source.close();
    let deadline = Instant::now() + WATCHDOG;
    let report = source
        .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
        .unwrap()
        .await;
    assert!(
        report.clean && report.snapshot.physically_retired(),
        "{report:?}"
    );
    source.reap_retired_threads().unwrap();
}

async fn reopen(fixture: &mut Fixture) {
    let mut config = fixture.store_config.clone();
    config.create_if_missing = false;
    fixture.store = Arc::new(
        ProtectedStoreOwner::start_validated_view(config, 0, codecs::Codecs::validate)
            .unwrap()
            .await
            .unwrap(),
    );
    fixture
        .store
        .bind_native_capacity(&fixture.native_capacity)
        .unwrap();
    let checkpoint = call(&fixture.store, StoreIoKind::Read, |db| {
        DispatchCatalog::owner_checkpoint(&db.snapshot().unwrap()).unwrap()
    })
    .await;
    fixture.start(true, checkpoint).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[expect(clippy::too_many_lines, reason = "one bounded backup, remote apply, restore, close and resume ownership schedule")]
async fn actual_tls_mutation_restored_pending_closes_without_redrive_under_current_dispatcher() {
    let mut fixture = Fixture::new(Fault::LosePostReply).await;
    let schema = codecs::schema_artifact().identity;
    let mut state_scope = scope();
    state_scope.state_schema.clone_from(&schema);
    call(&fixture.store, StoreIoKind::Write, move |db| {
        let view = db.snapshot().unwrap();
        let key = RowKey {
            family: Family::Namespace,
            key: namespace_record_key(&scope().tenant, &scope().namespace).unwrap(),
        };
        let old = view.get(&key).unwrap().unwrap();
        let mut namespace = NamespaceRecord::decode(&old).unwrap();
        namespace.state_schema = schema;
        drop(view);
        db.apply(AtomicBatch {
            expectations: vec![ExpectedRow {
                key: key.clone(),
                value: Some(old),
            }],
            mutations: vec![RowMutation {
                key,
                value: Some(namespace.encode().unwrap()),
            }],
        })
        .unwrap();
    })
    .await;
    let authority = fixture
        .commit_with_state_scope("restored-close-current", state_scope)
        .await;
    let command = call(&fixture.store, StoreIoKind::Read, |db| {
        let rows = db
            .snapshot()
            .unwrap()
            .scan(Family::Command, b"", 2, 65536)
            .unwrap();
        assert_eq!(rows.len(), 1);
        rows[0].1.clone()
    })
    .await;
    let workload = Workload { authority, command };
    let codecs = codecs::Codecs::with_close(&fixture, &workload);
    namespace(&fixture, NamespaceTransition::Quiesce).await;
    fixture.stop_dispatcher().await;
    fixture.stop_store().await;
    let source = offline(&fixture.store_config, codecs.clone(), false).await;
    eprintln!("native-recovery: original-offline-open");
    let backup = private_root();
    let input = SnapshotFile {
        root: backup.path().into(),
        file_name: "synthetic-native-backup".into(),
    };
    let snapshot = source
        .backup_to(input.clone(), codecs.metadata(), Instant::now() + WATCHDOG)
        .unwrap()
        .await
        .unwrap();
    let observed = source
        .inspect_namespace(
            "operator".into(),
            scope().namespace,
            Instant::now() + WATCHDOG,
        )
        .unwrap()
        .await
        .unwrap();
    eprintln!("native-recovery: original-backup-and-inspection-complete");
    source
        .resume_namespace(
            NamespaceResumeRequest {
                scope: observed.scope(),
                operator_id: "operator".into(),
                operation_id: "native-original-after-backup".into(),
                expected_view: observed.view_token().unwrap(),
                review_digest: [71; 32],
            },
            Instant::now() + WATCHDOG,
        )
        .unwrap()
        .await
        .unwrap();
    eprintln!("native-recovery: original-resume-complete");
    retire(source).await;
    eprintln!("native-recovery: original-offline-retired");
    reopen(&mut fixture).await;
    eprintln!("native-recovery: original-dispatch-reopened");
    fixture.owner.as_ref().unwrap().resume().unwrap();
    fixture
        .settled(&workload.authority, Disposition::RetryScheduled)
        .await;
    fixture.owner.as_ref().unwrap().pause();
    assert_eq!(fixture.endpoint.counter().await, 1);
    assert_eq!(
        fixture
            .proxy
            .posts
            .load(std::sync::atomic::Ordering::Acquire),
        1
    );
    let remote = fixture
        .endpoint
        .record(&format!("lsf-effect-{}", workload.authority.link().effect))
        .await;
    eprintln!("native-recovery: remote-mutation-observed");
    namespace(&fixture, NamespaceTransition::Quiesce).await;
    fixture.stop_dispatcher().await;
    fixture.stop_store().await;
    let source = offline(&fixture.store_config, codecs.clone(), false).await;
    let destination = private_root();
    let mut request = OfflineRestoreRequest {
        input,
        destination: ProtectedStoreConfig::bounded_linux(destination.path().into()),
        review: RestoreRequest {
            operation_id: "native-restore-close".into(),
            operator_id: "operator".into(),
            snapshot_digest: snapshot.snapshot_digest,
            runtime_digest: codecs.runtime_digest(),
            window_acknowledgement: [1; 32],
        },
    };
    let inspection = source
        .inspect_restore(request.clone(), Instant::now() + WATCHDOG)
        .unwrap()
        .await
        .unwrap();
    request.review.window_acknowledgement = inspection.window.digest().unwrap();
    let restored = source
        .restore_to(request, Instant::now() + WATCHDOG)
        .unwrap()
        .await
        .unwrap();
    eprintln!("native-recovery: actual-restore-complete");
    assert_eq!(
        restored.guard.status(),
        RecoveryStatus::ReconciliationRequired
    );
    retire(source).await;
    let restored_config = ProtectedStoreConfig::bounded_linux(destination.path().into());
    let source = offline(&restored_config, codecs.clone(), true).await;
    let inspected = source
        .inspect_retained_reconciliation(
            RetainedReconciliationRequest {
                operator_id: "operator".into(),
                operation_id: "native-close-original".into(),
                payload: b"inspect-close".to_vec(),
            },
            Instant::now() + WATCHDOG,
        )
        .unwrap()
        .await
        .unwrap();
    let plan = ClosePlan::decode(&inspected).unwrap();
    eprintln!("native-recovery: restored-pending-inspected");
    assert_eq!(plan.effects[0].original_disposition, Disposition::Pending);
    assert_eq!(fixture.endpoint.counter().await, 1);
    *codecs.close_approval.lock().unwrap() = Some(plan.digest().unwrap());
    let request = RetainedReconciliationRequest {
        operator_id: "operator".into(),
        operation_id: plan.operation_id.clone(),
        payload: plan.encode().unwrap(),
    };
    let receipt = source
        .reconcile_retained(request.clone(), Instant::now() + WATCHDOG)
        .unwrap()
        .await
        .unwrap();
    let receipt = CloseReceipt::decode(&receipt).unwrap();
    eprintln!("native-recovery: original-effect-closed");
    assert_eq!(receipt.outcome, "closed-without-redrive");
    assert_eq!(
        source
            .reconcile_retained(request, Instant::now() + WATCHDOG)
            .unwrap()
            .await
            .unwrap(),
        receipt.encode().unwrap()
    );
    let review_digest =
        codecs.approve_reconciliation(&restored.guard, remote["bodyDigest"].as_str().unwrap());
    source
        .review_reconciliation(
            RecoveryReviewRequest {
                operator_id: "operator".into(),
                expected_guard: restored.guard,
                review_digest,
            },
            Instant::now() + WATCHDOG,
        )
        .unwrap()
        .await
        .unwrap();
    let observed = source
        .inspect_namespace(
            "operator".into(),
            scope().namespace,
            Instant::now() + WATCHDOG,
        )
        .unwrap()
        .await
        .unwrap();
    source
        .resume_namespace(
            NamespaceResumeRequest {
                scope: observed.scope(),
                operator_id: "operator".into(),
                operation_id: "native-resume-closed".into(),
                expected_view: observed.view_token().unwrap(),
                review_digest: [71; 32],
            },
            Instant::now() + WATCHDOG,
        )
        .unwrap()
        .await
        .unwrap();
    retire(source).await;
    fixture.store_config = restored_config;
    reopen(&mut fixture).await;
    fixture.owner.as_ref().unwrap().resume().unwrap();
    assert_eq!(
        fixture.record(&workload.authority).await.disposition(),
        Disposition::DeadLettered
    );
    assert!(fixture
        .record(&workload.authority)
        .await
        .recovery_close_digest()
        .is_some());
    assert_eq!(fixture.endpoint.counter().await, 1);
    assert_eq!(
        fixture
            .proxy
            .posts
            .load(std::sync::atomic::Ordering::Acquire),
        1
    );
    assert_eq!(fixture.pool_snapshot().await.connections, 0);
    fixture.finish().await;
}

//! Actual migrated snapshot, Fresh import, physical adoption and affine resume.
//! Reviewers are explicit controlled owners, not authenticated operator proof.
use super::*;
use crate::{
    embedded::{AtomicBatch, ReadView},
    namespace::{namespace_record_key, NamespaceTransition},
    protected_store::{
        RestoreAdoptionFence, RestoreAdoptionOwners, RestoreAdoptionRequest, RestoreStageReceipt,
        RestoreStageRequest, RestoredMigrationResumeCommitFence, RestoredMigrationResumeOwners,
    },
    recovery::{
        migration::tests::fixture as logical,
        namespace_resume::NamespaceRecoveryView,
        restored_resume::{RestoredMigrationResumeObservation, RestoredMigrationResumeRequest},
        snapshot::{RequiredArtifact, SnapshotClosure},
        RecoveryGuard,
    },
};
use fixture::StageOwners;
use sha2::{Digest, Sha256};
use std::sync::atomic::AtomicU8;

struct Adoption(Arc<StageOwners>);
impl RestoreAdoptionOwners for Adoption {
    fn review(
        &self,
        view: &ReadView,
        stage: &RestoreStageReceipt,
        _: &RestoreAdoptionRequest,
    ) -> Result<(), StoreError> {
        self.0.review_reopened(view, stage.input(), stage.request())
    }
    fn current_role(&self) -> Result<(), StoreError> {
        self.0.current_role()
    }
    fn current_audit(&self) -> Result<(), StoreError> {
        self.0.current_audit()
    }
    fn current_publication(&self) -> Result<(), StoreError> {
        self.0.current_controls()
    }
    fn current_clock(&self) -> Result<(), StoreError> {
        self.0.current_clock()
    }
    fn accept(&self, original: RestoreAdoptionFence<'_>) -> Result<(), StoreError> {
        original.accept()
    }
}

struct ResumeOwners {
    source: Arc<Owners>,
    accept_mode: AtomicU8,
}
impl RestoredMigrationResumeOwners for ResumeOwners {
    fn row(&self, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
        self.source.row(key, bytes)
    }
    fn artifact(&self, required: &RequiredArtifact) -> Result<(), StoreError> {
        self.source.artifact(required)
    }
    fn linked(&self, view: &ReadView) -> Result<SnapshotClosure, StoreError> {
        logical::closure(view, vec![])
    }
    fn review(
        &self,
        _: &ReadView,
        request: &RestoredMigrationResumeRequest,
        observation: RestoredMigrationResumeObservation<'_>,
    ) -> Result<(), StoreError> {
        if request.operator_id != "operator"
            || request.migration_operation_id != "change-format"
            || !observation.progress.completed()
            || request.review_digest != [93; 32]
        {
            return Err(StoreError::UnsupportedFormat);
        }
        Ok(())
    }
    fn accept(&self, original: RestoredMigrationResumeCommitFence<'_>) -> Result<(), StoreError> {
        match self.accept_mode.load(Ordering::SeqCst) {
            0 => original.accept(),
            1 => Err(StoreError::Unavailable),
            2 => Ok(()),
            _ => Err(StoreError::Invalid),
        }
    }
}

struct Restored {
    setup: Setup,
    root: tempfile::TempDir,
    checkpoint: tempfile::TempDir,
    adopted: ProtectedStoreOwner,
    owners: Arc<ResumeOwners>,
    request: RestoredMigrationResumeRequest,
}

#[expect(
    clippy::too_many_lines,
    reason = "One actual finite migrate/export/Fresh-import/adoption/guard-review sequence retains every independent owner"
)]
fn restored() -> Restored {
    let mut setup = Setup::with_finite_java_restore_profile();
    let (snapshot, owners, request) = setup.checkpoint_profile(
        "original-migration.v2",
        ProtectedSnapshotProfile::SingleNamespace,
    );
    let (snapshot, staged) = setup.migrate(snapshot, &owners, &request, MigrationPhase::Stage);
    drop(staged.unwrap().unwrap());
    let (snapshot, completed) =
        setup.migrate(snapshot, &owners, &request, MigrationPhase::Complete);
    drop(completed.unwrap().unwrap());
    setup.retire(snapshot);
    setup.refresh_current_seed();
    let (snapshot, owners, request) =
        setup.checkpoint_profile("migrated.v2", ProtectedSnapshotProfile::SingleNamespace);
    setup.retire(snapshot);
    let (root, _) = super::super::fixture();
    let (checkpoint, _) = super::super::fixture();
    let mut destination =
        super::restore_stage::destination(root.path(), checkpoint.path(), 8 * 1024 * 1024);
    destination.store.io.resident_bytes = 8 * 1024 * 1024 + 256 * 1024;
    destination.store.io.recovery.as_mut().unwrap().job_bytes = 8 * 1024 * 1024 + 8192;
    destination
        .store
        .io
        .recovery
        .as_mut()
        .unwrap()
        .retained_bytes = 16 * 1024 * 1024;
    let row = Arc::clone(&owners);
    let current = Arc::clone(&owners);
    let (snapshot, opened) = wait(
        setup
            .owner
            .open_snapshot_for_restore_profile(
                setup.snapshot_config("migrated.v2"),
                destination,
                Arc::clone(setup.original()),
                move |key, bytes| row.row(key, bytes),
                Arc::new(move || current.current()),
                crate::recovery::snapshot::SNAPSHOT_FILE_BYTES,
                ProtectedSnapshotProfile::SingleNamespace,
            )
            .unwrap(),
    )
    .unwrap();
    drop(opened.unwrap().unwrap());
    let (snapshot, input) = wait(
        setup
            .owner
            .review_restore_window(snapshot, restore_input(&request), owners.clone())
            .unwrap(),
    )
    .unwrap();
    let input = input.unwrap().unwrap();
    let stage_request = RestoreStageRequest {
        operation_id: "restore-original-backup".into(),
        operator_id: "restore-operator".into(),
        runtime_digest: input.snapshot().manifest.metadata.runtime_digest,
        loss_window_acknowledgement: input.window().digest().unwrap(),
    };
    let stage_owners = Arc::new(StageOwners::new(&setup, &owners));
    let (snapshot, staged) = wait(super::restore_stage::job(
        &setup,
        snapshot,
        input,
        &stage_owners,
        stage_request,
    ))
    .unwrap();
    let staged = staged.unwrap().unwrap();
    let operation_digest = staged.operation_digest();
    let window_digest = staged.request().loss_window_acknowledgement;
    let adoption = RestoreAdoptionRequest {
        operator_id: staged.request().operator_id.clone(),
        operation_digest,
        checkpoint_digest: Sha256::digest(staged.checkpoint().encode()).into(),
        loss_window_acknowledgement: window_digest,
    };
    let (snapshot, plan) = wait(
        setup
            .owner
            .prepare_restore_adoption(snapshot, staged, adoption, Arc::new(Adoption(stage_owners)))
            .unwrap(),
    )
    .unwrap();
    let plan = plan.unwrap().unwrap();
    wait(snapshot.retire());
    setup
        .owner
        .ready
        .wait_test_metadata_retirement(Instant::now() + WATCHDOG);
    assert!(finish(&setup.owner).clean);
    plan.check_retired().unwrap();
    let adopted = wait(
        plan.start(Arc::new(latent_core::SystemActivationClock))
            .unwrap(),
    )
    .unwrap();
    adopted.bind_native_capacity(&setup.native).unwrap();
    let request = wait(
        adopted
            .with_store_retaining(
                StoreIoKind::RecoveryWrite,
                256 * 1024,
                Arc::clone(setup.original()) as Arc<dyn std::any::Any + Send + Sync>,
                move |engine| {
                    let view = engine.snapshot()?;
                    let guard = RecoveryGuard::capture(&view)?.ok_or(StoreError::Corrupt)?;
                    let reviewed = guard.prepare_reviewed(&view, [93; 32], |_, _, _| Ok(()))?;
                    drop(view);
                    engine.apply(reviewed)?;
                    let view = engine.snapshot()?;
                    let scope = &request.scope;
                    let current =
                        NamespaceRecoveryView::capture(&view, &scope.tenant, &scope.namespace)?;
                    Ok(RestoredMigrationResumeRequest {
                        scope: current.scope(),
                        operation_id: "activate-restored-migration".into(),
                        operator_id: "operator".into(),
                        migration_operation_id: "change-format".into(),
                        expected_view: current.view_token()?,
                        snapshot_digest: request.checkpoint_digest,
                        manifest_digest: request.checkpoint_manifest_digest,
                        restore_operation_digest: operation_digest,
                        window_digest,
                        review_digest: [93; 32],
                    })
                },
            )
            .unwrap(),
    )
    .unwrap()
    .unwrap();
    Restored {
        setup,
        root,
        checkpoint,
        adopted,
        owners: Arc::new(ResumeOwners {
            source: owners,
            accept_mode: AtomicU8::new(0),
        }),
        request,
    }
}

impl Restored {
    fn open(&self) -> ProtectedSnapshot {
        let row = Arc::clone(&self.owners);
        let current = Arc::clone(&self.owners);
        let (snapshot, opened) = wait(
            self.adopted
                .open_snapshot_profile(
                    self.setup.snapshot_config("migrated.v2"),
                    Arc::clone(self.setup.original()),
                    move |key, bytes| row.row(key, bytes),
                    Arc::new(move || current.source.current()),
                    crate::recovery::snapshot::SNAPSHOT_FILE_BYTES,
                    ProtectedSnapshotProfile::SingleNamespace,
                )
                .unwrap(),
        )
        .unwrap();
        drop(opened.unwrap().unwrap());
        snapshot
    }
    fn retire(&self, mut snapshot: ProtectedSnapshot) {
        let witness = snapshot.retirement_witness().unwrap();
        wait(snapshot.retire());
        self.adopted
            .ready
            .wait_test_metadata_retirement(Instant::now() + WATCHDOG);
        assert!(witness.has_retired());
        assert!(!self.adopted.snapshot().unwrap().custody_active);
    }
}

#[test]
#[expect(
    clippy::too_many_lines,
    reason = "Revoked/ignored fences, activation, file retirement, lost-response replay and original response capacity are one physical schedule"
)]
fn actual_migrated_backup_fresh_restore_activates_only_with_same_physical_writer_and_native_fence()
{
    let mut fixture = restored();
    for mode in [1, 2] {
        fixture.owners.accept_mode.store(mode, Ordering::SeqCst);
        let (returned, result) = wait(
            fixture
                .adopted
                .resume_restored_migration(
                    fixture.open(),
                    fixture.request.clone(),
                    fixture.setup.schema(),
                    fixture.owners.clone(),
                )
                .unwrap(),
        )
        .unwrap();
        let refused = result
            .unwrap()
            .err()
            .expect("revoked or ignored native fence must refuse");
        assert_eq!(refused, MigrationError::Review(StoreError::Unavailable));
        fixture.retire(returned);
        assert_eq!(fixture.adopted.failure(), None);
        let snapshot = fixture.open();
        fixture.retire(snapshot);
    }
    fixture.owners.accept_mode.store(0, Ordering::SeqCst);
    let (snapshot, result) = wait(
        fixture
            .adopted
            .resume_restored_migration(
                fixture.open(),
                fixture.request.clone(),
                fixture.setup.schema(),
                fixture.owners.clone(),
            )
            .unwrap(),
    )
    .unwrap();
    let receipt = result.unwrap().unwrap();
    let encoded = receipt.receipt().encode().unwrap();
    assert!(!receipt.replayed());
    assert!(encoded.starts_with(b"RMA\x01"));
    assert_eq!(
        receipt.receipt().namespace().status,
        NamespaceStatus::Active
    );
    assert_eq!(receipt.receipt().history().epochs.recovery, 2);
    fixture.retire(snapshot);
    assert_eq!(fixture.setup.native.snapshot().unwrap().recovery.slots, 1);
    drop(receipt);
    let scope = fixture.request.scope.clone();
    wait(
        fixture
            .adopted
            .with_store_retaining(
                StoreIoKind::RecoveryWrite,
                64 * 1024,
                Arc::clone(fixture.setup.original()) as Arc<dyn std::any::Any + Send + Sync>,
                move |engine| {
                    let view = engine.snapshot()?;
                    let current =
                        NamespaceRecoveryView::capture(&view, &scope.tenant, &scope.namespace)?;
                    let quiesced = current
                        .namespace
                        .transition(current.namespace.version, &NamespaceTransition::Quiesce, 0)
                        .unwrap();
                    drop(view);
                    engine.apply(AtomicBatch {
                        expectations: vec![],
                        mutations: vec![RowMutation {
                            key: RowKey {
                                family: Family::Namespace,
                                key: namespace_record_key(&scope.tenant, &scope.namespace).unwrap(),
                            },
                            value: Some(quiesced.encode().unwrap()),
                        }],
                    })?;
                    Ok(())
                },
            )
            .unwrap(),
    )
    .unwrap()
    .unwrap();
    let (snapshot, replay) = wait(
        fixture
            .adopted
            .resume_restored_migration(
                fixture.open(),
                fixture.request.clone(),
                fixture.setup.schema(),
                fixture.owners.clone(),
            )
            .unwrap(),
    )
    .unwrap();
    let replay = replay.unwrap().unwrap();
    assert!(replay.replayed());
    assert_eq!(replay.receipt().encode().unwrap(), encoded);
    fixture.retire(snapshot);
    let original = Arc::downgrade(fixture.setup.original());
    let native = fixture.setup.native.clone();
    fixture.setup.release_original();
    assert!(original.upgrade().is_some());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    drop(replay);
    assert!(original.upgrade().is_none());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 0);
    let scope = fixture.request.scope;
    wait(
        fixture
            .adopted
            .with_store(StoreIoKind::RecoveryRead, 256 * 1024, move |engine| {
                let view = engine.snapshot()?;
                let current =
                    NamespaceRecoveryView::capture(&view, &scope.tenant, &scope.namespace)?;
                assert_eq!(current.namespace.status, NamespaceStatus::Quiescing);
                let mut census = crate::tenant::TenantCensus::capture(
                    &view,
                    &[crate::tenant::inspect(&view, &scope.tenant)?.unwrap().quota],
                    crate::tenant::GlobalMetadataAllowance {
                        rows: 64,
                        bytes: 256 * 1024,
                    },
                    Instant::now() + WATCHDOG,
                )?;
                crate::recovery::snapshot::visit_view(
                    &view,
                    Instant::now() + WATCHDOG,
                    |_, key, bytes| {
                        census.observe(
                            key,
                            bytes,
                            crate::tenant::census_contribution(&view, key, bytes)?,
                        )
                    },
                )?;
                census.finish()?;
                Ok(())
            })
            .unwrap(),
    )
    .unwrap()
    .unwrap();
    assert!(finish(&fixture.adopted).clean);
    drop((
        fixture.owners,
        fixture.setup,
        fixture.root,
        fixture.checkpoint,
    ));
    assert_eq!(native.snapshot().unwrap().recovery.slots, 0);
}

#[test]
fn restored_activation_rejects_byte_identical_replacement_of_original_snapshot_without_mutation() {
    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;
    let fixture = restored();
    let snapshot = fixture.open();
    let config = fixture.setup.snapshot_config("migrated.v2");
    let path = config.root.join(config.file_name);
    let bytes = fs::read(&path).unwrap();
    fs::rename(&path, config.root.join("retained-original-migrated.v2")).unwrap();
    let mut replacement = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&path)
        .unwrap();
    replacement.write_all(&bytes).unwrap();
    replacement.sync_all().unwrap();
    drop(replacement);
    let (snapshot, refused) = wait(
        fixture
            .adopted
            .resume_restored_migration(
                snapshot,
                fixture.request.clone(),
                fixture.setup.schema(),
                fixture.owners.clone(),
            )
            .unwrap(),
    )
    .unwrap();
    assert!(matches!(
        refused.unwrap(),
        Err(MigrationError::Review(StoreError::Unavailable))
    ));
    fixture.retire(snapshot);
    assert_eq!(fixture.adopted.failure(), None);
    let scope = fixture.request.scope;
    wait(
        fixture
            .adopted
            .with_store(StoreIoKind::RecoveryRead, 64 * 1024, move |engine| {
                let view = engine.snapshot()?;
                let current =
                    NamespaceRecoveryView::capture(&view, &scope.tenant, &scope.namespace)?;
                assert_eq!(current.namespace.status, NamespaceStatus::Quiescing);
                assert_eq!(
                    current.history.status,
                    HistoryStatus::ReconciliationRequired
                );
                assert!(view
                    .scan(
                        Family::Maintenance,
                        crate::recovery::restored_resume::RECEIPT_PREFIX,
                        1,
                        8192
                    )?
                    .is_empty());
                Ok(())
            })
            .unwrap(),
    )
    .unwrap()
    .unwrap();
    assert_eq!(fs::read(&path).unwrap(), bytes);
    assert!(finish(&fixture.adopted).clean);
    drop((
        fixture.owners,
        fixture.setup,
        fixture.root,
        fixture.checkpoint,
    ));
}

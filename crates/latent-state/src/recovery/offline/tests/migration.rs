use super::*;
use crate::namespace::compatibility::{ReviewedSchema, SchemaDeclaration};
use crate::recovery::migration::{
    self, AggregateMigrationObservation, AggregateMigrationProgress, AggregateMigrationRequest,
    MigrationAction,
};

const V2: &[u8] =
    include_bytes!("../../../../../../contracts/state/application-aggregate-v2.schema.json");
struct MigrationCodecs {
    inner: Codecs,
}
fn artifacts() -> Vec<RequiredArtifact> {
    vec![
        artifact(),
        RequiredArtifact {
            identity: SchemaId::from_definition(V2).unwrap().as_str().into(),
            digest: Sha256::digest(V2).into(),
        },
        RequiredArtifact {
            identity: "lsf.aggregate-migration.v1".into(),
            digest: Sha256::digest(migration::RECIPE).into(),
        },
        RequiredArtifact {
            identity: migration::package_identity(&[83; 32]),
            digest: [83; 32],
        },
    ]
}
impl RecoveryCodecs for MigrationCodecs {
    fn runtime_digest(&self) -> [u8; 32] {
        [90; 32]
    }
    fn retained_bytes(&self) -> u64 {
        8192
    }
    fn scratch_bytes(&self) -> u64 {
        4 * 1024 * 1024
    }
    fn installed_formats(&self) -> &[RetainedFormat] {
        static FORMATS: std::sync::LazyLock<Vec<RetainedFormat>> = std::sync::LazyLock::new(|| {
            vec![
                crate::recovery::resume::retained_format(),
                migration::retained_format(),
            ]
        });
        &FORMATS
    }
    fn validate_row(&self, view: &ReadView, key: &RowKey, value: &[u8]) -> Result<(), StoreError> {
        if key.family == Family::Maintenance && key.key.starts_with(migration::PROGRESS_PREFIX) {
            AggregateMigrationProgress::validate_row(key, value)
        } else {
            self.inner.validate_row(view, key, value)
        }
    }
    fn validate_view(&self, view: &ReadView) -> Result<SnapshotClosure, StoreError> {
        let mut inventory = RetainedInventory::default();
        crate::recovery::snapshot::visit_view(view, Instant::now() + WATCHDOG, |_, key, bytes| {
            self.validate_row(view, key, bytes)?;
            let retained = if key.family == Family::Maintenance
                && key.key.starts_with(migration::PROGRESS_PREFIX)
            {
                Some((
                    migration::retained_format(),
                    u64::from(!AggregateMigrationProgress::decode(bytes)?.completed()),
                ))
            } else if key.family == Family::Maintenance
                && key.key.starts_with(crate::recovery::resume::RECEIPT_PREFIX)
            {
                Some((crate::recovery::resume::retained_format(), 0))
            } else {
                None
            };
            if let Some((format, unresolved)) = retained {
                inventory
                    .observe(
                        format,
                        RetainedCount {
                            rows: 1,
                            bytes: (key.key.len() + bytes.len()) as u64,
                            unresolved,
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
    fn verify_artifact(&self, value: &RequiredArtifact) -> Result<(), StoreError> {
        if self.inner.missing.load(Ordering::Acquire) {
            return Err(StoreError::Unavailable);
        }
        if !artifacts().contains(value) {
            return Err(StoreError::Corrupt);
        }
        Ok(())
    }
    fn review_backup(
        &self,
        view: &ReadView,
        metadata: &SnapshotMetadata,
        path: &SnapshotFile,
    ) -> Result<(), StoreError> {
        self.inner.review_backup(view, metadata, path)
    }
    fn authorize_inspection(
        &self,
        view: &ReadView,
        request: &OfflineRestoreRequest,
    ) -> Result<(), StoreError> {
        self.inner.authorize_inspection(view, request)
    }
    fn review_restore(
        &self,
        view: &ReadView,
        _: &RestoreWindow,
        request: &OfflineRestoreRequest,
    ) -> Result<(), StoreError> {
        self.inner.authorize_inspection(view, request)
    }
    fn authorize_namespace_inspection(
        &self,
        view: &ReadView,
        operator: &str,
        namespace: &StateNamespaceId,
    ) -> Result<(), StoreError> {
        self.inner
            .authorize_namespace_inspection(view, operator, namespace)
    }
    fn review_namespace_resume(
        &self,
        view: &ReadView,
        request: &NamespaceResumeRequest,
        observed: NamespaceResumeObservation<'_>,
    ) -> Result<(), StoreError> {
        self.inner.accept_namespace_resume(request)?;
        self.validate_view(view)?;
        if observed.namespace.tenant != request.scope.tenant {
            return Err(StoreError::Conflict);
        }
        Ok(())
    }
    fn accept_namespace_resume(&self, request: &NamespaceResumeRequest) -> Result<(), StoreError> {
        self.inner.accept_namespace_resume(request)
    }
    fn migration_schema(
        &self,
        _: &ReadView,
        request: &OfflineAggregateMigrationRequest,
    ) -> Result<ReviewedSchema, StoreError> {
        if self.inner.denied.load(Ordering::Acquire)
            || request.review.operator_id != "operator"
            || request.review.package_digest != [83; 32]
            || request.review.review_digest != [81; 32]
        {
            return Err(StoreError::Unavailable);
        }
        let (v1, v2) = migration::schema_ids()?;
        ReviewedSchema::accept_with(
            SchemaDeclaration {
                package_digest: [83; 32],
                readers: vec![v1, v2.clone()],
                writers: vec![v2],
            },
            [83; 32],
            [84; 32],
            |_, _, _| Ok(()),
        )
        .map_err(|_| StoreError::Unavailable)
    }
    fn review_migration(
        &self,
        view: &ReadView,
        request: &OfflineAggregateMigrationRequest,
        observed: AggregateMigrationObservation<'_>,
    ) -> Result<(), StoreError> {
        self.migration_schema(view, request)?;
        self.validate_view(view)?;
        if observed.current.namespace.tenant != request.review.scope.tenant {
            return Err(StoreError::Conflict);
        }
        if observed
            .original_progress
            .is_some_and(|progress| !progress.completed())
        {
            if let Some((gates, notice)) = &self.inner.pause {
                let (registration, mut tracked) = gates.track(()).unwrap();
                tracked.commit(Stage::Entered).unwrap();
                wait(async {
                    let mut pause = Box::pin(tracked.pause());
                    PollProbe::default().pending(pause.as_mut());
                    notice
                        .send(gates.blocked(registration, Stage::Entered).unwrap())
                        .unwrap();
                    pause.await;
                });
            }
        }
        Ok(())
    }
    fn accept_migration(
        &self,
        request: &OfflineAggregateMigrationRequest,
        _: MigrationAction,
    ) -> Result<(), StoreError> {
        if self.inner.denied.load(Ordering::Acquire)
            || request.review.operator_id != "operator"
            || request.review.review_digest != [81; 32]
        {
            return Err(StoreError::Unavailable);
        }
        Ok(())
    }
}
fn codecs() -> Arc<MigrationCodecs> {
    Arc::new(MigrationCodecs {
        inner: Codecs {
            denied: AtomicBool::new(false),
            missing: AtomicBool::new(false),
            pause: None,
        },
    })
}
fn open_source(path: &Path, owner: Arc<MigrationCodecs>) -> OfflineRecoverySource {
    wait(
        OfflineRecoverySource::start_review(
            ProtectedStoreConfig::bounded_linux(path.into()),
            "tenant".into(),
            owner,
        )
        .unwrap(),
    )
    .unwrap()
}
fn prepared() -> (
    tempfile::TempDir,
    tempfile::TempDir,
    OfflineAggregateMigrationRequest,
) {
    let original = root();
    let backup = root();
    let owner = populated_owner(original.path());
    finish(&owner);
    let decoder = codecs();
    let source = open_source(original.path(), decoder.clone());
    let checkpoint = SnapshotFile {
        root: backup.path().into(),
        file_name: "before-schema-change".into(),
    };
    let mut meta = metadata();
    meta.decoder_formats = decoder.installed_formats().to_vec();
    meta.required_artifacts = artifacts();
    let receipt = wait(
        source
            .backup_to(checkpoint.clone(), meta, Instant::now() + WATCHDOG)
            .unwrap(),
    )
    .unwrap();
    let current = wait(
        source
            .inspect_namespace(
                "operator".into(),
                StateNamespaceId("business".into()),
                Instant::now() + WATCHDOG,
            )
            .unwrap(),
    )
    .unwrap();
    let review = AggregateMigrationRequest {
        scope: current.scope(),
        operation_id: "migration-actual".into(),
        operator_id: "operator".into(),
        expected_view: current.view_token().unwrap(),
        checkpoint_digest: receipt.snapshot_digest,
        checkpoint_manifest_digest: receipt.manifest_digest,
        package_digest: [83; 32],
        review_digest: [81; 32],
    };
    close(&source);
    (
        original,
        backup,
        OfflineAggregateMigrationRequest { checkpoint, review },
    )
}

#[test]
fn protected_fixed_recipe_survives_staged_engine_retirement_and_requires_separate_reviewed_resume()
{
    let (original, _backup, request) = prepared();
    let owner = codecs();
    let source = open_source(original.path(), owner.clone());
    let stage = wait(
        source
            .stage_aggregate_migration(request.clone(), Instant::now() + WATCHDOG)
            .unwrap(),
    )
    .unwrap();
    assert!(!stage.completed());
    let current = wait(
        source
            .inspect_namespace(
                "operator".into(),
                StateNamespaceId("business".into()),
                Instant::now() + WATCHDOG,
            )
            .unwrap(),
    )
    .unwrap();
    let resume = NamespaceResumeRequest {
        scope: current.scope(),
        operation_id: "unsafe-resume".into(),
        operator_id: "operator".into(),
        expected_view: current.view_token().unwrap(),
        review_digest: [71; 32],
    };
    assert_eq!(
        wait(
            source
                .resume_namespace(resume, Instant::now() + WATCHDOG)
                .unwrap()
        )
        .err(),
        Some(OfflineRecoveryError::Review(StoreError::Unavailable))
    );
    close(&source);
    let source = open_source(original.path(), owner);
    assert_eq!(
        wait(
            source
                .stage_aggregate_migration(request.clone(), Instant::now() + WATCHDOG)
                .unwrap()
        )
        .unwrap(),
        stage
    );
    let completed = wait(
        source
            .complete_aggregate_migration(request.clone(), Instant::now() + WATCHDOG)
            .unwrap(),
    )
    .unwrap();
    assert!(completed.completed());
    assert_eq!(completed.result_history().unwrap().epochs.schema, 2);
    let current = wait(
        source
            .inspect_namespace(
                "operator".into(),
                StateNamespaceId("business".into()),
                Instant::now() + WATCHDOG,
            )
            .unwrap(),
    )
    .unwrap();
    assert_eq!(
        current.namespace.status,
        crate::namespace::NamespaceStatus::Quiescing
    );
    assert_eq!(current.namespace.version.incarnation, 1);
    assert_eq!(current.history.epochs.recovery, 1);
    let resume = NamespaceResumeRequest {
        scope: current.scope(),
        operation_id: "approved-v2-resume".into(),
        operator_id: "operator".into(),
        expected_view: current.view_token().unwrap(),
        review_digest: [71; 32],
    };
    wait(
        source
            .resume_namespace(resume, Instant::now() + WATCHDOG)
            .unwrap(),
    )
    .unwrap();
    assert_eq!(
        wait(
            source
                .complete_aggregate_migration(request.clone(), Instant::now() + WATCHDOG)
                .unwrap()
        )
        .unwrap(),
        completed
    );
    close(&source);
    verify_actual_v2_value(original.path(), request.review.scope);
}
fn verify_actual_v2_value(path: &Path, old_scope: StateScope) {
    let validator = codecs();
    let owner = wait(
        ProtectedStoreOwner::start_validated_view(
            ProtectedStoreConfig::bounded_linux(path.into()),
            validator.scratch_bytes(),
            move |view| {
                validator.validate_view(view)?;
                Ok(())
            },
        )
        .unwrap(),
    )
    .unwrap();
    wait(
        owner
            .with_store(StoreIoKind::Read, 1024 * 1024, move |store| {
                let view = store.snapshot()?;
                let mut scope = old_scope.clone();
                scope.state_schema = migration::schema_ids()?.1.as_str().into();
                assert!(
                    StateSession::open(&view, old_scope, SessionLimits::default(), |_, _| Ok(()))
                        .is_err()
                );
                let mut session =
                    StateSession::open(&view, scope, SessionLimits::default(), |_, _| Ok(()))
                        .unwrap();
                let value = session
                    .get(&view, b"count", |_, _| Ok(()))
                    .unwrap()
                    .unwrap()
                    .value;
                assert_eq!(
                    value.bytes,
                    [b"AG\x02\0".as_slice(), &7u64.to_le_bytes()].concat()
                );
                assert_eq!(value.media_type, "application/vnd.lsf.aggregate-v2");
                Ok(())
            })
            .unwrap(),
    )
    .unwrap()
    .unwrap();
    finish(&owner);
}

#[test]
fn protected_fixed_recipe_final_revocation_preserves_staged_progress_and_old_schema() {
    let (original, _backup, request) = prepared();
    let source = open_source(original.path(), codecs());
    let stage = wait(
        source
            .stage_aggregate_migration(request.clone(), Instant::now() + WATCHDOG)
            .unwrap(),
    )
    .unwrap();
    close(&source);
    let gates = Rendezvous::new(1);
    let (notice, receiver) = mpsc::channel();
    let owner = Arc::new(MigrationCodecs {
        inner: Codecs {
            denied: AtomicBool::new(false),
            missing: AtomicBool::new(false),
            pause: Some((gates.clone(), notice)),
        },
    });
    let source = open_source(original.path(), owner.clone());
    let operation = source
        .complete_aggregate_migration(request, Instant::now() + WATCHDOG)
        .unwrap();
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    owner.inner.denied.store(true, Ordering::Release);
    gates.release(ticket).unwrap();
    assert_eq!(
        wait(operation).err(),
        Some(OfflineRecoveryError::Review(StoreError::Unavailable))
    );
    owner.inner.denied.store(false, Ordering::Release);
    let current = wait(
        source
            .inspect_namespace(
                "operator".into(),
                StateNamespaceId("business".into()),
                Instant::now() + WATCHDOG,
            )
            .unwrap(),
    )
    .unwrap();
    assert_eq!(current.namespace, stage.source_namespace().unwrap());
    assert_eq!(current.history.epochs.schema, 1);
    close(&source);
}

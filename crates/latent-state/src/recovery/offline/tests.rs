use super::*;
use crate::{
    embedded::{AtomicBatch, ExpectedRow, Family, RowMutation},
    namespace::{
        catalog::NamespaceCatalog,
        compatibility::{RetainedCount, RetainedInventory, SchemaId},
        namespace_record_key, NamespacePins, NamespaceQuota, NamespaceRecord, NamespaceTransition,
    },
    recovery::{
        restore::RestoreRequest,
        resume::{NamespaceResumeObservation, NamespaceResumeReceipt, NamespaceResumeRequest},
        snapshot::{NamespaceSnapshot, RequiredArtifact},
        RecoveryStatus,
    },
    session::{SessionLimits, StateMode, StateScope, StateSession},
    store_io::StoreIoKind,
};
use latent_core::{
    test_support::{
        block_on,
        coordination::{with_watchdog, PauseTicket, PollProbe, Rendezvous, Stage, WATCHDOG},
    },
    transaction_contract::Value,
    StateNamespaceId, TenantId,
};
use sha2::{Digest, Sha256};
use std::{
    fs,
    os::unix::fs::{MetadataExt, PermissionsExt},
    path::Path,
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc,
    },
};

const DEFINITION: &[u8] =
    include_bytes!("../../../../../contracts/state/application-aggregate-v1.schema.json");

struct Codecs {
    denied: AtomicBool,
    missing: AtomicBool,
    pause: Option<(Rendezvous, mpsc::Sender<PauseTicket>)>,
}
impl RecoveryCodecs for Codecs {
    fn runtime_digest(&self) -> [u8; 32] {
        [90; 32]
    }
    fn retained_bytes(&self) -> u64 {
        4096
    }
    fn scratch_bytes(&self) -> u64 {
        4 * 1024 * 1024
    }
    fn installed_formats(&self) -> &[RetainedFormat] {
        static FORMATS: std::sync::LazyLock<Vec<RetainedFormat>> =
            std::sync::LazyLock::new(|| vec![super::super::resume::retained_format()]);
        &FORMATS
    }
    fn validate_row(
        &self,
        source: &ReadView,
        key: &RowKey,
        value: &[u8],
    ) -> Result<(), StoreError> {
        if *key == super::super::guard_key() {
            RecoveryGuard::validate_row(key, value)
        } else if key.family == Family::Maintenance
            && key.key.starts_with(super::super::resume::RECEIPT_PREFIX)
        {
            NamespaceResumeReceipt::validate_row(key, value)
        } else if key.family == Family::Namespace {
            NamespaceCatalog::validate_row(key, value).map_err(|_| StoreError::Corrupt)
        } else {
            crate::session::validate_row(source, key, value)
        }
    }
    fn validate_view(&self, view: &ReadView) -> Result<SnapshotClosure, StoreError> {
        let mut inventory = RetainedInventory::default();
        for family in super::super::snapshot::FAMILIES {
            let mut resume = None;
            loop {
                let page = view.scan_after(family, b"", resume.as_deref(), 128, 4 * 1024 * 1024)?;
                for (key, value) in page.rows {
                    self.validate_row(view, &key, &value)?;
                    if key.family == Family::Maintenance
                        && key.key.starts_with(super::super::resume::RECEIPT_PREFIX)
                    {
                        inventory
                            .observe(
                                super::super::resume::retained_format(),
                                RetainedCount {
                                    rows: 1,
                                    bytes: (key.key.len() + value.len()) as u64,
                                    unresolved: 0,
                                },
                            )
                            .map_err(|_| StoreError::Capacity)?;
                    }
                }
                resume = page.resume;
                if resume.is_none() {
                    break;
                }
            }
        }
        Ok(SnapshotClosure {
            inventory,
            required_artifacts: vec![artifact()],
        })
    }
    fn verify_artifact(&self, input: &RequiredArtifact) -> Result<(), StoreError> {
        if self.missing.load(Ordering::Acquire) {
            return Err(StoreError::Unavailable);
        }
        if input != &artifact() {
            return Err(StoreError::Corrupt);
        }
        Ok(())
    }
    fn review_backup(
        &self,
        _: &ReadView,
        metadata: &SnapshotMetadata,
        _: &SnapshotFile,
    ) -> Result<(), StoreError> {
        if self.denied.load(Ordering::Acquire) || metadata.operator_id != "operator" {
            return Err(StoreError::Unavailable);
        }
        if let Some((gates, notice)) = &self.pause {
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
        Ok(())
    }
    fn authorize_inspection(
        &self,
        _: &ReadView,
        request: &OfflineRestoreRequest,
    ) -> Result<(), StoreError> {
        if self.denied.load(Ordering::Acquire) || request.review.operator_id != "operator" {
            return Err(StoreError::Unavailable);
        }
        Ok(())
    }
    fn review_restore(
        &self,
        view: &ReadView,
        _: &RestoreWindow,
        request: &OfflineRestoreRequest,
    ) -> Result<(), StoreError> {
        self.authorize_inspection(view, request)
    }
    fn review_reconciliation(
        &self,
        view: &ReadView,
        request: &RecoveryReviewRequest,
    ) -> Result<(), StoreError> {
        self.accept_reconciliation(request)?;
        self.validate_view(view)?;
        let actual = RecoveryGuard::capture(view)?.ok_or(StoreError::Corrupt)?;
        if actual.snapshot_digest() != request.expected_guard.snapshot_digest()
            || actual.window_digest() != request.expected_guard.window_digest()
        {
            return Err(StoreError::Conflict);
        }
        Ok(())
    }
    fn accept_reconciliation(&self, request: &RecoveryReviewRequest) -> Result<(), StoreError> {
        if self.denied.load(Ordering::Acquire)
            || request.operator_id != "operator"
            || request.review_digest != [70; 32]
        {
            return Err(StoreError::Unavailable);
        }
        Ok(())
    }
    fn review_namespace_resume(
        &self,
        view: &ReadView,
        request: &NamespaceResumeRequest,
        observed: NamespaceResumeObservation<'_>,
    ) -> Result<(), StoreError> {
        self.accept_namespace_resume(request)?;
        self.validate_view(view)?;
        assert_eq!(observed.namespace.tenant, request.scope.tenant);
        assert_eq!(observed.history.incarnation, request.scope.incarnation);
        if let Some((gates, notice)) = &self.pause {
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
        Ok(())
    }
    fn accept_namespace_resume(&self, request: &NamespaceResumeRequest) -> Result<(), StoreError> {
        if self.denied.load(Ordering::Acquire)
            || request.operator_id != "operator"
            || request.review_digest != [71; 32]
        {
            return Err(StoreError::Unavailable);
        }
        Ok(())
    }
    fn authorize_namespace_inspection(
        &self,
        _: &ReadView,
        operator_id: &str,
        namespace: &StateNamespaceId,
    ) -> Result<(), StoreError> {
        if self.denied.load(Ordering::Acquire)
            || operator_id != "operator"
            || namespace.0 != "business"
        {
            return Err(StoreError::Unavailable);
        }
        Ok(())
    }
}

fn artifact() -> RequiredArtifact {
    RequiredArtifact {
        identity: SchemaId::from_definition(DEFINITION)
            .unwrap()
            .as_str()
            .into(),
        digest: Sha256::digest(DEFINITION).into(),
    }
}
fn wait<T>(future: impl Future<Output = T>) -> T {
    block_on(with_watchdog(WATCHDOG, future))
}
fn root() -> tempfile::TempDir {
    let base =
        std::env::var_os("LATENT_STATE_TEST_ROOT").map_or_else(std::env::temp_dir, PathBuf::from);
    let root = tempfile::tempdir_in(base).unwrap();
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).unwrap();
    root
}
fn metadata() -> SnapshotMetadata {
    SnapshotMetadata {
        tenant: "tenant".into(),
        operation_id: "backup-original".into(),
        operator_id: "operator".into(),
        runtime_digest: [90; 32],
        decoder_formats: vec![super::super::resume::retained_format()],
        required_artifacts: vec![artifact()],
    }
}
fn codecs() -> Arc<Codecs> {
    Arc::new(Codecs {
        denied: AtomicBool::new(false),
        missing: AtomicBool::new(false),
        pause: None,
    })
}

fn populated_owner(root: &Path) -> ProtectedStoreOwner {
    populated_owner_with_status(root, true)
}
fn populated_owner_with_status(root: &Path, quiesce: bool) -> ProtectedStoreOwner {
    let mut config = ProtectedStoreConfig::bounded_linux(root.to_path_buf());
    config.create_if_missing = true;
    let owner = wait(ProtectedStoreOwner::start(config).unwrap()).unwrap();
    wait(
        owner
            .with_store(StoreIoKind::Write, 8 * 1024 * 1024, move |store| {
                let record = NamespaceRecord::create(
                    TenantId("tenant".into()),
                    StateNamespaceId("business".into()),
                    artifact().identity,
                    NamespaceQuota::default(),
                )
                .unwrap();
                let key = RowKey {
                    family: Family::Namespace,
                    key: namespace_record_key(&record.tenant, &record.id).unwrap(),
                };
                store.apply(AtomicBatch {
                    expectations: vec![],
                    mutations: vec![RowMutation {
                        key: key.clone(),
                        value: Some(record.encode().unwrap()),
                    }],
                })?;
                let view = store.snapshot()?;
                let scope = StateScope {
                    tenant: record.tenant,
                    namespace: record.id,
                    incarnation: 1,
                    state_schema: record.state_schema,
                    entity: None,
                    mode: StateMode::Command,
                };
                let mut session =
                    StateSession::open(&view, scope, SessionLimits::default(), |_, _| Ok(()))
                        .unwrap();
                session
                    .put(
                        &view,
                        b"count".to_vec(),
                        Value {
                            bytes: 7u64.to_le_bytes().to_vec(),
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
                store.apply(batch)?;
                drop(view);
                if !quiesce {
                    return Ok(());
                }
                let view = store.snapshot()?;
                let original = view.get(&key)?.unwrap();
                let record = NamespaceRecord::decode(&original).unwrap();
                let quiesced = record
                    .transition(record.version, &NamespaceTransition::Quiesce, 0)
                    .unwrap();
                drop(view);
                store.apply(AtomicBatch {
                    expectations: vec![ExpectedRow {
                        key: key.clone(),
                        value: Some(original),
                    }],
                    mutations: vec![RowMutation {
                        key,
                        value: Some(quiesced.encode().unwrap()),
                    }],
                })
            })
            .unwrap(),
    )
    .unwrap()
    .unwrap();
    owner
}
fn finish(owner: &ProtectedStoreOwner) {
    let report = wait(
        owner
            .drain_async(Instant::now() + WATCHDOG, std::future::pending())
            .unwrap(),
    );
    assert!(report.clean && report.snapshot.physically_retired());
    owner.reap_retired_threads().unwrap();
}
fn offline(root: &Path, owner: Arc<Codecs>) -> OfflineRecoverySource {
    wait(
        OfflineRecoverySource::start(
            ProtectedStoreConfig::bounded_linux(root.to_path_buf()),
            "tenant".into(),
            owner,
        )
        .unwrap(),
    )
    .unwrap()
}
fn close(source: &OfflineRecoverySource) {
    let report = wait(
        source
            .drain_async(Instant::now() + WATCHDOG, std::future::pending())
            .unwrap(),
    );
    assert!(report.clean && report.snapshot.physically_retired());
    source.reap_retired_threads().unwrap();
}
fn request(
    input: SnapshotFile,
    destination: &Path,
    snapshot_digest: [u8; 32],
) -> OfflineRestoreRequest {
    OfflineRestoreRequest {
        input,
        destination: ProtectedStoreConfig::bounded_linux(destination.to_path_buf()),
        review: RestoreRequest {
            operation_id: "restore-original".into(),
            operator_id: "operator".into(),
            snapshot_digest,
            runtime_digest: [90; 32],
            window_acknowledgement: [0; 32],
        },
    }
}

#[test]
fn protected_offline_snapshot_and_fresh_restore_close_real_engines_and_remain_paused() {
    let original = root();
    let backup = root();
    let destination = root();
    let owner = populated_owner(original.path());
    finish(&owner);
    let source = offline(original.path(), codecs());
    let path = SnapshotFile {
        root: backup.path().into(),
        file_name: "private-snapshot".into(),
    };
    let snapshot = wait(
        source
            .backup_to(path.clone(), metadata(), Instant::now() + WATCHDOG)
            .unwrap(),
    )
    .unwrap();
    assert_eq!(
        fs::metadata(backup.path().join("private-snapshot"))
            .unwrap()
            .mode()
            & 0o777,
        0o600
    );
    let mut proposed = request(path, destination.path(), snapshot.snapshot_digest);
    let inspected = wait(
        source
            .inspect_restore(proposed.clone(), Instant::now() + WATCHDOG)
            .unwrap(),
    )
    .unwrap();
    assert!(!destination.path().join("transaction-state.redb").exists());
    proposed.review.window_acknowledgement = inspected.window.digest().unwrap();
    let receipt = wait(
        source
            .restore_to(proposed, Instant::now() + WATCHDOG)
            .unwrap(),
    )
    .unwrap();
    assert_eq!(
        receipt.guard.status(),
        RecoveryStatus::ReconciliationRequired
    );
    assert_eq!(receipt.snapshot_digest, snapshot.snapshot_digest);
    let decoder = codecs();
    let restored = wait(
        ProtectedStoreOwner::start_validated_view(
            ProtectedStoreConfig::bounded_linux(destination.path().into()),
            decoder.scratch_bytes(),
            move |view| {
                decoder.validate_view(view)?;
                Ok(())
            },
        )
        .unwrap(),
    )
    .unwrap();
    let captured: NamespaceSnapshot = wait(
        restored
            .with_store(StoreIoKind::Read, 1024 * 1024, |store| {
                let view = store.snapshot()?;
                assert_eq!(
                    super::super::require_ready(&view),
                    Err(StoreError::Unavailable)
                );
                Ok(super::super::snapshot::capture_namespaces(&view, "tenant")?.remove(0))
            })
            .unwrap(),
    )
    .unwrap()
    .unwrap();
    assert_eq!(captured.record, snapshot.manifest.namespaces[0].record);
    assert_eq!(captured.decode().unwrap().1.epochs.recovery, 2);
    finish(&restored);
    close(&source);
}

#[test]
fn protected_source_requires_actual_owner_retirement_and_refuses_active_or_missing_roots() {
    let original = root();
    let owner = populated_owner(original.path());
    let mut startup = Box::pin(
        OfflineRecoverySource::start(
            ProtectedStoreConfig::bounded_linux(original.path().into()),
            "tenant".into(),
            codecs(),
        )
        .unwrap(),
    );
    assert_eq!(
        wait(startup.as_mut()).err(),
        Some(OfflineRecoveryError::Protected(ProtectedStoreError::Store(
            StoreError::Unavailable
        )))
    );
    let report = wait(
        startup
            .drain_async(Instant::now() + WATCHDOG, std::future::pending())
            .unwrap(),
    );
    assert!(!report.clean && report.snapshot.physically_retired());
    finish(&owner);
    let source = offline(original.path(), codecs());
    close(&source);
    let active = root();
    let owner = populated_owner_with_status(active.path(), false);
    finish(&owner);
    let mut startup = Box::pin(
        OfflineRecoverySource::start(
            ProtectedStoreConfig::bounded_linux(active.path().into()),
            "tenant".into(),
            codecs(),
        )
        .unwrap(),
    );
    assert_eq!(
        wait(startup.as_mut()).err(),
        Some(OfflineRecoveryError::Protected(ProtectedStoreError::Store(
            StoreError::Conflict
        ),))
    );
    let report = wait(
        startup
            .drain_async(Instant::now() + WATCHDOG, std::future::pending())
            .unwrap(),
    );
    assert!(!report.clean && report.snapshot.physically_retired());
    let missing = root();
    let mut startup = Box::pin(
        OfflineRecoverySource::start(
            ProtectedStoreConfig::bounded_linux(missing.path().into()),
            "tenant".into(),
            codecs(),
        )
        .unwrap(),
    );
    assert_eq!(
        wait(startup.as_mut()).err(),
        Some(OfflineRecoveryError::Protected(
            ProtectedStoreError::UnsafeRoot
        ))
    );
    assert!(!missing.path().join("transaction-state.redb").exists());
    let report = wait(
        startup
            .drain_async(Instant::now() + WATCHDOG, std::future::pending())
            .unwrap(),
    );
    assert!(!report.clean && report.snapshot.physically_retired());
}

#[test]
fn protected_recovery_refuses_bad_input_missing_artifacts_revocation_and_existing_destination_without_source_poisoning(
) {
    let original = root();
    let backup = root();
    let destination = root();
    let owner = populated_owner(original.path());
    finish(&owner);
    let decoder = codecs();
    let source = offline(original.path(), decoder.clone());
    let path = SnapshotFile {
        root: backup.path().into(),
        file_name: "snapshot".into(),
    };
    let receipt = wait(
        source
            .backup_to(path.clone(), metadata(), Instant::now() + WATCHDOG)
            .unwrap(),
    )
    .unwrap();
    let mut proposed = request(path.clone(), destination.path(), receipt.snapshot_digest);
    let inspect = wait(
        source
            .inspect_restore(proposed.clone(), Instant::now() + WATCHDOG)
            .unwrap(),
    )
    .unwrap();
    proposed.review.window_acknowledgement = inspect.window.digest().unwrap();
    decoder.missing.store(true, Ordering::Release);
    assert_eq!(
        wait(
            source
                .restore_to(proposed.clone(), Instant::now() + WATCHDOG)
                .unwrap()
        )
        .err(),
        Some(OfflineRecoveryError::Input(StoreError::Unavailable))
    );
    assert!(!destination.path().join("transaction-state.redb").exists());
    decoder.missing.store(false, Ordering::Release);
    decoder.denied.store(true, Ordering::Release);
    assert_eq!(
        wait(
            source
                .restore_to(proposed.clone(), Instant::now() + WATCHDOG)
                .unwrap()
        )
        .err(),
        Some(OfflineRecoveryError::Review(StoreError::Unavailable))
    );
    decoder.denied.store(false, Ordering::Release);
    fs::write(
        destination.path().join("transaction-state.redb"),
        b"owned-failed-staging-data",
    )
    .unwrap();
    fs::set_permissions(
        destination.path().join("transaction-state.redb"),
        fs::Permissions::from_mode(0o600),
    )
    .unwrap();
    assert_eq!(
        wait(
            source
                .restore_to(proposed.clone(), Instant::now() + WATCHDOG)
                .unwrap()
        )
        .err(),
        Some(OfflineRecoveryError::UnsafeDestination)
    );
    assert_eq!(
        fs::read(destination.path().join("transaction-state.redb")).unwrap(),
        b"owned-failed-staging-data"
    );
    let mut invalid = proposed;
    invalid.review.snapshot_digest = [8; 32];
    assert_eq!(
        wait(
            source
                .inspect_restore(invalid, Instant::now() + WATCHDOG)
                .unwrap()
        )
        .err(),
        Some(OfflineRecoveryError::Input(StoreError::Corrupt))
    );
    let second = SnapshotFile {
        root: backup.path().into(),
        file_name: "source-still-usable".into(),
    };
    assert_eq!(
        wait(
            source
                .backup_to(second, metadata(), Instant::now() + WATCHDOG)
                .unwrap()
        )
        .unwrap()
        .snapshot_digest,
        receipt.snapshot_digest
    );
    close(&source);
}

#[test]
fn lost_backup_waiter_keeps_actual_worker_bytes_and_exclusive_root_until_physical_retirement() {
    let original = root();
    let output = root();
    let owner = populated_owner(original.path());
    finish(&owner);
    let gates = Rendezvous::new(1);
    let (notice, receiver) = mpsc::channel();
    let decoder = Arc::new(Codecs {
        denied: AtomicBool::new(false),
        missing: AtomicBool::new(false),
        pause: Some((gates.clone(), notice)),
    });
    let source = offline(original.path(), decoder);
    let operation = source
        .backup_to(
            SnapshotFile {
                root: output.path().into(),
                file_name: "uncertain-private-backup".into(),
            },
            metadata(),
            Instant::now() + WATCHDOG,
        )
        .unwrap();
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    drop(operation);
    source.close();
    let snapshot = source.snapshot().unwrap();
    assert_eq!(snapshot.active_reads, 1);
    assert!(snapshot.retained_bytes >= OPERATION_SCRATCH_BYTES);
    assert!(matches!(
        source.backup_to(
            SnapshotFile {
                root: output.path().into(),
                file_name: "refused-second".into(),
            },
            metadata(),
            Instant::now() + WATCHDOG
        ),
        Err(OfflineRecoveryError::Busy)
    ));
    let drain = wait(
        source
            .drain_async(Instant::now(), std::future::pending())
            .unwrap(),
    );
    assert!(!drain.clean && !drain.snapshot.physically_retired());
    let mut opening = Box::pin(
        OfflineRecoverySource::start(
            ProtectedStoreConfig::bounded_linux(original.path().into()),
            "tenant".into(),
            codecs(),
        )
        .unwrap(),
    );
    assert_eq!(
        wait(opening.as_mut()).err(),
        Some(OfflineRecoveryError::Protected(ProtectedStoreError::Store(
            StoreError::Unavailable
        ),))
    );
    let failed = wait(
        opening
            .drain_async(Instant::now() + WATCHDOG, std::future::pending())
            .unwrap(),
    );
    assert!(failed.snapshot.physically_retired());
    gates.release(ticket).unwrap();
    let retired = wait(
        source
            .drain_async(Instant::now() + WATCHDOG, std::future::pending())
            .unwrap(),
    );
    assert!(!retired.clean && retired.snapshot.physically_retired());
    assert_eq!(retired.snapshot.retained_bytes, 0);
    source.reap_retired_threads().unwrap();
    let reopened = offline(original.path(), codecs());
    close(&reopened);
}

fn restored_for_review() -> (tempfile::TempDir, RecoveryGuard, Vec<u8>) {
    let original = root();
    let backup = root();
    let destination = root();
    let owner = populated_owner(original.path());
    finish(&owner);
    let source = offline(original.path(), codecs());
    let path = SnapshotFile {
        root: backup.path().into(),
        file_name: "review-checkpoint".into(),
    };
    let snapshot = wait(
        source
            .backup_to(path.clone(), metadata(), Instant::now() + WATCHDOG)
            .unwrap(),
    )
    .unwrap();
    let (namespace, history) = snapshot.manifest.namespaces[0].decode().unwrap();
    let scope = StateScope {
        tenant: namespace.tenant,
        namespace: namespace.id,
        incarnation: namespace.version.incarnation,
        state_schema: namespace.state_schema,
        entity: None,
        mode: StateMode::Command,
    };
    let old_token = crate::session::version::ViewIdentity {
        namespace: namespace.version,
        epochs: history.epochs,
    }
    .token(&scope)
    .unwrap();
    let mut proposed = request(path, destination.path(), snapshot.snapshot_digest);
    let inspection = wait(
        source
            .inspect_restore(proposed.clone(), Instant::now() + WATCHDOG)
            .unwrap(),
    )
    .unwrap();
    proposed.review.window_acknowledgement = inspection.window.digest().unwrap();
    let receipt = wait(
        source
            .restore_to(proposed, Instant::now() + WATCHDOG)
            .unwrap(),
    )
    .unwrap();
    close(&source);
    (destination, receipt.guard, old_token)
}

fn review_source(path: &Path, decoder: Arc<Codecs>) -> OfflineRecoverySource {
    wait(
        OfflineRecoverySource::start_review(
            ProtectedStoreConfig::bounded_linux(path.to_path_buf()),
            "tenant".into(),
            decoder,
        )
        .unwrap(),
    )
    .unwrap()
}

#[test]
fn protected_review_requires_explicit_reconciliation_and_namespace_resume_and_replays_original_receipt(
) {
    let (destination, guard, old_token) = restored_for_review();
    let decoder = codecs();
    let source = review_source(destination.path(), decoder.clone());
    let observed = wait(
        source
            .inspect_namespace(
                "operator".into(),
                StateNamespaceId("business".into()),
                Instant::now() + WATCHDOG,
            )
            .unwrap(),
    )
    .unwrap();
    assert_eq!(observed.history.epochs.recovery, 2);
    let request = NamespaceResumeRequest {
        scope: observed.scope(),
        operation_id: "resume-actual".into(),
        operator_id: "operator".into(),
        expected_view: observed.view_token().unwrap(),
        review_digest: [71; 32],
    };
    assert_eq!(
        wait(
            source
                .resume_namespace(request.clone(), Instant::now() + WATCHDOG)
                .unwrap()
        )
        .err(),
        Some(OfflineRecoveryError::Review(StoreError::Unavailable))
    );
    let mut review = RecoveryReviewRequest {
        operator_id: "operator".into(),
        expected_guard: guard,
        review_digest: [69; 32],
    };
    assert_eq!(
        wait(
            source
                .review_reconciliation(review.clone(), Instant::now() + WATCHDOG)
                .unwrap()
        )
        .err(),
        Some(OfflineRecoveryError::Review(StoreError::Unavailable))
    );
    review.review_digest = [70; 32];
    let accepted = wait(
        source
            .review_reconciliation(review.clone(), Instant::now() + WATCHDOG)
            .unwrap(),
    )
    .unwrap();
    assert_eq!(accepted.status(), RecoveryStatus::ReviewAccepted);
    let observed = wait(
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
        observed.namespace.status,
        crate::namespace::NamespaceStatus::Quiescing
    );
    assert_eq!(
        observed.history.status,
        crate::namespace::history::HistoryStatus::ReconciliationRequired
    );
    let receipt = wait(
        source
            .resume_namespace(request.clone(), Instant::now() + WATCHDOG)
            .unwrap(),
    )
    .unwrap();
    let original_receipt = receipt.encode().unwrap();
    close(&source);
    assert_normal_resumed_namespace(destination.path(), &receipt, request.clone(), old_token);
    assert_recovery_replay(
        destination.path(),
        &decoder,
        request,
        &original_receipt,
        review,
        &accepted,
    );
}

fn assert_normal_resumed_namespace(
    path: &Path,
    receipt: &NamespaceResumeReceipt,
    request: NamespaceResumeRequest,
    old_token: Vec<u8>,
) {
    // Ordinary data access occurs only after physical administrative retirement.
    let validator = codecs();
    let owner = wait(
        ProtectedStoreOwner::start_validated_view(
            ProtectedStoreConfig::bounded_linux(path.into()),
            validator.scratch_bytes(),
            move |view| {
                super::super::require_ready(view)?;
                validator.validate_view(view)?;
                Ok(())
            },
        )
        .unwrap(),
    )
    .unwrap();
    let current_token = wait(
        owner
            .with_store(StoreIoKind::Read, 1024 * 1024, move |store| {
                let view = store.snapshot()?;
                let session = StateSession::open(
                    &view,
                    request.scope.clone(),
                    SessionLimits::default(),
                    |_, _| Ok(()),
                )
                .unwrap();
                assert_eq!(
                    session
                        .view_identity()
                        .require_minimum(&request.scope, &old_token),
                    Err(crate::session::StateError::RecoveryRequired)
                );
                Ok(session.view_token().unwrap())
            })
            .unwrap(),
    )
    .unwrap()
    .unwrap();
    assert_eq!(current_token, receipt.view_token().unwrap());
    finish(&owner);
}

fn assert_recovery_replay(
    path: &Path,
    decoder: &Arc<Codecs>,
    request: NamespaceResumeRequest,
    original_receipt: &[u8],
    review: RecoveryReviewRequest,
    accepted: &RecoveryGuard,
) {
    let source = review_source(path, decoder.clone());
    let mut replay = request;
    // The observation before resume is the exact input to the original decision.
    assert_eq!(
        wait(
            source
                .resume_namespace(replay.clone(), Instant::now() + WATCHDOG)
                .unwrap()
        )
        .unwrap()
        .encode()
        .unwrap(),
        original_receipt
    );
    assert_eq!(
        wait(
            source
                .review_reconciliation(review, Instant::now() + WATCHDOG)
                .unwrap()
        )
        .unwrap(),
        *accepted
    );
    decoder.denied.store(true, Ordering::Release);
    assert_eq!(
        wait(
            source
                .resume_namespace(replay.clone(), Instant::now() + WATCHDOG)
                .unwrap()
        )
        .err(),
        Some(OfflineRecoveryError::Review(StoreError::Unavailable))
    );
    decoder.denied.store(false, Ordering::Release);
    replay.review_digest = [72; 32];
    assert_eq!(
        wait(
            source
                .resume_namespace(replay, Instant::now() + WATCHDOG)
                .unwrap()
        )
        .err(),
        Some(OfflineRecoveryError::Review(StoreError::Conflict))
    );
    close(&source);
}

#[test]
fn protected_namespace_resume_rechecks_revocation_after_review_at_real_writer_fence() {
    let original = root();
    let owner = populated_owner(original.path());
    finish(&owner);
    let gates = Rendezvous::new(1);
    let (notice, receiver) = mpsc::channel();
    let decoder = Arc::new(Codecs {
        denied: AtomicBool::new(false),
        missing: AtomicBool::new(false),
        pause: Some((gates.clone(), notice)),
    });
    let source = review_source(original.path(), decoder.clone());
    let observed = wait(
        source
            .inspect_namespace(
                "operator".into(),
                StateNamespaceId("business".into()),
                Instant::now() + WATCHDOG,
            )
            .unwrap(),
    )
    .unwrap();
    let request = NamespaceResumeRequest {
        scope: observed.scope(),
        operation_id: "resume-revoked".into(),
        operator_id: "operator".into(),
        expected_view: observed.view_token().unwrap(),
        review_digest: [71; 32],
    };
    let operation = source
        .resume_namespace(request, Instant::now() + WATCHDOG)
        .unwrap();
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    assert_eq!(source.snapshot().unwrap().active_writes, 1);
    decoder.denied.store(true, Ordering::Release);
    gates.release(ticket).unwrap();
    assert_eq!(
        wait(operation).err(),
        Some(OfflineRecoveryError::Review(StoreError::Unavailable))
    );
    decoder.denied.store(false, Ordering::Release);
    let actual = wait(
        source
            .inspect_namespace(
                "operator".into(),
                StateNamespaceId("business".into()),
                Instant::now() + WATCHDOG,
            )
            .unwrap(),
    )
    .unwrap();
    assert_eq!(actual.namespace, observed.namespace);
    assert_eq!(actual.view_token().unwrap(), observed.view_token().unwrap());
    close(&source);
}

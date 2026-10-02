use super::*;

struct BoundedCodecs {
    inner: Arc<Codecs>,
    maximum_bytes: u64,
}
impl RecoveryCodecs for BoundedCodecs {
    fn runtime_digest(&self) -> [u8; 32] {
        self.inner.runtime_digest()
    }
    fn retained_bytes(&self) -> u64 {
        self.inner.retained_bytes()
    }
    fn scratch_bytes(&self) -> u64 {
        self.inner.scratch_bytes()
    }
    fn snapshot_file_bytes(&self) -> u64 {
        self.maximum_bytes
    }
    fn installed_formats(&self) -> &[RetainedFormat] {
        self.inner.installed_formats()
    }
    fn validate_row(&self, view: &ReadView, key: &RowKey, value: &[u8]) -> Result<(), StoreError> {
        self.inner.validate_row(view, key, value)
    }
    fn validate_view(&self, view: &ReadView) -> Result<SnapshotClosure, StoreError> {
        self.inner.validate_view(view)
    }
    fn verify_artifact(&self, artifact: &RequiredArtifact) -> Result<(), StoreError> {
        self.inner.verify_artifact(artifact)
    }
    fn review_backup(
        &self,
        view: &ReadView,
        metadata: &SnapshotMetadata,
        output: &SnapshotFile,
    ) -> Result<(), StoreError> {
        self.inner.review_backup(view, metadata, output)
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
        window: &RestoreWindow,
        request: &OfflineRestoreRequest,
    ) -> Result<(), StoreError> {
        self.inner.review_restore(view, window, request)
    }
}

fn bounded(root: &Path, maximum_bytes: u64) -> OfflineRecoverySource {
    wait(
        OfflineRecoverySource::start(
            ProtectedStoreConfig::bounded_linux(root.into()),
            "tenant".into(),
            Arc::new(BoundedCodecs {
                inner: codecs(),
                maximum_bytes,
            }),
        )
        .unwrap(),
    )
    .unwrap()
}

#[test]
fn stricter_installed_export_cap_refuses_before_oversize_write_and_preserves_source() {
    let original = root();
    let backup = root();
    let owner = populated_owner(original.path());
    finish(&owner);
    let source = bounded(original.path(), 8);
    let path = SnapshotFile {
        root: backup.path().into(),
        file_name: "bounded-snapshot".into(),
    };
    let result = wait(
        source
            .backup_to(path, metadata(), Instant::now() + WATCHDOG)
            .unwrap(),
    );
    assert!(result.is_err());
    assert_eq!(
        fs::metadata(backup.path().join("bounded-snapshot"))
            .unwrap()
            .len(),
        0
    );
    close(&source);
    let reopened = offline(original.path(), codecs());
    let full = SnapshotFile {
        root: backup.path().into(),
        file_name: "original-full-snapshot".into(),
    };
    let receipt = wait(
        reopened
            .backup_to(full, metadata(), Instant::now() + WATCHDOG)
            .unwrap(),
    )
    .unwrap();
    assert!(receipt.file_bytes > 8);
    close(&reopened);
}

#[test]
fn stricter_installed_input_cap_rejects_existing_snapshot_and_cannot_expand_native_profile() {
    let original = root();
    let backup = root();
    let destination = root();
    let owner = populated_owner(original.path());
    finish(&owner);
    let source = offline(original.path(), codecs());
    let path = SnapshotFile {
        root: backup.path().into(),
        file_name: "original-snapshot".into(),
    };
    let receipt = wait(
        source
            .backup_to(path.clone(), metadata(), Instant::now() + WATCHDOG)
            .unwrap(),
    )
    .unwrap();
    close(&source);
    for maximum_bytes in [0, super::super::super::snapshot::SNAPSHOT_FILE_BYTES + 1] {
        let result = OfflineRecoverySource::start(
            ProtectedStoreConfig::bounded_linux(original.path().into()),
            "tenant".into(),
            Arc::new(BoundedCodecs {
                inner: codecs(),
                maximum_bytes,
            }),
        );
        assert!(matches!(
            result,
            Err(OfflineRecoveryError::InvalidConfiguration)
        ));
    }
    let bounded = bounded(original.path(), receipt.file_bytes - 1);
    let request = request(path, destination.path(), receipt.snapshot_digest);
    assert!(matches!(
        wait(
            bounded
                .inspect_restore(request, Instant::now() + WATCHDOG)
                .unwrap()
        ),
        Err(OfflineRecoveryError::UnsafeDestination)
    ));
    assert!(!destination.path().join("STATE.redb").exists());
    close(&bounded);
}

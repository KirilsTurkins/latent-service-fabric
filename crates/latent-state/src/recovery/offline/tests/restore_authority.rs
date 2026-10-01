//! Actual protected restore boundaries; earlier review never becomes authority.
use super::*;

// Both fixtures keep the original installed decoders, artifact checks and
// operator review. The unfenced fixture deliberately inherits the DENY default.
macro_rules! original_codecs {
    () => {
        fn runtime_digest(&self) -> [u8; 32] {
            self.inner.runtime_digest()
        }
        fn retained_bytes(&self) -> u64 {
            self.inner.retained_bytes()
        }
        fn scratch_bytes(&self) -> u64 {
            self.inner.scratch_bytes()
        }
        fn installed_formats(&self) -> &[RetainedFormat] {
            self.inner.installed_formats()
        }
        fn validate_row(
            &self,
            view: &ReadView,
            key: &RowKey,
            bytes: &[u8],
        ) -> Result<(), StoreError> {
            self.inner.validate_row(view, key, bytes)
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
            file: &SnapshotFile,
        ) -> Result<(), StoreError> {
            self.inner.review_backup(view, metadata, file)
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
            self.review(view, window, request)
        }
    };
}

struct UnfencedCodecs {
    inner: Arc<Codecs>,
}
impl UnfencedCodecs {
    fn review(
        &self,
        view: &ReadView,
        window: &RestoreWindow,
        request: &OfflineRestoreRequest,
    ) -> Result<(), StoreError> {
        self.inner.review_restore(view, window, request)
    }
}
impl RecoveryCodecs for UnfencedCodecs {
    original_codecs!();
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum PauseAt {
    Review,
    Publication,
}
struct FencedCodecs {
    inner: Arc<Codecs>,
    stage: PauseAt,
    blocked: AtomicBool,
    gates: Rendezvous,
    notice: mpsc::Sender<PauseTicket>,
}
impl FencedCodecs {
    fn pause(&self, stage: PauseAt) {
        if self.stage != stage || self.blocked.swap(true, Ordering::AcqRel) {
            return;
        }
        let (registration, mut tracked) = self.gates.track(()).unwrap();
        tracked.commit(Stage::Entered).unwrap();
        wait(async {
            let mut pause = Box::pin(tracked.pause());
            PollProbe::default().pending(pause.as_mut());
            self.notice
                .send(self.gates.blocked(registration, Stage::Entered).unwrap())
                .unwrap();
            pause.await;
        });
    }
    fn review(
        &self,
        view: &ReadView,
        window: &RestoreWindow,
        request: &OfflineRestoreRequest,
    ) -> Result<(), StoreError> {
        self.inner.review_restore(view, window, request)?;
        self.pause(PauseAt::Review);
        Ok(())
    }
}
impl RecoveryCodecs for FencedCodecs {
    original_codecs!();
    fn accept_restore(
        &self,
        request: &OfflineRestoreRequest,
        fence: RestoreFence,
    ) -> Result<(), StoreError> {
        if fence == RestoreFence::Publication {
            self.pause(PauseAt::Publication);
        }
        self.inner.accept_restore(request, fence)
    }
}

struct Prepared {
    original: tempfile::TempDir,
    backup: tempfile::TempDir,
    destination: tempfile::TempDir,
    source: OfflineRecoverySource,
    request: OfflineRestoreRequest,
    snapshot_digest: [u8; 32],
}
impl Prepared {
    fn new(codecs: Arc<dyn RecoveryCodecs>) -> Self {
        let original = root();
        let backup = root();
        let destination = root();
        let owner = populated_owner(original.path());
        finish(&owner);
        let source = wait(
            OfflineRecoverySource::start(
                ProtectedStoreConfig::bounded_linux(original.path().into()),
                "tenant".into(),
                codecs,
            )
            .unwrap(),
        )
        .unwrap();
        let path = SnapshotFile {
            root: backup.path().into(),
            file_name: "original-snapshot".into(),
        };
        let snapshot_digest = wait(
            source
                .backup_to(path.clone(), metadata(), Instant::now() + WATCHDOG)
                .unwrap(),
        )
        .unwrap()
        .snapshot_digest;
        let mut request = request(path, destination.path(), snapshot_digest);
        let observed = wait(
            source
                .inspect_restore(request.clone(), Instant::now() + WATCHDOG)
                .unwrap(),
        )
        .unwrap();
        request.review.window_acknowledgement = observed.window.digest().unwrap();
        Self {
            original,
            backup,
            destination,
            source,
            request,
            snapshot_digest,
        }
    }
    fn assert_source_unchanged_and_close(self) {
        let observed = wait(
            self.source
                .backup_to(
                    SnapshotFile {
                        root: self.backup.path().into(),
                        file_name: "after-refusal".into(),
                    },
                    metadata(),
                    Instant::now() + WATCHDOG,
                )
                .unwrap(),
        )
        .unwrap();
        assert_eq!(observed.snapshot_digest, self.snapshot_digest);
        assert!(self
            .original
            .path()
            .join("transaction-state.redb")
            .is_file());
        close(&self.source);
        let snapshot = self.source.snapshot().unwrap();
        assert!(snapshot.physically_retired());
        assert_eq!(snapshot.accepted, 0);
        assert_eq!(snapshot.retained_bytes, 0);
    }
}

#[test]
fn protected_restore_requires_installed_final_authority_before_creating_destination() {
    let prepared = Prepared::new(Arc::new(UnfencedCodecs { inner: codecs() }));
    let result = wait(
        prepared
            .source
            .restore_to(prepared.request.clone(), Instant::now() + WATCHDOG)
            .unwrap(),
    );
    assert_eq!(
        result.err(),
        Some(OfflineRecoveryError::Review(StoreError::Unavailable))
    );
    assert!(!prepared
        .destination
        .path()
        .join("transaction-state.redb")
        .exists());
    prepared.assert_source_unchanged_and_close();
}

fn revoke_at(stage: PauseAt) {
    let gates = Rendezvous::new(1);
    let (notice, receiver) = mpsc::channel();
    let decoder = Arc::new(FencedCodecs {
        inner: codecs(),
        stage,
        blocked: AtomicBool::new(false),
        gates: gates.clone(),
        notice,
    });
    let prepared = Prepared::new(decoder.clone());
    let operation = prepared
        .source
        .restore_to(prepared.request.clone(), Instant::now() + WATCHDOG)
        .unwrap();
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    assert_eq!(prepared.source.snapshot().unwrap().active_reads, 1);
    decoder.inner.denied.store(true, Ordering::Release);
    gates.release(ticket).unwrap();
    let expected = if stage == PauseAt::Review {
        OfflineRecoveryError::Review(StoreError::Unavailable)
    } else {
        OfflineRecoveryError::Target(StoreError::CommitUncertain)
    };
    assert_eq!(wait(operation).err(), Some(expected));
    let path = prepared.destination.path().join("transaction-state.redb");
    if stage == PauseAt::Review {
        assert!(!path.exists());
    } else {
        assert!(path.is_file());
        let owner = wait(
            ProtectedStoreOwner::start(ProtectedStoreConfig::bounded_linux(
                prepared.destination.path().into(),
            ))
            .unwrap(),
        )
        .unwrap();
        let guard = wait(
            owner
                .with_store(StoreIoKind::Read, 1024 * 1024, |store| {
                    RecoveryGuard::capture(&store.snapshot()?)
                })
                .unwrap(),
        )
        .unwrap()
        .unwrap()
        .unwrap();
        assert_eq!(guard.status(), RecoveryStatus::ReconciliationRequired);
        assert_eq!(guard.snapshot_digest(), prepared.snapshot_digest);
        finish(&owner);
    }
    decoder.inner.denied.store(false, Ordering::Release);
    prepared.assert_source_unchanged_and_close();
}

#[test]
fn protected_restore_revocation_after_review_denies_writes_without_changing_source() {
    revoke_at(PauseAt::Review);
}

#[test]
fn protected_restore_final_publication_revocation_preserves_paused_history_without_success_receipt()
{
    revoke_at(PauseAt::Publication);
}

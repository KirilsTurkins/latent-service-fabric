//! Storage/ownership proof with an injected real mutex fence, not a claim of
//! cryptographic policy verification (the Wasmtime integration uses that policy).
use super::*;
use crate::{ArtifactPreparationReadWait, OwnedArtifactPreparationSource, ReleaseUseEligibility};
use std::sync::{mpsc, Mutex, Weak};
use std::time::Duration;

#[derive(Default)]
struct Gate {
    armed: AtomicBool,
    after_read: AtomicBool,
    initial_hashes: AtomicU64,
    repository: Mutex<Option<Weak<DirectoryArtifactRepository>>>,
    fence: Mutex<()>,
    failure: Mutex<Option<PlatformError>>,
}
impl Gate {
    fn check(&self) -> Result<(), PlatformError> {
        if !self.armed.load(Ordering::SeqCst) {
            return Ok(());
        }
        let repo = self
            .repository
            .lock()
            .unwrap()
            .as_ref()
            .unwrap()
            .upgrade()
            .unwrap();
        let after = repo.verification_snapshot().component_verification_attempts
            > self.initial_hashes.load(Ordering::SeqCst);
        if after != self.after_read.load(Ordering::SeqCst) {
            return Ok(());
        }
        let _guard = self
            .fence
            .try_lock()
            .map_err(|_| self.failure.lock().unwrap().clone().unwrap_or_else(busy))?;
        Ok(())
    }
}
fn busy() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::Unavailable,
        message: "injected authority fence".into(),
        retryable: true,
        details: vec![latent_core::ErrorDetail {
            kind: "admission.currentness".into(),
            fields: [("reason".into(), "admission-authority-busy".into())].into(),
        }],
    }
}
struct GatedHost {
    authority: Arc<Authority>,
    gate: Arc<Gate>,
}
impl GatedHost {
    fn wrap(&self, mut checked: VerifiedAdmission) -> VerifiedAdmission {
        checked.grant = Arc::new(GatedGrant {
            inner: checked.grant,
            gate: self.gate.clone(),
        });
        checked
    }
}
impl AdmissionAuthority for GatedHost {
    fn verify(
        &self,
        tenant: &TenantId,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        Ok(self.wrap(Host(self.authority.clone()).verify(tenant, upload)?))
    }
    fn recover(
        &self,
        binding: &AdmissionBinding,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        Ok(self.wrap(Host(self.authority.clone()).recover(binding, upload)?))
    }
}
struct GatedGrant {
    inner: Arc<dyn AdmissionGrant>,
    gate: Arc<Gate>,
}
impl AdmissionGrant for GatedGrant {
    fn as_any(&self) -> &dyn std::any::Any {
        self.inner.as_any()
    }
    fn binding(&self) -> &AdmissionBinding {
        self.inner.binding()
    }
    fn retained_bytes(&self) -> usize {
        self.inner.retained_bytes() + 256
    }
    fn check_current(&self) -> Result<(), PlatformError> {
        self.gate.check()?;
        self.inner.check_current()
    }
    fn with_current(
        &self,
        action: &mut dyn FnMut(&dyn AdmissionRecheck) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        self.gate.check()?;
        self.inner.with_current(action)
    }
}

struct Fixture {
    repository: Arc<DirectoryArtifactRepository>,
    source: OwnedArtifactPreparationSource,
    original: ReleaseUseEligibility,
    authority: Arc<Authority>,
    gate: Arc<Gate>,
    _root: TempRoot,
}
impl Fixture {
    fn new() -> Self {
        let root = TempRoot::new();
        let authority = Authority::new();
        let gate = Arc::new(Gate::default());
        let repository = Arc::new(
            DirectoryArtifactRepository::open_enforced(
                root.path(),
                Default::default(),
                Default::default(),
                Arc::new(GatedHost {
                    authority: authority.clone(),
                    gate: gate.clone(),
                }),
            )
            .unwrap(),
        );
        admit(&repository).unwrap();
        let source = repository.clone().owned_preparation_source().unwrap();
        let original = source
            .execution_eligibility_selected(&artifact().descriptor.release_digest, None)
            .unwrap()
            .unwrap();
        Self {
            repository,
            source,
            original,
            authority,
            gate,
            _root: root,
        }
    }
    fn limits(&self) -> crate::ArtifactPreparationReadLimits {
        self.repository.repository_read_limits()
    }
    fn fetch(
        &self,
        wait: &dyn ArtifactPreparationReadWait,
    ) -> Result<crate::CapsuleArtifact, PlatformError> {
        self.source.fetch_blocking_selected_with_wait(
            self.original.release(),
            Some(self.original.publication()),
            self.limits(),
            &self.original,
            wait,
        )
    }
    fn hold(&self, after: bool) -> Fence {
        self.gate.initial_hashes.store(
            self.repository
                .verification_snapshot()
                .component_verification_attempts,
            Ordering::SeqCst,
        );
        *self.gate.repository.lock().unwrap() = Some(Arc::downgrade(&self.repository));
        self.gate.after_read.store(after, Ordering::SeqCst);
        let gate = self.gate.clone();
        let (entered_send, entered) = mpsc::sync_channel(1);
        let (release, released) = mpsc::sync_channel(1);
        let worker = std::thread::spawn(move || {
            let _guard = gate.fence.lock().unwrap();
            entered_send.send(()).unwrap();
            released.recv_timeout(Duration::from_secs(5)).unwrap();
        });
        entered.recv_timeout(Duration::from_secs(5)).unwrap();
        self.gate.armed.store(true, Ordering::SeqCst);
        Fence {
            release: Some(release),
            worker: Some(worker),
        }
    }
}
struct Fence {
    release: Option<mpsc::SyncSender<()>>,
    worker: Option<std::thread::JoinHandle<()>>,
}
impl Fence {
    fn release(mut self) {
        self.release.take().unwrap().send(()).unwrap();
        self.worker.take().unwrap().join().unwrap();
    }
}
impl Drop for Fence {
    fn drop(&mut self) {
        if let Some(release) = self.release.take() {
            let _ = release.send(());
        }
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}
struct YieldOnce {
    calls: AtomicU64,
    action: Mutex<Option<Box<dyn FnOnce() + Send>>>,
}
impl YieldOnce {
    fn new(action: impl FnOnce() + Send + 'static) -> Self {
        Self {
            calls: AtomicU64::new(0),
            action: Mutex::new(Some(Box::new(action))),
        }
    }
}
impl ArtifactPreparationReadWait for YieldOnce {
    fn wait_after_busy(&self) -> bool {
        self.calls.fetch_add(1, Ordering::SeqCst);
        let action = self.action.lock().unwrap().take();
        if let Some(action) = action {
            action();
            true
        } else {
            false
        }
    }
}

#[test]
fn sealed_worker_fetch_waits_at_pre_and_post_currentness_without_repeating_disk_work() {
    for after_read in [false, true] {
        let f = Fixture::new();
        let before = f.repository.verification_snapshot();
        let fence = f.hold(after_read);
        let repo = f.repository.clone();
        let wait = YieldOnce::new(move || {
            let held = repo.verification_snapshot();
            assert_eq!(held.full_fetch_attempts - before.full_fetch_attempts, 1);
            assert_eq!(
                held.component_verification_attempts - before.component_verification_attempts,
                u64::from(after_read)
            );
            fence.release();
        });
        assert_eq!(f.fetch(&wait).unwrap(), artifact());
        assert_eq!(wait.calls.load(Ordering::SeqCst), 1);
        let actual = f.repository.verification_snapshot();
        assert_eq!(actual.full_fetch_attempts - before.full_fetch_attempts, 1);
        assert_eq!(
            actual.component_verification_attempts - before.component_verification_attempts,
            1
        );
        assert_eq!(
            actual.component_bytes_hashed - before.component_bytes_hashed,
            artifact().component_bytes.len() as u64
        );
    }
}

#[test]
fn sealed_worker_fetch_cannot_upgrade_original_grant_during_post_read_wait() {
    let f = Fixture::new();
    let fence = f.hold(true);
    let repo = f.repository.clone();
    let authority = f.authority.clone();
    let reference = crate::PublicationRef {
        id: f.original.publication().clone(),
        scope: f.original.scope().clone(),
    };
    let wait = YieldOnce::new(move || {
        fence.release();
        authority.generation.fetch_add(1, Ordering::SeqCst);
        repo.reverify_publication(&reference).unwrap();
    });
    assert_eq!(
        f.fetch(&wait).unwrap_err().code,
        PlatformErrorCode::PermissionDenied
    );
    assert_eq!(wait.calls.load(Ordering::SeqCst), 1);
    assert!(f.original.check_current().is_err());
    assert!(f
        .source
        .execution_eligibility_selected(f.original.release(), Some(f.original.publication()))
        .unwrap()
        .unwrap()
        .check_current()
        .is_ok());
}

#[test]
fn sealed_worker_fetch_never_schedules_non_busy_or_malformed_errors() {
    let mut failures = vec![];
    let mut changed = busy();
    changed.code = PlatformErrorCode::StateConflict;
    failures.push(changed);
    let mut changed = busy();
    changed.retryable = false;
    failures.push(changed);
    let mut changed = busy();
    changed.details.clear();
    failures.push(changed);
    let mut changed = busy();
    changed.details[0].kind = "admission.limit".into();
    failures.push(changed);
    let mut changed = busy();
    changed.details.push(changed.details[0].clone());
    failures.push(changed);
    let mut changed = busy();
    changed.details[0]
        .fields
        .insert("extra".into(), "value".into());
    failures.push(changed);
    let mut changed = busy();
    changed.details[0]
        .fields
        .insert("reason".into(), "admission-clock-lease-uncovered".into());
    failures.push(changed);
    for error in failures {
        let f = Fixture::new();
        *f.gate.failure.lock().unwrap() = Some(error.clone());
        let fence = f.hold(false);
        let wait = YieldOnce::new(|| panic!("non-busy error cannot schedule"));
        assert_eq!(f.fetch(&wait).unwrap_err(), error);
        assert_eq!(wait.calls.load(Ordering::SeqCst), 0);
        fence.release();
    }
}

#[test]
fn scheduling_hook_cannot_supply_success_and_legacy_fetch_remains_immediate() {
    let f = Fixture::new();
    let fence = f.hold(false);
    let wait = YieldOnce::new(|| {}); // One schedule, deliberately no fence release.
    assert_eq!(f.fetch(&wait).unwrap_err(), busy());
    assert_eq!(wait.calls.load(Ordering::SeqCst), 2);
    let error = f
        .source
        .fetch_blocking_selected(
            f.original.release(),
            Some(f.original.publication()),
            f.limits(),
        )
        .unwrap_err();
    assert_eq!(error, busy());
    fence.release();
}

#[test]
fn sealed_worker_fetch_rejects_a_foreign_original_grant_before_wait_or_disk_read() {
    let f = Fixture::new();
    let other = Fixture::new();
    let before = f.repository.verification_snapshot();
    let wait = YieldOnce::new(|| panic!("foreign grant cannot schedule"));
    let error = f
        .source
        .fetch_blocking_selected_with_wait(
            f.original.release(),
            Some(f.original.publication()),
            f.limits(),
            &other.original,
            &wait,
        )
        .unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::CorruptArtifact);
    assert_eq!(wait.calls.load(Ordering::SeqCst), 0);
    assert_eq!(
        f.repository
            .verification_snapshot()
            .component_verification_attempts,
        before.component_verification_attempts
    );
}

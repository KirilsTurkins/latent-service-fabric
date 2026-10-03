//! Payload verification must not monopolize a finite policy-currentness fence.
use super::*;
use crate::local_repository::integrity::faults::{AfterMetadataScanGuard, AfterRenameGuard};
use std::sync::Mutex;

struct Lease {
    now: u64,
    ceiling: u64,
    revoked: bool,
    valid_until: u64,
    fail_renewal: bool,
    renewals: usize,
    renewal_attempts: usize,
    grant_checks: AtomicU64,
}
impl Lease {
    fn check(&self) -> Result<(), PlatformError> {
        self.grant_checks.fetch_add(1, Ordering::SeqCst);
        if self.revoked || self.now >= self.valid_until {
            Err(denied())
        } else if self.now >= self.ceiling {
            Err(PlatformError {
                code: PlatformErrorCode::Unavailable,
                message: "test-clock-lease-uncovered".into(),
                retryable: true,
                details: Vec::new(),
            })
        } else {
            Ok(())
        }
    }
}
struct FencedHost(Arc<Mutex<Lease>>);
struct FencedGrant {
    binding: AdmissionBinding,
    lease: Arc<Mutex<Lease>>,
}
struct Check<'a>(&'a Lease);
impl AdmissionRecheck for Check<'_> {
    fn check(&self) -> Result<(), PlatformError> {
        self.0.check()
    }
}
impl AdmissionGrant for FencedGrant {
    fn as_any(&self) -> &dyn std::any::Any {
        self
    }
    fn binding(&self) -> &AdmissionBinding {
        &self.binding
    }
    fn retained_bytes(&self) -> usize {
        1024
    }
    fn check_current(&self) -> Result<(), PlatformError> {
        self.lease
            .try_lock()
            .expect("policy fence available")
            .check()
    }
    fn with_current(
        &self,
        action: &mut dyn FnMut(&dyn AdmissionRecheck) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        let lease = self.lease.try_lock().expect("policy fence available");
        lease.check()?;
        action(&Check(&lease))
    }
}
impl AdmissionAuthority for FencedHost {
    fn renew_control_lease(&self) -> Result<(), PlatformError> {
        let mut lease = self.0.try_lock().expect("renew outside policy fence");
        lease.renewal_attempts += 1;
        if lease.fail_renewal {
            return Err(PlatformError {
                code: PlatformErrorCode::Unavailable,
                message: "test-durable-renewal-failed".into(),
                retryable: false,
                details: Vec::new(),
            });
        }
        lease.ceiling = lease.now + 5;
        lease.renewals += 1;
        Ok(())
    }
    fn verify(
        &self,
        tenant: &TenantId,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        let mut verified = Host(Authority::new()).verify(tenant, upload)?;
        verified.grant = Arc::new(FencedGrant {
            binding: verified.grant.binding().clone(),
            lease: Arc::clone(&self.0),
        });
        Ok(verified)
    }
    fn recover(
        &self,
        binding: &AdmissionBinding,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        self.verify(&binding.tenant, upload)
    }
}

fn setup(root: &TempRoot) -> (DirectoryArtifactRepository, Arc<Mutex<Lease>>) {
    let lease = Arc::new(Mutex::new(Lease {
        now: 0,
        ceiling: 5,
        revoked: false,
        valid_until: 100,
        fail_renewal: false,
        renewals: 0,
        renewal_attempts: 0,
        grant_checks: AtomicU64::new(0),
    }));
    let repo = DirectoryArtifactRepository::open_enforced(
        root.path(),
        DirectoryArtifactRepositoryConfig::default(),
        AdmissionStorageLimits::default(),
        Arc::new(FencedHost(Arc::clone(&lease))),
    )
    .unwrap();
    (repo, lease)
}

#[test]
fn capsule_publication_renews_after_preparation_and_reads_outside_policy_fence() {
    let root = TempRoot::new();
    let (repo, lease) = setup(&root);
    let staged = Arc::clone(&lease);
    let _hook = AfterRenameGuard::new(move |_| {
        // Structural reads/staging cannot block the sampler or replacement.
        let mut lease = staged.try_lock().expect("payload I/O outside policy fence");
        lease.now += 6;
    });
    let summary = block_on(repo.admit_package(&tenant(), upload(), &mut |_| {
        // Preparation/audit may also outlast the previous five-second lease.
        lease.lock().unwrap().now = 6;
        Ok(())
    }))
    .unwrap();
    assert_eq!(lease.lock().unwrap().renewals, 2);
    assert_eq!(block_on(repo.list(None, 1)).unwrap().entries.len(), 1);
    repo.release_eligibility(&summary.descriptor.release_digest)
        .unwrap()
        .unwrap()
        .check_current()
        .unwrap();
}

#[test]
fn capsule_publication_staging_cannot_revive_revocation_or_failed_renewal() {
    for failed_renewal in [false, true] {
        let root = TempRoot::new();
        let (repo, lease) = setup(&root);
        let staged = Arc::clone(&lease);
        let _hook = AfterRenameGuard::new(move |_| {
            let mut lease = staged.try_lock().expect("payload I/O outside policy fence");
            lease.now = 6;
            lease.revoked = !failed_renewal;
            lease.fail_renewal = failed_renewal;
        });
        let failure = admit(&repo).unwrap_err();
        assert_eq!(
            failure.code,
            if failed_renewal {
                PlatformErrorCode::Unavailable
            } else {
                PlatformErrorCode::PermissionDenied
            }
        );
        assert!(block_on(repo.list(None, 1)).unwrap().entries.is_empty());
        assert_eq!(
            std::fs::read_dir(root.path().join("publications"))
                .unwrap()
                .count(),
            1,
            "retain uncertain staged state for explicit recovery"
        );
    }
}

fn selected(repo: &DirectoryArtifactRepository) -> crate::PublicationRef {
    repo.select_execution_publication(&tenant(), &artifact().descriptor.release_digest, None)
        .unwrap()
}

#[test]
fn control_metadata_scan_renews_after_verified_bytes_once_with_original_scope() {
    let root = TempRoot::new();
    let (repo, lease) = setup(&root);
    admit(&repo).unwrap();
    let reference = selected(&repo);
    let before = repo.verification_snapshot();
    let renewals = lease.lock().unwrap().renewals;
    let barrier = Arc::new(AtomicU64::new(0));
    let scanned = barrier.clone();
    let clock = lease.clone();
    let expected = reference.clone();
    let _hook = AfterMetadataScanGuard::new(move |actual| {
        assert_eq!(actual, &expected);
        assert_eq!(scanned.fetch_add(1, Ordering::SeqCst), 0);
        clock.try_lock().expect("scan owns no policy fence").now = 6;
    });
    let snapshot = repo
        .preparation_source()
        .unwrap()
        .control_historical_snapshot_selected(
            &artifact().descriptor.release_digest,
            Some(&reference.id),
        )
        .unwrap();
    let (metadata, state) = snapshot.into_parts();
    assert_eq!(
        metadata.descriptor().release_digest,
        artifact().descriptor.release_digest
    );
    let crate::HistoricalExecutionState::Eligible(grant) = state else {
        panic!("control scan must produce a current original grant");
    };
    grant.check_current().unwrap();
    grant.authorize_tenant(&tenant()).unwrap();
    assert_eq!(grant.publication(), &reference.id);
    assert_eq!(
        grant
            .authorize_tenant(&TenantId("foreign".into()))
            .unwrap_err()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    assert_eq!(barrier.load(Ordering::SeqCst), 1);
    assert_eq!(
        repo.verification_snapshot().metadata_fetch_attempts,
        before.metadata_fetch_attempts + 1
    );
    let lease = lease.lock().unwrap();
    assert_eq!(lease.renewals, renewals + 1);
    assert_eq!((lease.now, lease.ceiling), (6, 11));
}

#[test]
fn control_metadata_scan_cannot_revive_revocation_or_expired_policy() {
    for expired in [false, true] {
        let root = TempRoot::new();
        let (repo, lease) = setup(&root);
        admit(&repo).unwrap();
        let reference = selected(&repo);
        let before = repo.verification_snapshot();
        let renewals = lease.lock().unwrap().renewals;
        let clock = lease.clone();
        let _hook = AfterMetadataScanGuard::new(move |_| {
            let mut clock = clock.try_lock().expect("scan owns no policy fence");
            clock.now = 6;
            clock.revoked = !expired;
            if expired {
                clock.valid_until = 6;
            }
        });
        let snapshot = repo
            .preparation_source()
            .unwrap()
            .control_historical_snapshot_selected(
                &artifact().descriptor.release_digest,
                Some(&reference.id),
            )
            .unwrap();
        let crate::HistoricalExecutionState::Denied(denied) = snapshot.into_parts().1 else {
            panic!("lease renewal cannot authorize revoked or expired policy");
        };
        assert_eq!(denied.error().code, PlatformErrorCode::PermissionDenied);
        assert_eq!(
            repo.verification_snapshot().metadata_fetch_attempts,
            before.metadata_fetch_attempts + 1
        );
        assert!(repo
            .publication_catalog_entry(&reference)
            .unwrap()
            .is_some());
        let clock = lease.lock().unwrap();
        assert_eq!(clock.renewals, renewals + 1);
        assert_eq!((clock.now, clock.ceiling), (6, 11));
    }
}

#[test]
fn control_metadata_scan_failed_durable_renewal_has_no_positive_read_or_replay() {
    let root = TempRoot::new();
    let (repo, lease) = setup(&root);
    admit(&repo).unwrap();
    let reference = selected(&repo);
    let before = repo.verification_snapshot();
    let (attempts, checks) = {
        let clock = lease.lock().unwrap();
        (
            clock.renewal_attempts,
            clock.grant_checks.load(Ordering::SeqCst),
        )
    };
    let clock = lease.clone();
    let _hook = AfterMetadataScanGuard::new(move |_| {
        let mut clock = clock.try_lock().unwrap();
        clock.now = 6;
        clock.fail_renewal = true;
    });
    let failure = repo
        .preparation_source()
        .unwrap()
        .control_historical_snapshot_selected(
            &artifact().descriptor.release_digest,
            Some(&reference.id),
        )
        .err()
        .unwrap();
    assert_eq!(failure.code, PlatformErrorCode::Unavailable);
    assert_eq!(failure.message, "test-durable-renewal-failed");
    assert_eq!(
        repo.verification_snapshot().metadata_fetch_attempts,
        before.metadata_fetch_attempts + 1
    );
    let clock = lease.lock().unwrap();
    assert_eq!(clock.renewal_attempts, attempts + 1);
    assert_eq!(clock.grant_checks.load(Ordering::SeqCst), checks);
    assert_eq!(clock.ceiling, 5);
}

#[test]
fn ordinary_execution_and_historical_metadata_never_renew_an_expired_scan() {
    for execution in [false, true] {
        let root = TempRoot::new();
        let (repo, lease) = setup(&root);
        admit(&repo).unwrap();
        let reference = selected(&repo);
        let attempts = lease.lock().unwrap().renewal_attempts;
        let before = repo.verification_snapshot();
        let clock = lease.clone();
        let _hook = AfterMetadataScanGuard::new(move |_| clock.try_lock().unwrap().now = 6);
        let source = repo.preparation_source().unwrap();
        let release = artifact().descriptor.release_digest;
        let failure = if execution {
            source
                .metadata_selected(&release, Some(&reference.id))
                .err()
                .unwrap()
        } else {
            let snapshot = source
                .historical_snapshot_selected(&release, Some(&reference.id))
                .unwrap();
            let crate::HistoricalExecutionState::Denied(denied) = snapshot.into_parts().1 else {
                panic!("ordinary historical metadata supplies no current grant");
            };
            denied.error().clone()
        };
        assert_eq!(failure.code, PlatformErrorCode::Unavailable);
        assert_eq!(
            failure.message,
            if execution {
                "test-clock-lease-uncovered"
            } else {
                "historical-release-unavailable"
            }
        );
        assert_eq!(
            repo.verification_snapshot().metadata_fetch_attempts,
            before.metadata_fetch_attempts + 1
        );
        let clock = lease.lock().unwrap();
        assert_eq!(clock.renewal_attempts, attempts);
        assert_eq!(clock.ceiling, 5);
    }
}

#[test]
fn control_metadata_scan_corrupt_bytes_cannot_renew_authority() {
    let root = TempRoot::new();
    let (repo, lease) = setup(&root);
    admit(&repo).unwrap();
    let reference = selected(&repo);
    let attempts = lease.lock().unwrap().renewal_attempts;
    let path = repo
        .publication_path(&reference.id)
        .join(crate::local_repository::COMPONENT_FILE);
    assert!(path.is_file());
    std::fs::write(path, b"modified authenticated component").unwrap();
    lease.lock().unwrap().now = 6;
    let barrier = Arc::new(AtomicU64::new(0));
    let scanned = barrier.clone();
    let _hook = AfterMetadataScanGuard::new(move |_| {
        scanned.fetch_add(1, Ordering::SeqCst);
    });
    let failure = repo
        .preparation_source()
        .unwrap()
        .control_historical_snapshot_selected(
            &artifact().descriptor.release_digest,
            Some(&reference.id),
        )
        .err()
        .unwrap();
    assert_eq!(failure.code, PlatformErrorCode::CorruptArtifact);
    assert_eq!(barrier.load(Ordering::SeqCst), 0);
    assert_eq!(lease.lock().unwrap().renewal_attempts, attempts);
}

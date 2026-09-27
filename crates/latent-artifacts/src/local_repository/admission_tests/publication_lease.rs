//! Payload verification must not monopolize a finite policy-currentness fence.
use super::*;
use crate::local_repository::integrity::faults::AfterRenameGuard;
use std::sync::Mutex;

struct Lease {
    now: u64,
    ceiling: u64,
    revoked: bool,
    fail_renewal: bool,
    renewals: usize,
}
impl Lease {
    fn check(&self) -> Result<(), PlatformError> {
        if self.revoked || self.now >= self.ceiling {
            Err(denied())
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
        fail_renewal: false,
        renewals: 0,
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

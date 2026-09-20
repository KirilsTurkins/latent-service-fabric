//! Staged bytes do not monopolize the authority fence or bypass its final check.
use super::*;
use std::sync::Mutex;

#[derive(Default)]
struct Lease {
    now: u64,
    ceiling: u64,
    revoked: bool,
}
impl Lease {
    fn check(&self) -> Result<(), PlatformError> {
        if self.revoked || self.now >= self.ceiling {
            return Err(super::super::super::error(
                latent_core::PlatformErrorCode::PermissionDenied,
                "test-lease-not-current",
            ));
        }
        Ok(())
    }
}
struct FencedHost(Arc<Mutex<Lease>>);
struct FencedGrant {
    binding: WebAdmissionBinding,
    lease: Arc<Mutex<Lease>>,
}
struct Check<'a>(&'a Lease);
impl AdmissionRecheck for Check<'_> {
    fn check(&self) -> Result<(), PlatformError> {
        self.0.check()
    }
}
impl WebAdmissionGrant for FencedGrant {
    fn as_any(&self) -> &dyn Any {
        self
    }
    fn binding(&self) -> &WebAdmissionBinding {
        &self.binding
    }
    fn retained_bytes(&self) -> usize {
        1024
    }
    fn check_current(&self) -> Result<(), PlatformError> {
        self.lease
            .try_lock()
            .expect("authority fence available")
            .check()
    }
    fn with_current(
        &self,
        action: &mut dyn FnMut(&dyn AdmissionRecheck) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        let lease = self.lease.try_lock().expect("authority fence available");
        lease.check()?;
        action(&Check(&lease))
    }
}
impl AdmissionAuthority for FencedHost {
    fn verify(
        &self,
        tenant: &TenantId,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        Host.verify(tenant, upload)
    }
    fn recover(
        &self,
        binding: &AdmissionBinding,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        Host.recover(binding, upload)
    }
    fn verify_web(
        &self,
        tenant: &TenantId,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedWebAdmission, PlatformError> {
        let mut verified = Host.verify_web(tenant, upload)?;
        verified.grant = Arc::new(FencedGrant {
            binding: verified.grant.binding().clone(),
            lease: Arc::clone(&self.0),
        });
        Ok(verified)
    }
    fn recover_web(
        &self,
        binding: &WebAdmissionBinding,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedWebAdmission, PlatformError> {
        self.verify_web(&binding.tenant, upload)
    }
}

#[test]
fn staged_web_payload_allows_lease_renewal_but_expiry_and_revocation_cannot_commit() {
    for outcome in ["renew", "expire", "revoke"] {
        let root = TempRoot::new();
        let lease = Arc::new(Mutex::new(Lease {
            now: 0,
            ceiling: 5,
            revoked: false,
        }));
        let repo = DirectoryArtifactRepository::open_enforced(
            root.path(),
            DirectoryArtifactRepositoryConfig::default(),
            AdmissionStorageLimits::default(),
            Arc::new(FencedHost(Arc::clone(&lease))),
        )
        .unwrap();
        let observed = Arc::clone(&lease);
        let path = root.path().join("web/publications");
        *repo.web.after_payload_staged.lock().unwrap() = Some(Box::new(move || {
            assert_eq!(std::fs::read_dir(path).unwrap().count(), 1);
            // A control owner can acquire the actual same fence at the durable
            // staging boundary; no sleep or timeout stands in for this witness.
            let mut lease = observed
                .try_lock()
                .expect("payload staging must release the policy fence");
            lease.now = 7;
            if outcome != "expire" {
                lease.ceiling = 12;
            }
            lease.revoked = outcome == "revoke";
        }));
        let result = publish(&repo);
        let reference = PublicationRef::package(
            LifecycleScope::Tenant(tenant()),
            &crate::package::package_digest(&browser_test_upload().manifest),
        )
        .unwrap();
        if outcome == "renew" {
            assert!(!result.unwrap().replay);
            repo.read_web_asset(&reference, "/index.html").unwrap();
        } else {
            assert_eq!(
                result.unwrap_err().code,
                latent_core::PlatformErrorCode::Unavailable
            );
            assert!(repo.select_web_publication(&reference).is_err());
        }
        drop(repo);
        let reopened = open(&root);
        assert_eq!(
            reopened
                .web_operation_status(&reference.scope, "publish")
                .unwrap()
                .is_some(),
            outcome == "renew"
        );
        if outcome != "renew" {
            assert!(reopened.select_web_publication(&reference).is_err());
        }
    }
}

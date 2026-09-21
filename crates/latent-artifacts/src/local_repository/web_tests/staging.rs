//! Staged bytes do not monopolize the authority fence or bypass its final check.
use super::*;
use std::sync::Mutex;

#[derive(Default)]
struct Lease {
    now: u64,
    ceiling: u64,
    revoked: bool,
    renew_control: bool,
    renewals: usize,
    fail_renewal: bool,
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
    fn renew_control_lease(&self) -> Result<(), PlatformError> {
        let mut lease = self
            .0
            .try_lock()
            .expect("control renewal outside the fence");
        if lease.fail_renewal {
            return Err(super::super::super::error(
                latent_core::PlatformErrorCode::Unavailable,
                "test-lease-durability-uncertain",
            ));
        }
        if lease.renew_control {
            lease.ceiling = lease.now + 5;
            lease.renewals += 1;
        }
        Ok(())
    }
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
            ..Lease::default()
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

#[test]
fn control_commit_renews_after_preparation_and_staging_without_reviving_denied_grants() {
    for outcome in ["admit", "revoke", "uncertain"] {
        let root = TempRoot::new();
        let audit_root = TempRoot::new();
        let (audit, mut worker) = latent_audit::DirectoryPhase2AuditJournal::open(
            audit_root.path().join("audit"),
            latent_audit::AuditLimits::default(),
        )
        .unwrap();
        let lease = Arc::new(Mutex::new(Lease {
            ceiling: 5,
            renew_control: true,
            ..Lease::default()
        }));
        let repo = DirectoryArtifactRepository::open_enforced(
            root.path(),
            DirectoryArtifactRepositoryConfig::default(),
            AdmissionStorageLimits::default(),
            Arc::new(crate::AuditedAdmissionAuthority::new(
                Arc::new(FencedHost(Arc::clone(&lease))),
                audit.clone(),
            )),
        )
        .unwrap();
        let staged = Arc::clone(&lease);
        *repo.web.after_payload_staged.lock().unwrap() = Some(Box::new(move || {
            let mut value = staged.try_lock().expect("unfenced staging witness");
            assert_eq!(value.renewals, 1);
            value.now = 14;
            value.revoked = outcome == "revoke";
            value.fail_renewal = outcome == "uncertain";
        }));
        let result =
            repo.publish_web_package(context("publish", 0), browser_test_upload(), &mut |_| {
                // Preparation used the sole synchronous control worker past
                // the initial lease; a background timer cannot run here.
                lease.lock().unwrap().now = 7;
                Ok(())
            });
        let reference = PublicationRef::package(
            LifecycleScope::Tenant(tenant()),
            &crate::package::package_digest(&browser_test_upload().manifest),
        )
        .unwrap();
        if outcome == "admit" {
            assert!(!result.unwrap().replay);
            assert_eq!(lease.lock().unwrap().renewals, 2);
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
            outcome == "admit"
        );
        audit.close();
        assert!(worker
            .join_until(std::time::Instant::now() + std::time::Duration::from_secs(5))
            .unwrap());
    }
}

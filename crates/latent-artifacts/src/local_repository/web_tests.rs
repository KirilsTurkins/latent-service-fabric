//! Fault/storage tests with an explicitly injected non-cryptographic authority.
//! Signed browser/SSR admission and policy recovery live in latent-policy tests.
use super::TempRoot;
use crate::{web::*, *};
use latent_core::{PlatformError, TenantId};
use std::{
    any::Any,
    sync::{atomic::Ordering, Arc},
};

struct Host;
struct Grant(WebAdmissionBinding);
impl WebAdmissionGrant for Grant {
    fn as_any(&self) -> &dyn Any {
        self
    }
    fn binding(&self) -> &WebAdmissionBinding {
        &self.0
    }
    fn retained_bytes(&self) -> usize {
        1024
    }
    fn check_current(&self) -> Result<(), PlatformError> {
        Ok(())
    }
    fn with_current(
        &self,
        action: &mut dyn FnMut(&dyn AdmissionRecheck) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        action(self)
    }
}
impl AdmissionRecheck for Grant {
    fn check(&self) -> Result<(), PlatformError> {
        Ok(())
    }
    fn check_web_grant(&self, grant: &dyn WebAdmissionGrant) -> Result<(), PlatformError> {
        if !grant.as_any().is::<Grant>() {
            return Err(super::super::error(
                latent_core::PlatformErrorCode::PermissionDenied,
                "mock-web-grant",
            ));
        }
        grant.check_current()
    }
}
impl AdmissionAuthority for Host {
    fn verify(
        &self,
        _: &TenantId,
        _: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        Err(super::super::error(
            latent_core::PlatformErrorCode::PermissionDenied,
            "mock-capsule-unsupported",
        ))
    }
    fn recover(
        &self,
        _: &AdmissionBinding,
        _: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        Err(super::super::error(
            latent_core::PlatformErrorCode::PermissionDenied,
            "mock-capsule-unsupported",
        ))
    }
    fn verify_web(
        &self,
        tenant: &TenantId,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedWebAdmission, PlatformError> {
        let package = crate::package::inspect_package(
            &upload.manifest,
            &upload.configuration,
            crate::package::PackageLimits::default(),
        )?;
        let metadata = &upload
            .layers
            .iter()
            .find(|(path, _)| path == WEB_MANIFEST_PATH)
            .unwrap()
            .1;
        let layout = inspect_web_layout(&package, metadata)?;
        let binding = WebAdmissionBinding {
            tenant: tenant.clone(),
            package: layout.package().clone(),
            manifest: layout.manifest_digest().clone(),
            assets: layout.assets_digest().clone(),
            receipt: b"mock web admission".to_vec(),
        };
        Ok(VerifiedWebAdmission {
            layout,
            upload,
            grant: Arc::new(Grant(binding)),
        })
    }
    fn recover_web(
        &self,
        binding: &WebAdmissionBinding,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedWebAdmission, PlatformError> {
        let value = self.verify_web(&binding.tenant, upload)?;
        assert_eq!(value.grant.binding(), binding);
        Ok(value)
    }
}
fn tenant() -> TenantId {
    TenantId("tests".into())
}

#[path = "web_tests/audit.rs"]
mod audit;
#[path = "web_tests/projection.rs"]
mod projection;
fn context(operation: &str, generation: u64) -> ReleaseMutationContext {
    ReleaseMutationContext {
        scope: LifecycleScope::Tenant(tenant()),
        actor: ReleaseActor {
            subject: "mock-host".into(),
            kind: ReleaseActorKind::Host,
        },
        operation: Some(ReleaseOperationPrecondition {
            operation_id: operation.into(),
            expected_generation: generation,
        }),
    }
}
fn open(root: &TempRoot) -> DirectoryArtifactRepository {
    DirectoryArtifactRepository::open_enforced(
        root.path(),
        DirectoryArtifactRepositoryConfig::default(),
        AdmissionStorageLimits::default(),
        Arc::new(Host),
    )
    .unwrap()
}
fn publish(repo: &DirectoryArtifactRepository) -> Result<WebMutationResult, PlatformError> {
    repo.publish_web_package(
        context("publish", 0),
        browser_test_upload(),
        &mut |_| Ok(()),
    )
}
fn revoke(
    repo: &DirectoryArtifactRepository,
    reference: &PublicationRef,
) -> Result<WebMutationResult, PlatformError> {
    repo.transition_web_publication(
        context("revoke", 1),
        reference,
        ReleaseLifecycleAction::Revoke,
        ReleaseLifecycleReason::OperatorRevocation,
        &mut |_| Ok(()),
    )
}

#[test]
fn web_durability_faults_poison_held_tokens_and_restart_distinguishes_commit_from_no_commit() {
    for after_head in [false, true] {
        let root = TempRoot::new();
        let repo = open(&root);
        let reference = publish(&repo).unwrap().receipt.publication;
        let held = repo.select_web_publication(&reference).unwrap();
        if after_head {
            repo.web.fail_after_head.store(true, Ordering::SeqCst);
        } else {
            repo.fail_parent_sync_once.store(true, Ordering::SeqCst);
        }
        assert_eq!(
            revoke(&repo, &reference).unwrap_err().code,
            latent_core::PlatformErrorCode::Unavailable
        );
        assert!(held.with_current(&tenant(), &mut |_| Ok(())).is_err());
        assert!(repo.reclaim_uncommitted_content(1).is_err());
        assert!(repo.select_web_publication(&reference).is_err());
        drop(repo);
        let reopened = open(&root);
        let operation = reopened
            .web_operation_status(&reference.scope, "revoke")
            .unwrap();
        assert_eq!(operation.is_some(), after_head);
        if after_head {
            assert!(reopened.select_web_publication(&reference).is_err());
        } else {
            reopened.select_web_publication(&reference).unwrap();
        }
        assert_eq!(revoke(&reopened, &reference).unwrap().replay, after_head);
        assert!(held.with_current(&tenant(), &mut |_| Ok(())).is_err());
    }
}

#[test]
fn web_interrupted_first_publication_retains_storage_but_requires_new_admission_before_becoming_visible(
) {
    let root = TempRoot::new();
    let repo = open(&root);
    repo.fail_parent_sync_once.store(true, Ordering::SeqCst);
    assert!(publish(&repo).is_err());
    assert_eq!(
        repo.publication_storage_snapshot()
            .unwrap()
            .retained_publications,
        1
    );
    drop(repo);
    let reopened = open(&root);
    let reference = PublicationRef::package(
        LifecycleScope::Tenant(tenant()),
        &crate::package::package_digest(&browser_test_upload().manifest),
    )
    .unwrap();
    assert!(reopened.select_web_publication(&reference).is_err());
    assert!(reopened
        .web_operation_status(&reference.scope, "publish")
        .unwrap()
        .is_none());
    assert_eq!(reopened.reclaim_uncommitted_content(1024).unwrap().blobs, 0);
    assert!(!publish(&reopened).unwrap().replay);
    reopened.read_web_asset(&reference, "/index.html").unwrap();
}

#[test]
fn web_read_budget_survives_token_clones_and_recovers_only_after_actual_consumer_drop() {
    let root = TempRoot::new();
    let repo = open(&root);
    let reference = publish(&repo).unwrap().receipt.publication;
    let selections: Vec<_> = (0..32)
        .map(|_| repo.select_web_publication(&reference).unwrap())
        .collect();
    assert!(repo.select_web_publication(&reference).is_err());
    let retained: Vec<_> = selections.iter().map(|s| s.eligibility().clone()).collect();
    drop(selections);
    assert_eq!(repo.web_read_snapshot().unwrap().active_reads, 32);
    assert!(repo.read_web_asset(&reference, "/index.html").is_err());
    drop(retained);
    assert_eq!(repo.web_read_snapshot().unwrap().active_reads, 0);
    repo.select_web_publication(&reference).unwrap();
}

#[test]
fn web_capacity_rejection_never_stages_payload_or_consumes_an_operation() {
    let root = TempRoot::new();
    let repo = DirectoryArtifactRepository::open_enforced(
        root.path(),
        DirectoryArtifactRepositoryConfig {
            max_index_bytes: 4096,
            ..DirectoryArtifactRepositoryConfig::default()
        },
        AdmissionStorageLimits::default(),
        Arc::new(Host),
    )
    .unwrap();
    let before = repo.publication_storage_snapshot().unwrap();
    assert!(publish(&repo).is_err());
    assert!(!root.path().join("web").exists());
    assert_eq!(repo.publication_storage_snapshot().unwrap(), before);
}

#[test]
fn web_empty_initialization_interruption_can_resume_without_treating_temporary_bytes_as_authority()
{
    let root = TempRoot::new();
    drop(open(&root));
    std::fs::create_dir(root.path().join("web")).unwrap();
    std::fs::write(
        root.path().join("web/HEAD.next"),
        b"incomplete uncommitted initialization",
    )
    .unwrap();
    let reopened = open(&root);
    assert!(reopened
        .web_operation_status(&LifecycleScope::Tenant(tenant()), "publish")
        .unwrap()
        .is_none());
    let reference = publish(&reopened).unwrap().receipt.publication;
    reopened.read_web_asset(&reference, "/index.html").unwrap();
    drop(reopened);
    open(&root).select_web_publication(&reference).unwrap();
}

#[test]
fn web_recovery_rejects_unknown_control_files_and_bounds_uncommitted_head_allocation() {
    for extra in [false, true] {
        let root = TempRoot::new();
        let config = DirectoryArtifactRepositoryConfig {
            max_index_bytes: 64 * 1024,
            ..DirectoryArtifactRepositoryConfig::default()
        };
        let repo = DirectoryArtifactRepository::open_enforced(
            root.path(),
            config,
            AdmissionStorageLimits::default(),
            Arc::new(Host),
        )
        .unwrap();
        publish(&repo).unwrap();
        drop(repo);
        let name = if extra {
            "web/unaccounted.bin"
        } else {
            "web/HEAD.next"
        };
        let file = std::fs::File::create(root.path().join(name)).unwrap();
        file.set_len(if extra {
            1
        } else {
            config.max_index_bytes as u64 + 1
        })
        .unwrap();
        drop(file);
        assert!(DirectoryArtifactRepository::open_enforced(
            root.path(),
            config,
            AdmissionStorageLimits::default(),
            Arc::new(Host)
        )
        .is_err());
    }
}

#[test]
fn web_reclamation_removes_an_orphan_without_erasing_current_content_or_its_receipt() {
    let root = TempRoot::new();
    let repo = open(&root);
    let committed = publish(&repo).unwrap().receipt.publication;
    let mut other = context("other-publish", 0);
    other.scope = LifecycleScope::Tenant(TenantId("other".into()));
    repo.fail_parent_sync_once.store(true, Ordering::SeqCst);
    assert!(repo
        .publish_web_package(other, browser_test_upload(), &mut |_| Ok(()))
        .is_err());
    drop(repo);
    let reopened = open(&root);
    assert_eq!(
        reopened
            .publication_storage_snapshot()
            .unwrap()
            .retained_publications,
        2
    );
    assert_eq!(reopened.reclaim_uncommitted_web_content(1).unwrap(), 1);
    assert_eq!(
        reopened
            .publication_storage_snapshot()
            .unwrap()
            .retained_publications,
        1
    );
    assert_eq!(reopened.reclaim_uncommitted_web_content(1).unwrap(), 0);
    reopened.reclaim_uncommitted_content(1024).unwrap();
    reopened.read_web_asset(&committed, "/index.html").unwrap();
    assert!(reopened
        .web_operation_status(&committed.scope, "publish")
        .unwrap()
        .is_some());
}

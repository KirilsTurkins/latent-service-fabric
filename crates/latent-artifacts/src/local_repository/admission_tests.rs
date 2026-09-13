//! Storage/ownership tests use an explicitly configured test authority. They do
//! not assert that the tiny arbitrary component or evidence is cryptographically
//! or semantically valid; those checks belong to the injected policy integration.
#[cfg(unix)]
#[path = "admission_tests/audit.rs"]
mod audit;
#[path = "admission_tests/fixture.rs"]
mod fixture;
#[path = "admission_tests/retained_package.rs"]
mod retained_package;

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;

use latent_core::{PlatformError, PlatformErrorCode, TenantId};

use super::{block_on, release_dir, TempRoot};
use crate::{
    AdmissionAuthority, AdmissionBinding, AdmissionGrant, AdmissionRecheck, AdmissionStorageLimits,
    ArtifactRepository, DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig,
    PackageAdmissionUpload, VerifiedAdmission,
};
use fixture::{artifact, upload};

struct Authority {
    allowed: AtomicBool,
    generation: AtomicU64,
}
impl Authority {
    fn new() -> Arc<Self> {
        Arc::new(Self {
            allowed: AtomicBool::new(true),
            generation: AtomicU64::new(1),
        })
    }
}
struct Host(Arc<Authority>);
impl AdmissionAuthority for Host {
    fn verify(
        &self,
        tenant: &TenantId,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        let binding = AdmissionBinding {
            tenant: tenant.clone(),
            package: crate::package::package_digest(&upload.manifest),
            release: artifact().descriptor.release_digest,
            receipt: b"test historical receipt".to_vec(),
        };
        self.recover(&binding, upload)
    }
    fn recover(
        &self,
        binding: &AdmissionBinding,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        let grant = Grant {
            binding: binding.clone(),
            authority: Arc::clone(&self.0),
            generation: self.0.generation.load(Ordering::Acquire),
        };
        grant.check_current()?;
        Ok(VerifiedAdmission {
            artifact: artifact(),
            upload,
            grant: Arc::new(grant),
        })
    }
}
struct Grant {
    binding: AdmissionBinding,
    authority: Arc<Authority>,
    generation: u64,
}
impl AdmissionGrant for Grant {
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
        if !self.authority.allowed.load(Ordering::Acquire)
            || self.generation != self.authority.generation.load(Ordering::Acquire)
        {
            return Err(denied());
        }
        Ok(())
    }
    fn with_current(
        &self,
        action: &mut dyn FnMut(&dyn AdmissionRecheck) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        self.check_current()?;
        action(self)
    }
}
impl AdmissionRecheck for Grant {
    fn check(&self) -> Result<(), PlatformError> {
        self.check_current()
    }
    fn check_grant(&self, grant: &dyn AdmissionGrant) -> Result<(), PlatformError> {
        let other = grant.as_any().downcast_ref::<Self>().ok_or_else(denied)?;
        if !Arc::ptr_eq(&self.authority, &other.authority) {
            return Err(denied());
        }
        other.check_current()
    }
}
fn denied() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::PermissionDenied,
        message: "test-authority-denied".to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
fn tenant() -> TenantId {
    TenantId("examples".to_owned())
}
fn host(authority: &Arc<Authority>) -> Arc<dyn AdmissionAuthority> {
    Arc::new(Host(Arc::clone(authority)))
}
fn open(root: &TempRoot, authority: &Arc<Authority>) -> DirectoryArtifactRepository {
    DirectoryArtifactRepository::open_enforced(
        root.path(),
        DirectoryArtifactRepositoryConfig::default(),
        AdmissionStorageLimits::default(),
        host(authority),
    )
    .unwrap()
}
fn admit(repo: &DirectoryArtifactRepository) -> Result<crate::ArtifactCatalogEntry, PlatformError> {
    block_on(repo.admit_package(&tenant(), upload(), &mut |_| Ok(())))
}
fn assert_no_releases(root: &TempRoot) {
    assert_eq!(
        std::fs::read_dir(root.path().join("releases"))
            .unwrap()
            .count(),
        0
    );
    assert_eq!(
        std::fs::read_dir(root.path().join(".tmp")).unwrap().count(),
        0
    );
}

#[test]
fn exact_retry_preserves_bytes_and_history_but_refreshes_grant_incarnation() {
    let root = TempRoot::new();
    let authority = Authority::new();
    let repo = open(&root, &authority);
    let summary = admit(&repo).unwrap();
    let release = &summary.descriptor.release_digest;
    let before = repo.release_eligibility(release).unwrap().unwrap();
    let directory = release_dir(root.path(), release);
    let receipt = std::fs::read(directory.join("admission.json")).unwrap();
    let complete = std::fs::read(directory.join("COMPLETE")).unwrap();
    assert_eq!(block_on(repo.fetch(release)).unwrap(), artifact());
    let components = std::fs::read_dir(&directory)
        .unwrap()
        .filter(|entry| {
            std::fs::read(entry.as_ref().unwrap().path()).unwrap() == artifact().component_bytes
        })
        .count();
    assert_eq!(components, 1, "component bytes are stored once");
    authority.generation.fetch_add(1, Ordering::AcqRel);
    assert!(before.check_current().is_err());
    assert_eq!(admit(&repo).unwrap(), summary);
    let after = repo.release_eligibility(release).unwrap().unwrap();
    assert_ne!(before, after);
    assert_ne!(before.cache_digest(), after.cache_digest());
    assert_eq!(before.identity(), after.identity());
    assert_eq!(
        std::fs::read(directory.join("admission.json")).unwrap(),
        receipt
    );
    assert_eq!(std::fs::read(directory.join("COMPLETE")).unwrap(), complete);
    drop(repo);
    assert_eq!(
        after.check_current().unwrap_err().code,
        PlatformErrorCode::Unavailable
    );
    let reopened = open(&root, &authority);
    assert_eq!(block_on(reopened.fetch(release)).unwrap(), artifact());
}

#[test]
fn retained_ineligible_history_requires_control_reverification() {
    let root = TempRoot::new();
    let authority = Authority::new();
    let repo = open(&root, &authority);
    let summary = admit(&repo).unwrap();
    let release = &summary.descriptor.release_digest;
    drop(repo);
    authority.allowed.store(false, Ordering::Release);
    let reopened = open(&root, &authority);
    assert_eq!(block_on(reopened.list(None, 1)).unwrap().entries.len(), 1);
    assert_eq!(
        block_on(reopened.fetch(release)).unwrap_err().code,
        PlatformErrorCode::PermissionDenied
    );
    assert_eq!(
        reopened.release_eligibility(release).unwrap_err().code,
        PlatformErrorCode::PermissionDenied
    );
    assert!(reopened.reverify_retained(&tenant(), release).is_err());
    authority.allowed.store(true, Ordering::Release);
    assert_eq!(
        reopened.reverify_retained(&tenant(), release).unwrap(),
        summary
    );
    assert!(reopened.release_eligibility(release).unwrap().is_some());
    assert_eq!(
        reopened
            .reverify_retained(&TenantId("other".to_owned()), release)
            .unwrap_err()
            .code,
        PlatformErrorCode::NotFound
    );
}

#[test]
fn enforced_catalog_refuses_raw_publication_and_mode_downgrade() {
    let root = TempRoot::new();
    let authority = Authority::new();
    let repo = open(&root, &authority);
    assert_eq!(
        block_on(repo.publish(artifact())).unwrap_err().code,
        PlatformErrorCode::PermissionDenied
    );
    assert_no_releases(&root);
    drop(repo);
    assert_eq!(
        DirectoryArtifactRepository::open(
            root.path(),
            DirectoryArtifactRepositoryConfig::default()
        )
        .unwrap_err()
        .code,
        PlatformErrorCode::PermissionDenied
    );
}

#[test]
fn preflight_runs_once_without_locks_and_cannot_stage_on_rejection() {
    let root = TempRoot::new();
    let authority = Authority::new();
    let repo = open(&root, &authority);
    let mut calls = 0;
    let failure = block_on(repo.admit_package(&tenant(), upload(), &mut |_| {
        calls += 1;
        assert!(block_on(repo.list(None, 1)).unwrap().entries.is_empty());
        assert_eq!(
            admit(&repo).unwrap_err().code,
            PlatformErrorCode::ResourceExhausted
        );
        Err(denied())
    }))
    .unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::PermissionDenied);
    assert_eq!(calls, 1);
    assert_no_releases(&root);
    admit(&repo).unwrap();
    calls = 0;
    block_on(repo.admit_package(&tenant(), upload(), &mut |_| {
        calls += 1;
        Err(denied())
    }))
    .unwrap_err();
    assert_eq!(calls, 1);
}

#[test]
fn post_rename_expiry_does_not_adopt_and_exact_retry_recovers() {
    let root = TempRoot::new();
    let authority = Authority::new();
    let repo = open(&root, &authority);
    let changed = Arc::clone(&authority);
    let _hook = super::super::integrity::faults::AfterRenameGuard::new(move |_| {
        changed.allowed.store(false, Ordering::Release);
    });
    assert_eq!(
        admit(&repo).unwrap_err().code,
        PlatformErrorCode::PermissionDenied
    );
    assert!(block_on(repo.list(None, 1)).unwrap().entries.is_empty());
    assert_eq!(
        std::fs::read_dir(root.path().join("releases"))
            .unwrap()
            .count(),
        1
    );
    authority.allowed.store(true, Ordering::Release);
    admit(&repo).unwrap();
    assert_eq!(block_on(repo.list(None, 1)).unwrap().entries.len(), 1);
}

#[test]
fn parent_sync_failure_retains_pending_bytes_without_positive_index() {
    let root = TempRoot::new();
    let authority = Authority::new();
    let repo = open(&root, &authority);
    repo.fail_parent_sync_once.store(true, Ordering::SeqCst);
    assert_eq!(admit(&repo).unwrap_err().code, PlatformErrorCode::Internal);
    assert!(block_on(repo.list(None, 1)).unwrap().entries.is_empty());
    admit(&repo).unwrap();
    assert_eq!(block_on(repo.list(None, 1)).unwrap().entries.len(), 1);
}

#[test]
fn auxiliary_and_combined_index_limits_reject_before_staging() {
    let root = TempRoot::new();
    let authority = Authority::new();
    let limits = AdmissionStorageLimits {
        max_auxiliary_bytes: 128,
        ..AdmissionStorageLimits::default()
    };
    let repo = DirectoryArtifactRepository::open_enforced(
        root.path(),
        DirectoryArtifactRepositoryConfig::default(),
        limits,
        host(&authority),
    )
    .unwrap();
    assert_eq!(
        admit(&repo).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_no_releases(&root);
    drop(repo);
    let default = DirectoryArtifactRepositoryConfig::default();
    let config = DirectoryArtifactRepositoryConfig {
        max_index_bytes: super::super::index::entry_cost(&artifact(), default)
            + super::super::index::REPOSITORY_ACCOUNTED_BYTES
            + 128,
        ..default
    };
    let repo = DirectoryArtifactRepository::open_enforced(
        root.path(),
        config,
        AdmissionStorageLimits::default(),
        host(&authority),
    )
    .unwrap();
    assert_eq!(
        admit(&repo).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_no_releases(&root);
    assert!(block_on(repo.list(None, 1)).unwrap().entries.is_empty());
}

#[test]
fn corrupt_evidence_is_not_classified_as_expired_history() {
    let root = TempRoot::new();
    let authority = Authority::new();
    let repo = open(&root, &authority);
    let release = admit(&repo).unwrap().descriptor.release_digest;
    let path = release_dir(root.path(), &release).join("admission-0001.bin");
    std::fs::write(&path, b"tampered manifest").unwrap();
    assert_eq!(
        block_on(repo.fetch(&release)).unwrap_err().code,
        PlatformErrorCode::CorruptArtifact
    );
    drop(repo);
    authority.allowed.store(false, Ordering::Release);
    assert_eq!(
        DirectoryArtifactRepository::open_enforced(
            root.path(),
            DirectoryArtifactRepositoryConfig::default(),
            AdmissionStorageLimits::default(),
            host(&authority)
        )
        .unwrap_err()
        .code,
        PlatformErrorCode::CorruptArtifact
    );
}

#[test]
fn same_component_cannot_replace_immutable_package_or_evidence() {
    let root = TempRoot::new();
    let authority = Authority::new();
    let repo = open(&root, &authority);
    let release = admit(&repo).unwrap().descriptor.release_digest;
    let before = std::fs::read(release_dir(root.path(), &release).join("COMPLETE")).unwrap();
    for changed_package in [false, true] {
        let mut changed = upload();
        if changed_package {
            changed.manifest.push(b' ');
        } else {
            changed.signatures[0].manifest.push(b' ');
        }
        assert_eq!(
            block_on(repo.admit_package(&tenant(), changed, &mut |_| Ok(())))
                .unwrap_err()
                .code,
            PlatformErrorCode::AlreadyExists
        );
    }
    assert_eq!(
        std::fs::read(release_dir(root.path(), &release).join("COMPLETE")).unwrap(),
        before
    );
    assert_eq!(block_on(repo.fetch(&release)).unwrap(), artifact());
}

#[test]
fn foreign_owner_and_spare_capacity_fail_without_staging() {
    let root = TempRoot::new();
    let authority = Authority::new();
    let repo = open(&root, &authority);
    let mut excessive = upload();
    excessive.layers.reserve(257);
    assert_eq!(
        block_on(repo.admit_package(&tenant(), excessive, &mut |_| Ok(())))
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_no_releases(&root);
    let release = admit(&repo).unwrap().descriptor.release_digest;
    let token = repo.release_eligibility(&release).unwrap().unwrap();
    assert_eq!(
        token
            .check_for_authority(&host(&authority))
            .unwrap_err()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    let configured = repo.admission.as_ref().unwrap().authority.clone();
    token.check_for_authority(&configured).unwrap();
}

#[test]
fn batch_checks_owner_retirement_and_rejects_other_authority() {
    let first_root = TempRoot::new();
    let second_root = TempRoot::new();
    let first_authority = Authority::new();
    let second_authority = Authority::new();
    let first = open(&first_root, &first_authority);
    let second = open(&second_root, &second_authority);
    let release = admit(&first).unwrap().descriptor.release_digest;
    admit(&second).unwrap();
    let a = first.release_eligibility(&release).unwrap().unwrap();
    let b = second.release_eligibility(&release).unwrap().unwrap();
    let mut calls = 0;
    assert!(
        crate::ReleaseEligibility::with_all_current(&[a.clone(), b], &mut |_| {
            calls += 1;
            Ok(())
        })
        .is_err()
    );
    assert_eq!(calls, 0);
    crate::ReleaseEligibility::with_all_current(&[a.clone(), a.clone()], &mut |check| {
        check.check()
    })
    .unwrap();
    drop(first);
    assert!(crate::ReleaseEligibility::with_all_current(&[a], &mut |_| {
        calls += 1;
        Ok(())
    })
    .is_err());
    assert_eq!(calls, 0);
}

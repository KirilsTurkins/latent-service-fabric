//! Real Ed25519 publisher/provenance proofs and checked embedded SBOM through
//! the concrete durable catalog; no guest execution or external registry needed.
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll, Wake, Waker};

use latent_artifacts::package::{decode_config, PackageLimits};
use latent_artifacts::{
    AdmissionAuthority, AdmissionStorageLimits, ArtifactCatalogEntry, ArtifactRepository,
    DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig, PackageAdmissionUpload,
};
use latent_core::{PlatformError, PlatformErrorCode, ReleaseDigest, TenantId};

use super::{Fixture, SupplyChainAuthority, NOW};

struct Noop;
impl Wake for Noop {
    fn wake(self: Arc<Self>) {}
}
fn ready<T>(mut future: Pin<Box<dyn Future<Output = T> + Send + '_>>) -> T {
    let waker = Waker::from(Arc::new(Noop));
    match future.as_mut().poll(&mut Context::from_waker(&waker)) {
        Poll::Ready(value) => value,
        Poll::Pending => panic!("catalog control operation unexpectedly awaited"),
    }
}
fn tenant() -> TenantId {
    TenantId("tests".to_owned())
}
fn authority(fixture: &Fixture, root: &std::path::Path) -> Arc<SupplyChainAuthority> {
    Arc::new(
        SupplyChainAuthority::open(root, fixture.approved(), fixture.clock.clone(), 5).unwrap(),
    )
}
fn catalog(
    root: &std::path::Path,
    authority: &Arc<SupplyChainAuthority>,
) -> DirectoryArtifactRepository {
    let configured: Arc<dyn AdmissionAuthority> = authority.clone();
    DirectoryArtifactRepository::open_enforced(
        root,
        DirectoryArtifactRepositoryConfig::default(),
        AdmissionStorageLimits::default(),
        configured,
    )
    .unwrap()
}
fn admit(
    repo: &DirectoryArtifactRepository,
    upload: PackageAdmissionUpload,
) -> Result<ArtifactCatalogEntry, PlatformError> {
    ready(repo.admit_package(&tenant(), upload, &mut |_| Ok(())))
}
fn release(fixture: &Fixture) -> ReleaseDigest {
    let value = fixture.upload();
    ReleaseDigest(
        decode_config(&value.configuration, PackageLimits::default())
            .unwrap()
            .component_digest
            .unwrap()
            .to_string(),
    )
}

#[test]
fn signed_package_roundtrips_metadata_and_sealed_preparation_source() {
    let fixture = Fixture::new();
    let root = tempfile::tempdir().unwrap();
    let authority = authority(&fixture, &root.path().join("trust"));
    let repo = Arc::new(catalog(&root.path().join("catalog"), &authority));
    let summary = admit(&repo, fixture.upload()).unwrap();
    assert_eq!(
        summary.descriptor.publisher.as_ref().unwrap().0,
        "publisher-a"
    );
    let release = &summary.descriptor.release_digest;
    let token = repo.release_eligibility(release).unwrap().unwrap();
    assert_eq!(
        summary.descriptor.reference.0,
        format!("package:{}", token.package())
    );
    let receipt: serde_json::Value = serde_json::from_slice(&token.binding().receipt).unwrap();
    assert!(receipt["sbomInventory"]
        .as_str()
        .unwrap()
        .starts_with("sha256:"));
    assert_eq!(receipt["builder"], "builder-a");
    let metadata = ready(repo.fetch_verified_metadata(release)).unwrap();
    assert_eq!(metadata.descriptor(), &summary.descriptor);
    let source = repo.preparation_source().unwrap();
    assert_eq!(source.eligibility(release).unwrap().unwrap(), token);
    assert!(source.identity(release).unwrap().is_some());
    let fetched = ready(source.fetch(release)).unwrap();
    assert_eq!(fetched.contracts, metadata.contracts());
    assert_eq!(fetched.manifest, *metadata.manifest());
    assert_eq!(receipt["verifiedAt"], NOW);
    let owned = repo.clone().owned_preparation_source().unwrap();
    assert_eq!(
        owned.read_bounds(release).unwrap().component_bytes,
        fetched.component_bytes.len() as u64
    );
    assert_eq!(owned.eligibility(release).unwrap().unwrap(), token);
    assert_eq!(admit(&repo, fixture.upload()).unwrap(), summary);
}

#[test]
fn malformed_or_missing_evidence_never_creates_preparation_authority() {
    let fixture = Fixture::new();
    let root = tempfile::tempdir().unwrap();
    let authority = authority(&fixture, &root.path().join("trust"));
    let repo = catalog(&root.path().join("catalog"), &authority);
    let release = release(&fixture);
    for case in 0..4 {
        let mut upload = fixture.upload();
        match case {
            0 => upload.signatures.clear(),
            1 => upload.provenance.clear(),
            2 => upload.layers[0].1[0] ^= 1,
            _ => upload.manifest[0] ^= 1,
        }
        assert!(admit(&repo, upload).is_err());
        assert!(ready(repo.list(None, 1)).unwrap().entries.is_empty());
        assert_eq!(
            repo.preparation_source()
                .unwrap()
                .identity(&release)
                .unwrap_err()
                .code,
            PlatformErrorCode::NotFound
        );
        assert_eq!(
            repo.release_eligibility(&release).unwrap_err().code,
            PlatformErrorCode::NotFound
        );
        assert_eq!(
            std::fs::read_dir(repo.root().join("releases"))
                .unwrap()
                .count(),
            0
        );
        assert_eq!(
            std::fs::read_dir(repo.root().join(".tmp")).unwrap().count(),
            0
        );
    }
    admit(&repo, fixture.upload()).unwrap();
    assert!(repo.release_eligibility(&release).unwrap().is_some());
}

#[test]
fn revocation_blocks_source_and_original_evidence_can_reverify_after_approved_update() {
    let mut fixture = Fixture::new();
    let root = tempfile::tempdir().unwrap();
    let authority = authority(&fixture, &root.path().join("trust"));
    let repo = catalog(&root.path().join("catalog"), &authority);
    let summary = admit(&repo, fixture.upload()).unwrap();
    let release = &summary.descriptor.release_digest;
    let previous = repo.release_eligibility(release).unwrap().unwrap();
    fixture.policy["generation"] = serde_json::json!(2);
    fixture.policy["publisherRevocations"]["generation"] = serde_json::json!(2);
    fixture.policy["publisherRevocations"]["revokedPublishers"] =
        serde_json::json!(["publisher-a"]);
    authority.replace_policy(fixture.approved()).unwrap();
    assert!(previous.check_current().is_err());
    assert!(ready(repo.fetch(release)).is_err());
    assert!(ready(repo.fetch_verified_metadata(release)).is_err());
    assert!(repo
        .preparation_source()
        .unwrap()
        .identity(release)
        .is_err());
    assert!(repo.reverify_retained(&tenant(), release).is_err());
    fixture.policy["generation"] = serde_json::json!(3);
    fixture.policy["publisherRevocations"]["generation"] = serde_json::json!(3);
    fixture.policy["publisherRevocations"]["revokedPublishers"] = serde_json::json!([]);
    authority.replace_policy(fixture.approved()).unwrap();
    assert_eq!(repo.reverify_retained(&tenant(), release).unwrap(), summary);
    let current = repo.release_eligibility(release).unwrap().unwrap();
    assert_eq!(current.binding(), previous.binding());
    assert_ne!(current.cache_digest(), previous.cache_digest());
    assert!(previous.check_current().is_err());
    current.check_current().unwrap();
    authority.retire();
    assert!(current.check_current().is_err());
    assert!(ready(repo.fetch(release)).is_err());
}

#[test]
fn expired_package_recovers_only_as_history_and_retired_catalog_tokens_fail() {
    let fixture = Fixture::new();
    let root = tempfile::tempdir().unwrap();
    let authority = authority(&fixture, &root.path().join("trust"));
    let catalog_root = root.path().join("catalog");
    let repo = catalog(&catalog_root, &authority);
    let summary = admit(&repo, fixture.upload()).unwrap();
    let release = &summary.descriptor.release_digest;
    let token = repo.release_eligibility(release).unwrap().unwrap();
    drop(repo);
    assert_eq!(
        token.check_current().unwrap_err().code,
        PlatformErrorCode::Unavailable
    );
    fixture.clock.set(2000); // The original publisher and builder envelopes expire.
    authority.renew_clock_lease().unwrap();
    let reopened = catalog(&catalog_root, &authority);
    assert_eq!(
        ready(reopened.get_catalog_entry(&tenant(), release)).unwrap(),
        Some(summary.clone())
    );
    assert_eq!(ready(reopened.list(None, 1)).unwrap().entries.len(), 1);
    assert_eq!(
        reopened.release_eligibility(release).unwrap_err().code,
        PlatformErrorCode::PermissionDenied
    );
    assert!(reopened
        .preparation_source()
        .unwrap()
        .identity(release)
        .is_err());
    assert!(ready(reopened.fetch(release)).is_err());
    assert!(reopened.reverify_retained(&tenant(), release).is_err());
}

#[test]
fn aged_proof_refresh_preserves_original_durable_receipt_and_package() {
    let fixture = Fixture::new();
    let root = tempfile::tempdir().unwrap();
    let authority = authority(&fixture, &root.path().join("trust"));
    let repo = catalog(&root.path().join("catalog"), &authority);
    let release = admit(&repo, fixture.upload())
        .unwrap()
        .descriptor
        .release_digest;
    let previous = repo.release_eligibility(&release).unwrap().unwrap();
    let directory = repo
        .root()
        .join("releases")
        .join(release.0.strip_prefix("sha256:").unwrap());
    let complete = std::fs::read(directory.join("COMPLETE")).unwrap();
    fixture.clock.set(NOW + 60);
    authority.renew_clock_lease().unwrap();
    assert!(previous.check_current().is_err());
    assert!(ready(repo.fetch(&release)).is_err());
    repo.reverify_retained(&tenant(), &release).unwrap();
    let current = repo.release_eligibility(&release).unwrap().unwrap();
    assert_eq!(current.binding(), previous.binding());
    assert_ne!(current.cache_digest(), previous.cache_digest());
    assert_eq!(std::fs::read(directory.join("COMPLETE")).unwrap(), complete);
    ready(repo.fetch(&release)).unwrap();
}

#[test]
fn held_retired_token_does_not_keep_authority_or_catalog_root_locked() {
    let fixture = Fixture::new();
    let root = tempfile::tempdir().unwrap();
    let trust_root = root.path().join("trust");
    let catalog_root = root.path().join("catalog");
    let previous_owner = authority(&fixture, &trust_root);
    let repo = catalog(&catalog_root, &previous_owner);
    let release = admit(&repo, fixture.upload())
        .unwrap()
        .descriptor
        .release_digest;
    let held = repo.release_eligibility(&release).unwrap().unwrap();
    previous_owner.retire();
    drop(repo);
    assert!(held.check_current().is_err());
    fixture.clock.set(NOW + 5);
    let replacement = authority(&fixture, &trust_root);
    let reopened = catalog(&catalog_root, &replacement);
    let fresh = reopened.release_eligibility(&release).unwrap().unwrap();
    fresh.check_current().unwrap();
    assert!(held.check_current().is_err());
    assert_eq!(held.binding(), fresh.binding());
    assert_ne!(held.cache_digest(), fresh.cache_digest());
    assert!(previous_owner.renew_clock_lease().is_err());
    ready(reopened.fetch(&release)).unwrap();
}

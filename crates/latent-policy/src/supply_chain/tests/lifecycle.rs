//! Real publisher, builder, and embedded-SBOM proofs across lifecycle changes.

use std::collections::BTreeMap;
use std::path::Path;
use std::sync::Arc;

use latent_artifacts::{
    AdmissionAuthority, AdmissionStorageLimits, ArtifactRepository, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig, HistoricalExecutionState, LifecycleScope, ReleaseActor,
    ReleaseActorKind, ReleaseEvidenceUpload, ReleaseLifecycleAction, ReleaseLifecycleReason,
    ReleaseLifecycleState, ReleaseLifecycleStatus, ReleaseLiveEligibility, ReleaseMutationContext,
    ReleaseOperationPrecondition, ReleaseOperationReceipt,
};
use latent_core::{PackageDigest, PlatformError, PlatformErrorCode, ReleaseDigest, TenantId};

use super::catalog::ready;
use super::{Fixture, SupplyChainAuthority, NOW};

fn tenant() -> TenantId {
    TenantId("tests".into())
}
fn context(id: &str, generation: u64) -> ReleaseMutationContext {
    ReleaseMutationContext {
        scope: LifecycleScope::Tenant(tenant()),
        actor: ReleaseActor {
            subject: "real-crypto-lifecycle-test".into(),
            kind: ReleaseActorKind::Host,
        },
        operation: Some(ReleaseOperationPrecondition {
            operation_id: id.into(),
            expected_generation: generation,
        }),
    }
}
fn catalog(root: &Path, owner: &Arc<SupplyChainAuthority>) -> DirectoryArtifactRepository {
    let configured: Arc<dyn AdmissionAuthority> = owner.clone();
    DirectoryArtifactRepository::open_enforced(
        root,
        DirectoryArtifactRepositoryConfig::default(),
        AdmissionStorageLimits::default(),
        configured,
    )
    .unwrap()
}
fn evidence(fixture: &Fixture) -> ReleaseEvidenceUpload {
    let upload = fixture.upload();
    ReleaseEvidenceUpload {
        signatures: upload.signatures,
        provenance: upload.provenance,
        sboms: upload.sboms,
    }
}
fn status(repo: &DirectoryArtifactRepository, release: &ReleaseDigest) -> ReleaseLifecycleStatus {
    ready(repo.get_release_lifecycle(&LifecycleScope::Tenant(tenant()), release))
        .unwrap()
        .unwrap()
}
fn renew(
    repo: &DirectoryArtifactRepository,
    release: &ReleaseDigest,
    package: &PackageDigest,
    evidence: ReleaseEvidenceUpload,
    id: &str,
    generation: u64,
) -> Result<ReleaseOperationReceipt, PlatformError> {
    ready(repo.renew_release_evidence(
        context(id, generation),
        release,
        package,
        evidence,
        &mut |_| Ok(()),
    ))
}
fn revoke(
    repo: &DirectoryArtifactRepository,
    release: &ReleaseDigest,
    id: &str,
    generation: u64,
) -> ReleaseOperationReceipt {
    ready(repo.change_release_lifecycle(
        context(id, generation),
        release,
        ReleaseLifecycleAction::Revoke,
        ReleaseLifecycleReason::OperatorRevocation,
        &mut |_| Ok(()),
    ))
    .unwrap()
}
fn immutable_files(
    repo: &DirectoryArtifactRepository,
    release: &ReleaseDigest,
) -> BTreeMap<String, Vec<u8>> {
    let directory = repo
        .root()
        .join("releases")
        .join(release.0.strip_prefix("sha256:").unwrap());
    let mut result = BTreeMap::new();
    let mut bytes = 0;
    for entry in std::fs::read_dir(directory).unwrap() {
        let entry = entry.unwrap();
        assert!(entry.file_type().unwrap().is_file());
        let value = std::fs::read(entry.path()).unwrap();
        bytes += value.len();
        assert!(
            bytes < 256 * 1024,
            "only the tiny owned fixture is retained"
        );
        result.insert(entry.file_name().into_string().unwrap(), value);
        assert!(result.len() < 100);
    }
    assert!(result.contains_key("COMPLETE"));
    assert!(result.contains_key("admission.json"));
    result
}

struct Setup {
    fixture: Fixture,
    root: tempfile::TempDir,
    owner: Arc<SupplyChainAuthority>,
    repo: DirectoryArtifactRepository,
    release: ReleaseDigest,
    package: PackageDigest,
}
impl Setup {
    fn new() -> Self {
        let fixture = Fixture::new();
        let root = tempfile::tempdir().unwrap();
        let owner = Arc::new(
            SupplyChainAuthority::open(
                &root.path().join("trust"),
                fixture.approved(),
                fixture.clock.clone(),
                5,
            )
            .unwrap(),
        );
        let repo = catalog(&root.path().join("catalog"), &owner);
        let release = ready(repo.admit_package(&tenant(), fixture.upload(), &mut |_| Ok(())))
            .unwrap()
            .descriptor
            .release_digest;
        let package = repo
            .release_eligibility(&release)
            .unwrap()
            .unwrap()
            .package()
            .clone();
        Self {
            fixture,
            root,
            owner,
            repo,
            release,
            package,
        }
    }
}

#[test]
fn renewal_replaces_only_selected_evidence_and_invalidates_old_execution_generation() {
    let Setup {
        fixture,
        root,
        owner,
        repo,
        release,
        package,
    } = Setup::new();
    let original_files = immutable_files(&repo, &release);
    let original = repo.execution_eligibility(&release).unwrap().unwrap();
    let original_receipt = original.admission().unwrap().binding().receipt.clone();
    fixture.clock.set(NOW + 1);
    // The same valid signed bytes receive a freshly verified admission receipt.
    let receipt = renew(&repo, &release, &package, evidence(&fixture), "renew-1", 1).unwrap();
    assert_eq!(receipt.record.as_ref().unwrap().generation, 2);
    assert!(receipt
        .record
        .as_ref()
        .unwrap()
        .evidence_revision_digest
        .is_some());
    let fresh = repo.execution_eligibility(&release).unwrap().unwrap();
    assert_eq!(fresh.package(), Some(&package));
    assert_eq!(fresh.generation(), 2);
    fresh.check_current().unwrap();
    assert!(original.check_current().is_err());
    assert_ne!(original.cache_digest(), fresh.cache_digest());
    let selected_receipt = fresh.admission().unwrap().binding().receipt.clone();
    assert_ne!(selected_receipt, original_receipt);
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&selected_receipt).unwrap()["verifiedAt"],
        NOW + 1
    );
    assert_eq!(immutable_files(&repo, &release), original_files);
    assert_eq!(
        renew(&repo, &release, &package, evidence(&fixture), "renew-1", 1).unwrap(),
        receipt,
        "exact replay precedes the now-stale generation precondition"
    );
    drop(repo);
    assert!(fresh.check_current().is_err());
    let reopened = catalog(&root.path().join("catalog"), &owner);
    let recovered = reopened.execution_eligibility(&release).unwrap().unwrap();
    assert_eq!(recovered.generation(), 2);
    assert_eq!(
        recovered.admission().unwrap().binding().receipt,
        selected_receipt
    );
    recovered.check_current().unwrap();
    assert_eq!(immutable_files(&reopened, &release), original_files);
}

#[test]
fn bad_evidence_wrong_package_and_new_policy_denial_cannot_advance_lifecycle() {
    let mut setup = Setup::new();
    let original = status(&setup.repo, &setup.release).record;
    let before = immutable_files(&setup.repo, &setup.release);
    let held = setup
        .repo
        .execution_eligibility(&setup.release)
        .unwrap()
        .unwrap();
    let mut missing = evidence(&setup.fixture);
    missing.provenance.clear();
    assert!(renew(
        &setup.repo,
        &setup.release,
        &setup.package,
        missing,
        "missing-builder",
        1
    )
    .is_err());
    assert_eq!(status(&setup.repo, &setup.release).record, original);
    held.check_current().unwrap();
    let wrong: PackageDigest = format!("sha256:{}", "0".repeat(64)).parse().unwrap();
    assert!(renew(
        &setup.repo,
        &setup.release,
        &wrong,
        evidence(&setup.fixture),
        "wrong-package",
        1
    )
    .is_err());
    assert_eq!(status(&setup.repo, &setup.release).record, original);
    let mut corrupt = evidence(&setup.fixture);
    corrupt.signatures[0].payload[0] ^= 1;
    assert!(renew(
        &setup.repo,
        &setup.release,
        &setup.package,
        corrupt,
        "corrupt-signature",
        1
    )
    .is_err());
    assert_eq!(status(&setup.repo, &setup.release).record, original);
    setup.fixture.policy["generation"] = serde_json::json!(2);
    setup.fixture.policy["tenants"][0]["publishers"] = serde_json::json!([]);
    setup
        .owner
        .replace_policy(setup.fixture.approved())
        .unwrap();
    assert!(held.check_current().is_err());
    assert!(renew(
        &setup.repo,
        &setup.release,
        &setup.package,
        evidence(&setup.fixture),
        "new-policy-denial",
        1
    )
    .is_err());
    let denied = status(&setup.repo, &setup.release);
    assert_eq!(denied.record, original);
    assert_eq!(denied.eligibility, ReleaseLiveEligibility::Denied);
    assert_eq!(immutable_files(&setup.repo, &setup.release), before);
}

#[test]
fn lifecycle_revocation_is_terminal_for_reverify_republication_renewal_and_restart() {
    let Setup {
        fixture,
        root,
        owner,
        repo,
        release,
        package,
    } = Setup::new();
    let held = repo.execution_eligibility(&release).unwrap().unwrap();
    let revoked = revoke(&repo, &release, "terminal-revoke", 1);
    assert_eq!(
        revoked.record.as_ref().unwrap().state,
        ReleaseLifecycleState::Revoked
    );
    assert!(held.check_current().is_err());
    assert!(repo.reverify_retained(&tenant(), &release).is_err());
    assert!(ready(repo.admit_package(&tenant(), fixture.upload(), &mut |_| Ok(()))).is_err());
    assert!(renew(
        &repo,
        &release,
        &package,
        evidence(&fixture),
        "revoked-renew",
        2
    )
    .is_err());
    assert_eq!(
        status(&repo, &release).record,
        *revoked.record.as_ref().unwrap()
    );
    drop(repo);
    let reopened = catalog(&root.path().join("catalog"), &owner);
    let observed = status(&reopened, &release);
    assert_eq!(observed.record.state, ReleaseLifecycleState::Revoked);
    assert_eq!(observed.record.generation, 2);
    assert_eq!(observed.eligibility, ReleaseLiveEligibility::Denied);
    assert!(reopened.execution_eligibility(&release).is_err());
    assert!(ready(reopened.fetch(&release)).is_err());
    assert!(reopened.reverify_retained(&tenant(), &release).is_err());
    let snapshot = ready(reopened.historical_execution_snapshot(&release)).unwrap();
    assert!(matches!(
        snapshot.into_parts().1,
        HistoricalExecutionState::Denied(_)
    ));
}

#[test]
fn expired_trust_reopens_as_denied_history_and_emergency_revocation_remains_available() {
    let Setup {
        fixture,
        root,
        owner,
        repo,
        release,
        ..
    } = Setup::new();
    let originals = immutable_files(&repo, &release);
    drop(repo);
    owner.retire();
    fixture.clock.set(3001);
    let expired = Arc::new(
        SupplyChainAuthority::open(
            &root.path().join("trust"),
            fixture.approved(),
            fixture.clock.clone(),
            5,
        )
        .unwrap(),
    );
    let reopened = catalog(&root.path().join("catalog"), &expired);
    let observed = status(&reopened, &release);
    assert_eq!(observed.record.state, ReleaseLifecycleState::Admitted);
    assert_eq!(observed.eligibility, ReleaseLiveEligibility::Denied);
    assert!(reopened.execution_eligibility(&release).is_err());
    assert_eq!(ready(reopened.list(None, 1)).unwrap().entries.len(), 1);
    let snapshot = ready(reopened.historical_execution_snapshot(&release)).unwrap();
    assert!(matches!(
        snapshot.into_parts().1,
        HistoricalExecutionState::Denied(_)
    ));
    assert_eq!(immutable_files(&reopened, &release), originals);
    revoke(&reopened, &release, "expired-emergency-revoke", 1);
    assert_eq!(
        status(&reopened, &release).record.state,
        ReleaseLifecycleState::Revoked
    );
    drop(reopened);
    // Expired trust never turns corrupt retained bytes into acceptable history.
    let path = root
        .path()
        .join("catalog/releases")
        .join(release.0.strip_prefix("sha256:").unwrap())
        .join("component.wasm");
    std::fs::write(path, b"corrupt fixture").unwrap();
    let configured: Arc<dyn AdmissionAuthority> = expired;
    assert_eq!(
        DirectoryArtifactRepository::open_enforced(
            root.path().join("catalog"),
            DirectoryArtifactRepositoryConfig::default(),
            AdmissionStorageLimits::default(),
            configured
        )
        .err()
        .unwrap()
        .code,
        PlatformErrorCode::CorruptArtifact
    );
}

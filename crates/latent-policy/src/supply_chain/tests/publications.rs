//! Signed identical Wasm with independent package/tenant lifecycle authority.
use super::catalog::ready;
use super::{Fixture, SupplyChainAuthority};
use latent_artifacts::package::{decode_config, package_digest, PackageLimits};
use latent_artifacts::{
    AdmissionAuthority, AdmissionStorageLimits, ArtifactRepository, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig, LifecycleScope, ManagedPublicationUpload, ReleaseActor,
    ReleaseActorKind, ReleaseEvidenceUpload, ReleaseLifecycleAction, ReleaseLifecycleReason,
    ReleaseLifecycleState, ReleaseMutationContext, ReleaseOperationPrecondition,
};
use latent_core::TenantId;
use std::sync::Arc;

fn scope(tenant: &str) -> LifecycleScope {
    LifecycleScope::Tenant(TenantId(tenant.into()))
}
fn context(tenant: &str, operation: &str, generation: u64) -> ReleaseMutationContext {
    ReleaseMutationContext {
        scope: scope(tenant),
        actor: ReleaseActor {
            subject: "trusted-test-adapter".into(),
            kind: ReleaseActorKind::Administrator,
        },
        operation: Some(ReleaseOperationPrecondition {
            operation_id: operation.into(),
            expected_generation: generation,
        }),
    }
}
fn open(
    path: &std::path::Path,
    authority: &Arc<SupplyChainAuthority>,
) -> DirectoryArtifactRepository {
    let authority: Arc<dyn AdmissionAuthority> = authority.clone();
    DirectoryArtifactRepository::open_enforced(
        path,
        DirectoryArtifactRepositoryConfig::default(),
        AdmissionStorageLimits::default(),
        authority,
    )
    .unwrap()
}

#[test]
fn corrected_embedded_inventory_and_two_tenants_share_wasm_without_sharing_authority() {
    let mut fixture = Fixture::new();
    fixture.policy["tenants"]
        .as_array_mut()
        .unwrap()
        .push(serde_json::json!({"tenant":"other","publishers":["publisher-a"]}));
    let root = tempfile::tempdir().unwrap();
    let authority = Arc::new(
        SupplyChainAuthority::open(
            &root.path().join("trust"),
            fixture.approved(),
            fixture.clock.clone(),
            5,
        )
        .unwrap(),
    );
    let original = fixture.neutral_inventory_upload(false);
    let corrected = fixture.neutral_inventory_upload(true);
    let original_package = package_digest(&original.manifest);
    assert_ne!(original_package, package_digest(&corrected.manifest));
    assert_eq!(
        decode_config(&original.configuration, PackageLimits::default())
            .unwrap()
            .component_digest,
        decode_config(&corrected.configuration, PackageLimits::default())
            .unwrap()
            .component_digest
    );
    let path = root.path().join("catalog");
    let repo = open(&path, &authority);
    let publish = |tenant, upload, operation| {
        ready(repo.publish_managed(
            context(tenant, operation, 0),
            ManagedPublicationUpload::Package(upload),
            &mut |_| Ok(()),
        ))
        .unwrap()
    };
    let first = publish(
        "tests",
        fixture.neutral_inventory_upload(false),
        "create-original",
    );
    let other = publish(
        "other",
        fixture.neutral_inventory_upload(false),
        "create-other",
    );
    let correction = publish("tests", corrected, "create-correction");
    assert_ne!(first.publication, other.publication);
    assert_ne!(first.publication, correction.publication);
    let first_token = repo
        .publication_execution_eligibility(&first.publication)
        .unwrap();
    let other_token = repo
        .publication_execution_eligibility(&other.publication)
        .unwrap();
    let correction_token = repo
        .publication_execution_eligibility(&correction.publication)
        .unwrap();
    assert_eq!(
        first_token.admission().unwrap().package(),
        other_token.admission().unwrap().package()
    );
    assert_ne!(
        first_token.admission().unwrap(),
        other_token.admission().unwrap()
    );
    assert!(first_token
        .authorize_tenant(&TenantId("other".into()))
        .is_err());
    assert_eq!(
        repo.resolve_publication(&scope("tests"), &first.publication)
            .unwrap(),
        Some(first.publication.clone())
    );
    assert!(repo
        .resolve_publication(&scope("other"), &first.publication)
        .is_err());
    assert_eq!(
        repo.resolve_publication(&scope("other"), &other.publication)
            .unwrap(),
        Some(other.publication.clone())
    );
    // Proof refresh selects the retained publication even when component bytes
    // have two package associations in this tenant and another tenant's row.
    for publication in [
        &first.publication,
        &correction.publication,
        &other.publication,
    ] {
        assert_eq!(
            repo.reverify_publication(publication)
                .unwrap()
                .publication
                .as_ref(),
            Some(&publication.id)
        );
    }
    let foreign = latent_artifacts::PublicationRef {
        scope: scope("other"),
        id: first.publication.id.clone(),
    };
    assert_eq!(
        repo.reverify_publication(&foreign).unwrap_err().code,
        latent_core::PlatformErrorCode::NotFound
    );
    let original_selector = first.publication.clone();
    let renewed = repo
        .renew_publication_evidence(
            context("tests", "renew-original", 1),
            &original_selector,
            &original_package,
            ReleaseEvidenceUpload {
                signatures: original.signatures,
                provenance: original.provenance,
                sboms: original.sboms,
            },
            &mut |_| Ok(()),
        )
        .unwrap();
    assert_eq!(renewed.record.unwrap().generation, 2);
    assert!(first_token.check_current().is_err());
    other_token.check_current().unwrap();
    correction_token.check_current().unwrap();
    repo.change_publication_lifecycle(
        context("tests", "revoke-original", 2),
        &original_selector,
        ReleaseLifecycleAction::Revoke,
        ReleaseLifecycleReason::OperatorRevocation,
        &mut |_| Ok(()),
    )
    .unwrap();
    repo.change_publication_lifecycle(
        context("tests", "retire-original", 3),
        &original_selector,
        ReleaseLifecycleAction::Retire,
        ReleaseLifecycleReason::EndOfSupport,
        &mut |_| Ok(()),
    )
    .unwrap();
    assert!(repo.reverify_publication(&first.publication).is_err());
    repo.reverify_publication(&correction.publication).unwrap();
    repo.reverify_publication(&other.publication).unwrap();
    other_token.check_current().unwrap();
    correction_token.check_current().unwrap();
    repo.reclaim_uncommitted_content(32).unwrap();
    assert_eq!(
        repo.publication_storage_snapshot()
            .unwrap()
            .retained_publications,
        3
    );
    let wasm = repo
        .fetch_publication(&correction.publication)
        .unwrap()
        .component_bytes;
    assert_eq!(
        repo.fetch_publication(&other.publication)
            .unwrap()
            .component_bytes,
        wasm
    );
    drop(repo);
    let repo = open(&path, &authority);
    assert_eq!(
        repo.publication_lifecycle_status(&first.publication)
            .unwrap()
            .unwrap()
            .record
            .state,
        ReleaseLifecycleState::Retired
    );
    assert_eq!(
        repo.publication_lifecycle_status(&first.publication)
            .unwrap()
            .unwrap()
            .record
            .generation,
        4
    );
    assert_eq!(
        repo.fetch_publication(&correction.publication)
            .unwrap()
            .component_bytes,
        wasm
    );
    assert_eq!(
        repo.fetch_publication(&other.publication)
            .unwrap()
            .component_bytes,
        wasm
    );
    assert!(repo
        .publication_execution_eligibility(&first.publication)
        .is_err());
    assert_eq!(
        ready(repo.publish_managed(
            context("tests", "create-original", 0),
            ManagedPublicationUpload::Package(fixture.neutral_inventory_upload(false)),
            &mut |_| Ok(())
        ))
        .unwrap(),
        first
    );
}

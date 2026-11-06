//! Actual payload unlink, shared reference accounting and crash continuation.
use super::*;
mod qualification;
use latent_artifacts::{
    PublicationReclamationLimits, PublicationReclamationLookup, PublicationReclamationRequest,
    PublicationReclamationResult,
};

fn request(
    repo: &DirectoryArtifactRepository,
    deletion: &PublicationDeletionRequest,
) -> PublicationReclamationRequest {
    let observed = repo
        .inspect_publication_reclamation(deletion, PublicationReclamationLimits::default(), TIMEOUT)
        .unwrap();
    PublicationReclamationRequest {
        deletion: deletion.clone(),
        expected_catalog_fence: observed.catalog_fence,
        limits: PublicationReclamationLimits::default(),
    }
}
fn reclaim(
    repo: &DirectoryArtifactRepository,
    request: &PublicationReclamationRequest,
) -> std::result::Result<PublicationReclamationResult, PlatformError> {
    repo.reclaim_tombstoned_capsules(request, TIMEOUT, &mut |_| Ok(()))
}
fn deleted(
    repo: &DirectoryArtifactRepository,
    publication: &PublicationRef,
) -> PublicationDeletionRequest {
    let deletion = selection(repo, publication);
    commit(repo, &deletion).unwrap();
    deletion
}

#[test]
fn native_cleanup_reclaims_capsule_files_and_capacity_after_sync_and_reopen() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let publication = retired(&repo, "cleanup-one");
    let catalog = bind(&roots[1], &repo);
    let deletion = deleted(&repo, &publication);
    let request = request(&repo, &deletion);
    let before = repo.publication_capacity_snapshot().unwrap();
    let result = reclaim(&repo, &request).unwrap();
    assert!(!result.replay);
    assert_eq!(result.receipt.request, request);
    assert_eq!(
        result.receipt.content.publication_file_bytes,
        before.storage.publication_file_bytes
    );
    assert_eq!(
        result.receipt.content.last_reference_blob_bytes,
        before.storage.shared_blob_bytes
    );
    assert!(!roots[0]
        .0
        .join("publications")
        .join(publication.id.hex())
        .exists());
    assert_eq!(fs::read_dir(roots[0].0.join("blobs")).unwrap().count(), 0);
    let after = repo.publication_capacity_snapshot().unwrap();
    assert_eq!(after.storage.publication_file_bytes, 0);
    assert_eq!(after.storage.shared_blob_bytes, 0);
    assert_eq!(after.storage.retained_publications, 0);
    assert_eq!(after.indexed_publications, 0);
    assert_eq!(after.release_directories, 0);
    assert!(after.storage.retention_control_bytes > 0);
    hidden(&repo, &publication);
    assert!(commit(&repo, &deletion).unwrap().replay);
    assert!(reclaim(&repo, &request).unwrap().replay);
    let stable = bytes(&roots[0].0);
    assert!(reclaim(&repo, &request).unwrap().replay);
    assert_eq!(stable, bytes(&roots[0].0));
    drop(catalog);
    drop(repo);
    let repo = artifacts(&roots[0]);
    let _catalog = bind(&roots[1], &repo);
    hidden(&repo, &publication);
    assert_eq!(repo.publication_capacity_snapshot().unwrap(), after);
    assert_eq!(
        repo.publication_reclamation_operation(&deletion.scope, &deletion.operation_id)
            .unwrap(),
        PublicationReclamationLookup::Found(result.receipt)
    );
    assert!(reclaim(&repo, &request).unwrap().replay);
    assert_eq!(stable, bytes(&roots[0].0));
}

#[test]
fn native_cleanup_preserves_shared_live_and_retired_publication_content() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let one = retired(&repo, "cleanup-one");
    let two = publish(&repo, "alice", "cleanup-two");
    let catalog = bind(&roots[1], &repo);
    let deletion = deleted(&repo, &one);
    let result = reclaim(&repo, &request(&repo, &deletion)).unwrap();
    assert!(result.receipt.content.shared_blobs_retained > 0);
    assert!(repo.fetch_publication(&two).is_ok());
    let capacity = repo.publication_capacity_snapshot().unwrap();
    assert_eq!(capacity.storage.retained_publications, 1);
    assert_eq!(capacity.indexed_publications, 1);
    assert_eq!(capacity.release_directories, 1);
    drop(catalog);
    drop(repo);
    let repo = artifacts(&roots[0]);
    let _catalog = bind(&roots[1], &repo);
    assert!(repo.fetch_publication(&two).is_ok());
    assert_eq!(repo.publication_capacity_snapshot().unwrap(), capacity);
    revoke(&repo, &two);
    let second = batch(&repo, std::slice::from_ref(&two), "delete-second");
    commit(&repo, &second).unwrap();
    let result = reclaim(&repo, &request(&repo, &second)).unwrap();
    assert!(result.receipt.content.last_reference_blobs > 0);
    assert_eq!(repo.publication_storage_snapshot().unwrap().shared_blobs, 0);
    assert!(fs::read_dir(roots[0].0.join("publications"))
        .unwrap()
        .next()
        .is_none());
}

#[test]
fn native_cleanup_exact_batch_reclaims_shared_blobs_only_once() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let publications: Vec<_> = (0..32)
        .map(|i| retired(&repo, &format!("batch-{i}")))
        .collect();
    let _catalog = bind(&roots[1], &repo);
    let deletion = batch(&repo, &publications, "cleanup-batch");
    commit(&repo, &deletion).unwrap();
    let before = repo.publication_storage_snapshot().unwrap();
    let result = reclaim(&repo, &request(&repo, &deletion)).unwrap();
    assert_eq!(result.receipt.content.publications, 32);
    assert_eq!(
        result.receipt.content.last_reference_blobs,
        before.shared_blobs
    );
    assert_eq!(
        result.receipt.content.last_reference_blob_bytes,
        before.shared_blob_bytes
    );
    assert_eq!(repo.publication_storage_snapshot().unwrap().shared_blobs, 0);
    assert_eq!(
        repo.publication_capacity_snapshot()
            .unwrap()
            .indexed_publications,
        0
    );
}

#[test]
fn native_cleanup_rechecks_catalog_and_control_revisions_after_preflight() {
    for kind in 0..2 {
        let roots = [TempRoot::new(), TempRoot::new()];
        let repo = artifacts(&roots[0]);
        let one = retired(&repo, "cleanup-one");
        let other = publish(&repo, "alice", "live");
        let catalog = bind(&roots[1], &repo);
        let deletion = deleted(&repo, &one);
        let request = request(&repo, &deletion);
        let before = payload_bytes(&roots[0].0);
        let failure = repo
            .reclaim_tombstoned_capsules(&request, TIMEOUT, &mut |_| {
                if kind == 0 {
                    let selected = selection(&repo, &other);
                    repo.change_publication_retention(
                        &PublicationRetentionRequest {
                            scope: selected.scope,
                            actor: actor(),
                            operation_id: "keep-live".into(),
                            expected_catalog_fence: selected.expected_catalog_fence,
                            action: PublicationRetentionAction::Pin,
                            targets: selected.targets,
                        },
                        TIMEOUT,
                        &mut |_| Ok(()),
                    )?;
                } else {
                    run(catalog.apply(deployment("other", "alice", &release())))?;
                }
                Ok(())
            })
            .unwrap_err();
        assert_eq!(failure.code, PlatformErrorCode::StateConflict);
        assert_eq!(before, payload_bytes(&roots[0].0));
        assert_eq!(
            repo.publication_reclamation_operation(&deletion.scope, &deletion.operation_id)
                .unwrap(),
            PublicationReclamationLookup::Unknown
        );
    }
}

#[test]
fn native_cleanup_refuses_stale_foreign_unknown_and_changed_original_requests() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let one = retired(&repo, "cleanup-one");
    let _catalog = bind(&roots[1], &repo);
    let deletion = deleted(&repo, &one);
    let base = request(&repo, &deletion);
    let before = bytes(&roots[0].0);
    for kind in 0..4 {
        let mut candidate = base.clone();
        match kind {
            0 => candidate.expected_catalog_fence = deletion.expected_catalog_fence,
            1 => candidate.deletion.scope = LifecycleScope::Tenant(TenantId("foreign".into())),
            2 => candidate.deletion.operation_id = "missing".into(),
            _ => candidate.deletion.actor.subject = "changed".into(),
        }
        let mut called = false;
        assert!(repo
            .reclaim_tombstoned_capsules(&candidate, TIMEOUT, &mut |_| {
                called = true;
                Ok(())
            })
            .is_err());
        assert!(!called);
        assert_eq!(bytes(&roots[0].0), before);
    }
}

#[test]
fn native_cleanup_audit_refusal_and_work_limits_have_no_side_effects() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let one = retired(&repo, "cleanup-one");
    let _catalog = bind(&roots[1], &repo);
    let deletion = deleted(&repo, &one);
    let base = request(&repo, &deletion);
    let before = bytes(&roots[0].0);
    let capacity = repo.publication_capacity_snapshot().unwrap();
    assert!(repo
        .reclaim_tombstoned_capsules(&base, TIMEOUT, &mut |_| Err(PlatformError {
            code: PlatformErrorCode::ResourceExhausted,
            message: "audit-full".into(),
            retryable: false,
            details: Vec::new()
        }))
        .is_err());
    let mut tiny = base.clone();
    tiny.limits.maximum_bytes_hashed = 1;
    assert!(reclaim(&repo, &tiny).is_err());
    tiny = base.clone();
    tiny.limits.maximum_files = 2;
    assert!(reclaim(&repo, &tiny).is_err());
    assert!(repo
        .reclaim_tombstoned_capsules(&base, Duration::ZERO, &mut |_| Ok(()))
        .is_err());
    assert_eq!(bytes(&roots[0].0), before);
    assert_eq!(repo.publication_capacity_snapshot().unwrap(), capacity);
}

#[test]
fn native_cleanup_recovers_original_operation_at_each_unlink_sync_refund_boundary() {
    for point in [
        DevelopmentRetentionFault::AfterIntent,
        DevelopmentRetentionFault::AfterHead,
        DevelopmentRetentionFault::AfterIntentRemoval,
        DevelopmentRetentionFault::AfterReclamationCommit,
        DevelopmentRetentionFault::AfterPublicationFileUnlink,
        DevelopmentRetentionFault::AfterPublicationDirectorySync,
        DevelopmentRetentionFault::AfterBlobUnlink,
        DevelopmentRetentionFault::AfterBlobParentSync,
        DevelopmentRetentionFault::BeforeReclamationReceipt,
        DevelopmentRetentionFault::AfterReclamationReceipt,
    ] {
        let roots = [TempRoot::new(), TempRoot::new()];
        let repo = artifacts(&roots[0]);
        let one = retired(&repo, "cleanup-crash");
        let catalog = bind(&roots[1], &repo);
        let deletion = deleted(&repo, &one);
        let request = request(&repo, &deletion);
        repo.inject_retention_fault_for_test(point);
        assert_eq!(
            reclaim(&repo, &request).unwrap_err().code,
            PlatformErrorCode::Unavailable,
            "{point:?}"
        );
        assert!(repo.publication_capacity_snapshot().is_err());
        assert_eq!(
            repo.publication_reclamation_operation(&deletion.scope, &deletion.operation_id)
                .unwrap(),
            PublicationReclamationLookup::Uncertain
        );
        assert!(reclaim(&repo, &request).is_err());
        drop(catalog);
        drop(repo);
        let repo = artifacts(&roots[0]);
        let _catalog = bind(&roots[1], &repo);
        hidden(&repo, &one);
        let result = reclaim(&repo, &request).unwrap();
        assert!(result.replay, "{point:?}");
        assert_eq!(result.receipt.request, request);
        assert_eq!(repo.publication_storage_snapshot().unwrap().shared_blobs, 0);
        assert_eq!(
            repo.publication_capacity_snapshot()
                .unwrap()
                .indexed_publications,
            0
        );
        assert_eq!(
            repo.publication_capacity_snapshot()
                .unwrap()
                .release_directories,
            0
        );
        assert!(commit(&repo, &deletion).unwrap().replay);
        assert!(!roots[0].0.join("lifecycle/retention/INTENT").exists());
    }
}

#[test]
fn native_cleanup_format_promotion_without_intent_does_not_delete_or_invent_receipt() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let one = retired(&repo, "cleanup-before-intent");
    let catalog = bind(&roots[1], &repo);
    let deletion = deleted(&repo, &one);
    let request = request(&repo, &deletion);
    let before = payload_bytes(&roots[0].0);
    repo.inject_retention_fault_for_test(
        DevelopmentRetentionFault::AfterReclamationFormatPromotion,
    );
    assert!(reclaim(&repo, &request).is_err());
    drop(catalog);
    drop(repo);
    let repo = artifacts(&roots[0]);
    let _catalog = bind(&roots[1], &repo);
    assert_eq!(before, payload_bytes(&roots[0].0));
    hidden(&repo, &one);
    assert_eq!(
        repo.publication_reclamation_operation(&deletion.scope, &deletion.operation_id)
            .unwrap(),
        PublicationReclamationLookup::Unknown
    );
}

#[test]
fn native_cleanup_pending_corruption_rejects_before_any_remaining_unlink() {
    for kind in 0..3 {
        let roots = [TempRoot::new(), TempRoot::new()];
        let repo = artifacts(&roots[0]);
        let one = retired(&repo, "cleanup-corrupt");
        let catalog = bind(&roots[1], &repo);
        let deletion = deleted(&repo, &one);
        let request = request(&repo, &deletion);
        repo.inject_retention_fault_for_test(DevelopmentRetentionFault::AfterReclamationCommit);
        assert!(reclaim(&repo, &request).is_err());
        drop(catalog);
        drop(repo);
        let directory = roots[0].0.join("publications").join(one.id.hex());
        match kind {
            0 => fs::write(directory.join("foreign"), b"must not unlink").unwrap(),
            1 => {
                fs::remove_file(directory.join("component.wasm")).unwrap();
                fs::write(directory.join("component.wasm"), b"changed").unwrap();
            }
            _ => {
                let path = directory.join("manifest.json");
                fs::remove_file(&path).unwrap();
                std::os::unix::fs::symlink("metadata.json", path).unwrap();
            }
        }
        let before = payload_bytes(&roots[0].0);
        assert!(DirectoryArtifactRepository::open(
            &roots[0].0,
            DirectoryArtifactRepositoryConfig::default()
        )
        .is_err());
        assert_eq!(payload_bytes(&roots[0].0), before);
    }
}

#[test]
fn native_cleanup_downgraded_or_missing_authority_refuses_before_temporary_cleanup() {
    for kind in 0..3 {
        let roots = [TempRoot::new(), TempRoot::new()];
        let repo = artifacts(&roots[0]);
        let one = retired(&repo, "cleanup-mode");
        let catalog = bind(&roots[1], &repo);
        let deletion = deleted(&repo, &one);
        let request = request(&repo, &deletion);
        repo.inject_retention_fault_for_test(DevelopmentRetentionFault::AfterReclamationCommit);
        assert!(reclaim(&repo, &request).is_err());
        drop(catalog);
        drop(repo);
        match kind {
            0 => fs::write(
                roots[0].0.join("LIFECYCLE_MODE"),
                b"lsf-release-lifecycle-deletion-v1\n",
            )
            .unwrap(),
            1 => fs::remove_file(roots[0].0.join("lifecycle/retention/HEAD")).unwrap(),
            _ => fs::write(roots[0].0.join("lifecycle/retention/HEAD"), b"{}").unwrap(),
        }
        fs::write(roots[0].0.join(".tmp/must-remain"), b"no cleanup").unwrap();
        let before = bytes(&roots[0].0);
        assert!(DirectoryArtifactRepository::open(
            &roots[0].0,
            DirectoryArtifactRepositoryConfig::default()
        )
        .is_err());
        assert_eq!(bytes(&roots[0].0), before);
    }
}

#[test]
fn native_cleanup_finished_payload_resurrection_and_new_publish_id_are_refused() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let one = retired(&repo, "cleanup-resurrect");
    let catalog = bind(&roots[1], &repo);
    let deletion = deleted(&repo, &one);
    let original = payload_bytes(&roots[0].0);
    reclaim(&repo, &request(&repo, &deletion)).unwrap();
    let stable = bytes(&roots[0].0);
    let mut value = artifact("shared-executable");
    value.manifest.metadata.tenant = Some(TenantId("alice".into()));
    let contract = latent_core::ContractId("alice:echo/api@1.0.0".into());
    value.manifest.world = contract.clone();
    value.manifest.exports[0].contract = contract.clone();
    value.contracts[0].id = contract.clone();
    value.contracts[0].package_name = "alice:echo".into();
    value.contracts[0].interfaces[0].id = latent_core::InterfaceId(contract.0);
    value
        .manifest
        .metadata
        .annotations
        .insert("inventory-revision".into(), "cleanup-resurrect".into());
    for (id, generation) in [("cleanup-resurrect", 0), ("new-publish-id", 2)] {
        let result = run(repo.publish_managed(
            context("alice", id, generation),
            ManagedPublicationUpload::Local(value.clone()),
            &mut |_| Ok(()),
        ));
        assert_eq!(result.unwrap_err().code, PlatformErrorCode::NotFound);
        assert!(payload_bytes(&roots[0].0).is_empty());
    }
    assert!(repo.fetch_publication(&one).is_err());
    assert_eq!(bytes(&roots[0].0), stable);
    drop(catalog);
    drop(repo);
    for (path, contents) in original {
        if path.starts_with("publications") {
            fs::create_dir_all(roots[0].0.join(&path).parent().unwrap()).unwrap();
            fs::write(roots[0].0.join(path), contents).unwrap();
        }
    }
    let restored = payload_bytes(&roots[0].0);
    assert!(DirectoryArtifactRepository::open(
        &roots[0].0,
        DirectoryArtifactRepositoryConfig::default()
    )
    .is_err());
    assert_eq!(restored, payload_bytes(&roots[0].0));
}

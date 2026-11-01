//! Durable negative authority exercised through both actual native catalog owners.
use super::*;
use latent_artifacts::{
    DevelopmentRetentionFault, PublicationContentReclamation, PublicationDeletionLookup,
    PublicationDeletionResult, PublicationDeletionStage, PublicationRetentionTarget,
};
use latent_core::{PlatformError, PlatformErrorCode};
use std::fs;

mod capacity;
mod cleanup;
mod reclamation;
mod recovery;

fn retired(repo: &DirectoryArtifactRepository, id: &str) -> PublicationRef {
    let publication = publish(repo, "alice", id);
    repo.change_publication_lifecycle(
        context("alice", &format!("retire-{id}"), 1),
        &publication,
        ReleaseLifecycleAction::Retire,
        ReleaseLifecycleReason::OperatorRetirement,
        &mut |_| Ok(()),
    )
    .unwrap();
    publication
}
fn batch(
    repo: &DirectoryArtifactRepository,
    publications: &[PublicationRef],
    id: &str,
) -> PublicationDeletionRequest {
    let mut publications = publications.to_vec();
    publications.sort_by(|a, b| a.id.cmp(&b.id));
    let selected = repo
        .publication_retention_snapshot(&publications[0].scope, &publications, TIMEOUT)
        .unwrap();
    PublicationDeletionRequest {
        scope: publications[0].scope.clone(),
        actor: actor(),
        operation_id: id.into(),
        expected_catalog_fence: selected.catalog_fence,
        // Source selections have larger elements; compact the in-place collect
        // before passing the exact bounded target allocation to the host API.
        targets: selected
            .selections
            .into_iter()
            .map(|s| s.target)
            .collect::<Vec<_>>()
            .into_boxed_slice()
            .into_vec(),
    }
}
fn commit(
    repo: &DirectoryArtifactRepository,
    request: &PublicationDeletionRequest,
) -> std::result::Result<PublicationDeletionResult, PlatformError> {
    repo.tombstone_publications(request, TIMEOUT, &mut |_| Ok(()))
}
fn hidden(repo: &DirectoryArtifactRepository, publication: &PublicationRef) {
    assert_eq!(
        repo.resolve_publication(&publication.scope, publication)
            .unwrap(),
        None
    );
    assert_eq!(repo.publication_catalog_entry(publication).unwrap(), None);
    assert_eq!(
        repo.publication_lifecycle_status(publication).unwrap(),
        None
    );
    assert!(repo.publication_execution_eligibility(publication).is_err());
    assert!(repo.fetch_publication(publication).is_err());
    assert!(repo
        .publication_retention_snapshot(
            &publication.scope,
            std::slice::from_ref(publication),
            TIMEOUT
        )
        .is_err());
}
fn payload_bytes(root: &Path) -> BTreeMap<PathBuf, Vec<u8>> {
    bytes(root)
        .into_iter()
        .filter(|(p, _)| p.starts_with("publications") || p.starts_with("blobs"))
        .collect()
}
#[test]
fn native_tombstone_commit_removes_visibility_preserves_payload_and_recovers_original_receipts() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let publication = retired(&repo, "one");
    let catalog = bind(&roots[1], &repo);
    let request = selection(&repo, &publication);
    let payloads = payload_bytes(&roots[0].0);
    let before = repo.publication_capacity_snapshot().unwrap();
    let result = commit(&repo, &request).unwrap();
    assert!(!result.replay);
    assert_eq!(
        result.receipt.stage,
        PublicationDeletionStage::VisibilityRemoved
    );
    hidden(&repo, &publication);
    assert_eq!(payloads, payload_bytes(&roots[0].0));
    let after = repo.publication_capacity_snapshot().unwrap();
    assert_eq!(after.indexed_publications, before.indexed_publications);
    assert_eq!(after.release_directories, before.release_directories);
    assert_eq!(
        after.storage.shared_blob_bytes,
        before.storage.shared_blob_bytes
    );
    assert_eq!(
        after.storage.publication_file_bytes,
        before.storage.publication_file_bytes
    );
    assert!(after.index_bytes > before.index_bytes);
    assert!(after.charged_storage_bytes > before.charged_storage_bytes);
    let committed_files = bytes(&roots[0].0);
    let replay = commit(&repo, &request).unwrap();
    assert!(replay.replay);
    assert_eq!(replay.receipt, result.receipt);
    assert_eq!(bytes(&roots[0].0), committed_files);
    // The original publication receipt remains recoverable, not admission.
    assert_eq!(publish(&repo, "alice", "one"), publication);
    hidden(&repo, &publication);
    assert_eq!(bytes(&roots[0].0), committed_files);
    assert_eq!(
        repo.reclaim_uncommitted_content(32).unwrap(),
        PublicationContentReclamation::default()
    );
    drop(catalog);
    drop(repo);
    let repo = artifacts(&roots[0]);
    let _catalog = bind(&roots[1], &repo);
    hidden(&repo, &publication);
    assert_eq!(repo.publication_capacity_snapshot().unwrap(), after);
    assert_eq!(
        repo.publication_deletion_operation(&request.scope, &request.operation_id)
            .unwrap(),
        PublicationDeletionLookup::Found(result.receipt)
    );
    assert!(commit(&repo, &request).unwrap().replay);
    assert_eq!(publish(&repo, "alice", "one"), publication);
    hidden(&repo, &publication);
    assert_eq!(payload_bytes(&roots[0].0), payloads);
}
#[test]
fn native_tombstone_preflight_rejection_and_expired_deadline_make_no_persistent_change() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let publication = retired(&repo, "one");
    let _catalog = bind(&roots[1], &repo);
    let request = selection(&repo, &publication);
    let before = bytes(&roots[0].0);
    let capacity = repo.publication_capacity_snapshot().unwrap();
    let rejected = PlatformError {
        code: PlatformErrorCode::ResourceExhausted,
        message: "audit-capacity".into(),
        retryable: false,
        details: Default::default(),
    };
    assert_eq!(
        repo.tombstone_publications(&request, TIMEOUT, &mut |_| Err(rejected.clone()))
            .unwrap_err(),
        rejected
    );
    assert_eq!(
        repo.tombstone_publications(&request, Duration::ZERO, &mut |_| panic!(
            "invalid deadline"
        ))
        .unwrap_err()
        .code,
        PlatformErrorCode::InvalidArgument
    );
    // No sleeping: expire the original caller deadline with a bounded spin.
    let error = repo
        .tombstone_publications(&request, Duration::from_millis(5), &mut |_| {
            let end = std::time::Instant::now() + Duration::from_millis(6);
            while std::time::Instant::now() < end {
                std::hint::spin_loop();
            }
            Ok(())
        })
        .unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::DeadlineExceeded);
    assert_eq!(before, bytes(&roots[0].0));
    assert_eq!(capacity, repo.publication_capacity_snapshot().unwrap());
    assert_eq!(
        repo.publication_deletion_operation(&request.scope, &request.operation_id)
            .unwrap(),
        PublicationDeletionLookup::Unknown
    );
}
#[test]
fn native_tombstone_rechecks_preparation_readers_created_during_preflight() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let publication = retired(&repo, "one");
    let _catalog = bind(&roots[1], &repo);
    let request = selection(&repo, &publication);
    let before = bytes(&roots[0].0);
    let mut reader = None;
    let error = repo
        .tombstone_publications(&request, TIMEOUT, &mut |_| {
            reader = Some(repo.clone().owned_preparation_source().unwrap());
            Ok(())
        })
        .unwrap_err();
    assert_eq!(error.message, "publication-deletion-readers-active");
    assert_eq!(before, bytes(&roots[0].0));
    let cloned = reader.as_ref().unwrap().clone();
    drop(reader);
    assert!(commit(&repo, &request).is_err());
    drop(cloned);
    commit(&repo, &request).unwrap();
    hidden(&repo, &publication);
}
#[test]
fn native_tombstone_rechecks_pins_and_unrelated_control_commits_after_preflight() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let publication = retired(&repo, "one");
    let other = publish(&repo, "bob", "other");
    let catalog = bind(&roots[1], &repo);
    let request = selection(&repo, &publication);
    let mut attempted = false;
    assert!(repo
        .tombstone_publications(&request, TIMEOUT, &mut |_| {
            attempted = true;
            run(catalog.apply(deployment("other", "bob", &release())))?;
            Ok(())
        })
        .is_err());
    assert!(attempted);
    assert!(repo
        .publication_catalog_entry(&publication)
        .unwrap()
        .is_some());
    assert!(!roots[0].0.join("lifecycle/retention/INTENT").exists());
    let request = selection(&repo, &publication);
    repo.tombstone_publications(&request, TIMEOUT, &mut |_| {
        repo.change_publication_retention(
            &PublicationRetentionRequest {
                scope: request.scope.clone(),
                actor: actor(),
                operation_id: "rollback-pin".into(),
                expected_catalog_fence: request.expected_catalog_fence,
                action: PublicationRetentionAction::Pin,
                targets: request.targets.clone(),
            },
            TIMEOUT,
            &mut |_| Ok(()),
        )?;
        Ok(())
    })
    .unwrap_err();
    assert!(repo
        .publication_retention_snapshot(&request.scope, std::slice::from_ref(&publication), TIMEOUT)
        .unwrap()
        .selections[0]
        .pin
        .is_some());
    assert_eq!(
        repo.publication_deletion_operation(&request.scope, &request.operation_id)
            .unwrap(),
        PublicationDeletionLookup::Unknown
    );
    assert!(repo.publication_execution_eligibility(&other).is_ok());
}
#[test]
fn native_tombstone_rejects_stale_foreign_and_mixed_batches_without_partial_visibility() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let a = retired(&repo, "a");
    let b = retired(&repo, "b");
    let _catalog = bind(&roots[1], &repo);
    let request = batch(&repo, &[a.clone(), b.clone()], "delete-both");
    let before = bytes(&roots[0].0);
    let mut bad = request.clone();
    bad.targets[1].expected_generation += 1;
    assert_eq!(
        commit(&repo, &bad).unwrap_err().code,
        PlatformErrorCode::StateConflict
    );
    assert!(repo.publication_catalog_entry(&a).unwrap().is_some());
    assert!(repo.publication_catalog_entry(&b).unwrap().is_some());
    let scope = LifecycleScope::Tenant(TenantId("foreign".into()));
    bad = request.clone();
    bad.scope = scope.clone();
    for t in &mut bad.targets {
        t.publication.scope = scope.clone();
    }
    let foreign = commit(&repo, &bad).unwrap_err();
    let mut missing = bad.clone();
    missing.targets = vec![PublicationRetentionTarget {
        publication: PublicationRef::package(
            scope.clone(),
            &"sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
                .parse()
                .unwrap(),
        )
        .unwrap(),
        expected_generation: 2,
    }];
    assert_eq!(foreign, commit(&repo, &missing).unwrap_err());
    assert_eq!(before, bytes(&roots[0].0));
    commit(&repo, &request).unwrap();
    hidden(&repo, &a);
    hidden(&repo, &b);
    assert_eq!(
        repo.publication_deletion_operation(&scope, &request.operation_id)
            .unwrap(),
        PublicationDeletionLookup::Unknown
    );
    let mut changed = request.clone();
    changed.actor.subject = "changed".into();
    assert!(commit(&repo, &changed).is_err());
}
#[test]
fn native_tombstones_preserve_shared_blobs_and_unrelated_eligible_publications() {
    use std::os::unix::fs::MetadataExt;
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let a = retired(&repo, "a");
    let b = retired(&repo, "b");
    let other = publish(&repo, "alice", "other");
    let _catalog = bind(&roots[1], &repo);
    let paths: Vec<_> = [&a, &b, &other]
        .into_iter()
        .map(|p| {
            roots[0]
                .0
                .join("publications")
                .join(p.id.hex())
                .join("component.wasm")
        })
        .collect();
    let inode = fs::metadata(&paths[0]).unwrap().ino();
    assert!(paths
        .iter()
        .all(|p| fs::metadata(p).unwrap().ino() == inode));
    let before = repo.publication_storage_snapshot().unwrap();
    commit(&repo, &batch(&repo, &[a.clone(), b.clone()], "delete-two")).unwrap();
    assert_eq!(
        repo.reclaim_uncommitted_content(32).unwrap(),
        PublicationContentReclamation::default()
    );
    assert!(paths
        .iter()
        .all(|p| fs::metadata(p).unwrap().ino() == inode));
    let after = repo.publication_storage_snapshot().unwrap();
    println!(
        "native-tombstone-measurement {}",
        serde_json::json!({
            "scenario": "three-publications-two-terminal-tombstones",
            "before": {"retainedPublications": before.retained_publications,
                "sharedBlobs": before.shared_blobs, "sharedBlobBytes":before.shared_blob_bytes,
                "publicationFileBytes":before.publication_file_bytes,
                "retentionControlBytes":before.retention_control_bytes},
            "after": {"retainedPublications": after.retained_publications,
                "sharedBlobs": after.shared_blobs, "sharedBlobBytes":after.shared_blob_bytes,
                "publicationFileBytes":after.publication_file_bytes,
                "retentionControlBytes":after.retention_control_bytes}
        })
    );
    assert_eq!(before.shared_blobs, after.shared_blobs);
    assert_eq!(before.shared_blob_bytes, after.shared_blob_bytes);
    assert_eq!(before.publication_file_bytes, after.publication_file_bytes);
    assert_eq!(before.retained_publications, after.retained_publications);
    assert!(repo.fetch_publication(&other).is_ok());
    hidden(&repo, &a);
    hidden(&repo, &b);
}

#[test]
fn native_reference_writer_and_revision_are_retained_across_the_tombstone_commit() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    // This observation wrapper delegates every selection and exclusion to the
    // actual persisted DirectoryDeploymentRepository; it supplies no model rows.
    struct ObservedNative {
        native: Arc<Store>,
        visits: AtomicUsize,
    }
    impl PublicationReferenceAuthority for ObservedNative {
        fn catalog_authority(
            &self,
        ) -> std::result::Result<latent_artifacts::LifecycleAuthorityHandle, PlatformError>
        {
            self.native.catalog_authority()
        }
        fn with_unreferenced_publications(
            &self,
            owner: &latent_artifacts::LifecycleAuthorityHandle,
            publications: &[PublicationRef],
            action: &mut dyn FnMut(u64) -> std::result::Result<(), PlatformError>,
        ) -> std::result::Result<(), PlatformError> {
            self.native
                .with_unreferenced_publications(owner, publications, &mut |revision| {
                    assert!(self.native.writer.try_lock().is_err());
                    assert!(self.native.current.try_write().is_err());
                    let result = action(revision);
                    assert!(self.native.writer.try_lock().is_err());
                    assert!(self.native.current.try_write().is_err());
                    self.visits.fetch_add(1, Ordering::SeqCst);
                    result
                })
        }
    }
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let publication = retired(&repo, "native-locks");
    let native = Arc::new(store(&roots[1], &repo));
    let observed = Arc::new(ObservedNative {
        native: native.clone(),
        visits: AtomicUsize::new(0),
    });
    let owner: Arc<dyn PublicationReferenceAuthority> = observed.clone();
    repo.install_publication_reference_authority(&owner)
        .unwrap();
    commit(&repo, &selection(&repo, &publication)).unwrap();
    hidden(&repo, &publication);
    assert_eq!(observed.visits.load(Ordering::SeqCst), 2);
    assert!(native.writer.try_lock().is_ok());
    assert!(native.current.try_write().is_ok());
}

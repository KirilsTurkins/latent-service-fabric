//! Reclamation estimates use actual files and the actual control writer.
use super::*;
use latent_artifacts::{PublicationReclamationAssessment, PublicationReclamationLimits};

fn inspect(
    repo: &DirectoryArtifactRepository,
    request: &PublicationDeletionRequest,
) -> std::result::Result<PublicationReclamationAssessment, PlatformError> {
    repo.inspect_publication_reclamation(request, PublicationReclamationLimits::default(), TIMEOUT)
}

#[test]
fn native_reclamation_planning_preserves_bytes_charges_and_original_receipts() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let publication = retired(&repo, "plan-one");
    let _catalog = bind(&roots[1], &repo);
    let request = selection(&repo, &publication);
    let receipt = commit(&repo, &request).unwrap().receipt;
    let before = bytes(&roots[0].0);
    let capacity = repo.publication_capacity_snapshot().unwrap();
    let plan = inspect(&repo, &request).unwrap();
    assert_eq!(plan.deletion, request);
    assert_ne!(plan.catalog_fence, request.expected_catalog_fence);
    assert_eq!(plan.content.publications, 1);
    assert_eq!(
        plan.content.publication_file_bytes,
        capacity.storage.publication_file_bytes
    );
    assert_eq!(
        plan.content.last_reference_blob_bytes,
        capacity.storage.shared_blob_bytes
    );
    assert_eq!(
        plan.content.last_reference_blobs,
        capacity.storage.shared_blobs
    );
    assert_eq!(plan.content.shared_blobs_retained, 0);
    assert_eq!(
        plan.content.bytes_hashed,
        plan.content.publication_file_bytes + plan.content.last_reference_blob_bytes
    );
    assert_eq!(inspect(&repo, &request).unwrap(), plan);
    assert_eq!(bytes(&roots[0].0), before);
    assert_eq!(repo.publication_capacity_snapshot().unwrap(), capacity);
    assert_eq!(
        repo.publication_deletion_operation(&request.scope, &request.operation_id)
            .unwrap(),
        PublicationDeletionLookup::Found(receipt)
    );
    hidden(&repo, &publication);
}

#[test]
fn native_reclamation_planning_counts_shared_blobs_once_across_exact_batches() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let one = retired(&repo, "plan-one");
    let two = retired(&repo, "plan-two");
    let _catalog = bind(&roots[1], &repo);
    let request = batch(&repo, &[one.clone(), two.clone()], "plan-both");
    commit(&repo, &request).unwrap();
    let plan = inspect(&repo, &request).unwrap();
    let snapshot = repo.publication_storage_snapshot().unwrap();
    assert_eq!(plan.content.publications, 2);
    assert!(plan.content.publication_files > plan.content.selected_blobs);
    assert_eq!(plan.content.last_reference_blobs, snapshot.shared_blobs);
    assert_eq!(
        plan.content.last_reference_blob_bytes,
        snapshot.shared_blob_bytes
    );
    assert_eq!(plan.content.shared_blobs_retained, 0);
    assert_eq!(
        plan.content.publication_file_bytes,
        snapshot.publication_file_bytes
    );
}

#[test]
fn native_reclamation_planning_preserves_unselected_committed_blob_references() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let one = retired(&repo, "plan-one");
    let two = publish(&repo, "alice", "plan-two");
    let _catalog = bind(&roots[1], &repo);
    let request = selection(&repo, &one);
    commit(&repo, &request).unwrap();
    let plan = inspect(&repo, &request).unwrap();
    assert!(plan.content.shared_blobs_retained > 0);
    assert!(plan.content.shared_blob_bytes_retained > 0);
    assert_eq!(
        plan.content.last_reference_blobs + plan.content.shared_blobs_retained,
        plan.content.selected_blobs
    );
    assert!(repo.publication_execution_eligibility(&two).is_ok());
    // The unselected publication remains a reference even after retirement.
    repo.change_publication_lifecycle(
        context("alice", "retire-second", 1),
        &two,
        ReleaseLifecycleAction::Retire,
        ReleaseLifecycleReason::OperatorRetirement,
        &mut |_| Ok(()),
    )
    .unwrap();
    assert_eq!(inspect(&repo, &request).unwrap().content, plan.content);
}

#[test]
fn native_reclamation_planning_requires_exact_retained_original_deletion() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let one = retired(&repo, "plan-one");
    let _catalog = bind(&roots[1], &repo);
    let request = selection(&repo, &one);
    assert_eq!(
        inspect(&repo, &request).unwrap_err().code,
        PlatformErrorCode::NotFound
    );
    commit(&repo, &request).unwrap();
    let before = bytes(&roots[0].0);
    let mut changed = request.clone();
    changed.actor.subject = "other-actor".into();
    assert_eq!(
        inspect(&repo, &changed).unwrap_err().code,
        PlatformErrorCode::StateConflict
    );
    let mut unknown = request.clone();
    unknown.operation_id = "unknown-deletion".into();
    assert_eq!(
        inspect(&repo, &unknown).unwrap_err().code,
        PlatformErrorCode::NotFound
    );
    assert_eq!(bytes(&roots[0].0), before);
}

#[test]
fn native_reclamation_planning_enforces_exact_file_byte_and_deadline_bounds() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let one = retired(&repo, "plan-one");
    let _catalog = bind(&roots[1], &repo);
    let request = selection(&repo, &one);
    commit(&repo, &request).unwrap();
    let plan = inspect(&repo, &request).unwrap();
    let exact = PublicationReclamationLimits {
        maximum_files: plan.content.publication_files + plan.content.selected_blobs,
        maximum_bytes_hashed: plan.content.bytes_hashed,
    };
    let before = bytes(&roots[0].0);
    assert_eq!(
        repo.inspect_publication_reclamation(&request, exact, TIMEOUT)
            .unwrap(),
        plan
    );
    for limits in [
        PublicationReclamationLimits {
            maximum_files: exact.maximum_files - 1,
            ..exact
        },
        PublicationReclamationLimits {
            maximum_bytes_hashed: exact.maximum_bytes_hashed - 1,
            ..exact
        },
    ] {
        assert_eq!(
            repo.inspect_publication_reclamation(&request, limits, TIMEOUT)
                .unwrap_err()
                .code,
            PlatformErrorCode::ResourceExhausted
        );
    }
    assert_eq!(
        repo.inspect_publication_reclamation(&request, exact, Duration::ZERO)
            .unwrap_err()
            .code,
        PlatformErrorCode::InvalidArgument
    );
    assert_eq!(
        repo.inspect_publication_reclamation(&request, exact, Duration::from_nanos(1))
            .unwrap_err()
            .code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert_eq!(bytes(&roots[0].0), before);
}

#[test]
fn native_reclamation_planning_rejects_corrupt_payload_without_refund() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let one = retired(&repo, "plan-one");
    let _catalog = bind(&roots[1], &repo);
    let request = selection(&repo, &one);
    commit(&repo, &request).unwrap();
    let capacity = repo.publication_capacity_snapshot().unwrap();
    let path = roots[0]
        .0
        .join("publications")
        .join(one.id.hex())
        .join("component.wasm");
    let mut content = fs::read(&path).unwrap();
    content[0] ^= 1;
    fs::write(&path, content).unwrap();
    let before = bytes(&roots[0].0);
    assert_eq!(
        inspect(&repo, &request).unwrap_err().code,
        PlatformErrorCode::CorruptArtifact
    );
    assert_eq!(bytes(&roots[0].0), before);
    assert_eq!(repo.publication_capacity_snapshot().unwrap(), capacity);
}

#[test]
fn native_reclamation_planning_rechecks_preparations_owner_and_reopen() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let one = retired(&repo, "plan-one");
    let catalog = bind(&roots[1], &repo);
    let request = selection(&repo, &one);
    commit(&repo, &request).unwrap();
    let plan = inspect(&repo, &request).unwrap();
    let source = Arc::clone(&repo).owned_preparation_source().unwrap();
    assert_eq!(
        inspect(&repo, &request).unwrap_err().message,
        "publication-deletion-readers-active"
    );
    drop(source);
    drop(catalog);
    assert_eq!(
        inspect(&repo, &request).unwrap_err().message,
        "publication-deletion-reference-authority-unavailable"
    );
    drop(repo);
    let repo = artifacts(&roots[0]);
    assert!(inspect(&repo, &request).is_err());
    let _catalog = bind(&roots[1], &repo);
    assert_eq!(inspect(&repo, &request).unwrap(), plan);
}

#[test]
fn native_reclamation_planning_rejects_foreign_or_changed_batches_before_content_details() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let one = retired(&repo, "plan-one");
    let two = retired(&repo, "plan-two");
    let _catalog = bind(&roots[1], &repo);
    let request = batch(&repo, &[one, two], "plan-batch");
    commit(&repo, &request).unwrap();
    let before = bytes(&roots[0].0);
    let mut foreign = request.clone();
    foreign.scope = LifecycleScope::Tenant(TenantId("bob".into()));
    for target in &mut foreign.targets {
        target.publication.scope = foreign.scope.clone();
    }
    assert_eq!(
        inspect(&repo, &foreign).unwrap_err().code,
        PlatformErrorCode::NotFound
    );
    let mut changed = request.clone();
    changed.targets.pop();
    assert_eq!(
        inspect(&repo, &changed).unwrap_err().code,
        PlatformErrorCode::StateConflict
    );
    let mut stale = request.clone();
    stale.targets[0].expected_generation += 1;
    assert_eq!(
        inspect(&repo, &stale).unwrap_err().code,
        PlatformErrorCode::StateConflict
    );
    assert_eq!(bytes(&roots[0].0), before);
}

#[test]
fn native_reclamation_planning_refuses_evicted_receipts_without_replaying_deletion() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let _catalog = bind(&roots[1], &repo);
    let first = retired(&repo, "plan-first");
    let request = batch(&repo, std::slice::from_ref(&first), "plan-delete-first");
    commit(&repo, &request).unwrap();
    for n in 0..latent_artifacts::MAX_PUBLICATION_DELETION_RECEIPTS {
        let publication = retired(&repo, &format!("plan-{n}"));
        let later = batch(&repo, &[publication], &format!("plan-delete-{n}"));
        commit(&repo, &later).unwrap();
    }
    let before = bytes(&roots[0].0);
    let capacity = repo.publication_capacity_snapshot().unwrap();
    assert_eq!(
        repo.publication_deletion_operation(&request.scope, &request.operation_id)
            .unwrap(),
        PublicationDeletionLookup::Unknown
    );
    assert_eq!(
        inspect(&repo, &request).unwrap_err().message,
        "publication-reclamation-original-operation-unavailable"
    );
    hidden(&repo, &first);
    assert_eq!(bytes(&roots[0].0), before);
    assert_eq!(repo.publication_capacity_snapshot().unwrap(), capacity);
}

#[test]
fn native_reclamation_planning_detects_canonical_blob_corruption_independent_of_links() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let one = retired(&repo, "plan-one");
    let _catalog = bind(&roots[1], &repo);
    let request = selection(&repo, &one);
    commit(&repo, &request).unwrap();
    let path = roots[0]
        .0
        .join("publications")
        .join(one.id.hex())
        .join("component.wasm");
    let original = fs::read(&path).unwrap();
    // Replace only the canonical name, leaving publication hard links intact.
    let blob = roots[0].0.join("blobs").join(&release().0[7..]);
    fs::remove_file(&blob).unwrap();
    let mut changed = original.clone();
    changed[0] ^= 1;
    fs::write(&blob, changed).unwrap();
    assert_eq!(fs::read(path).unwrap(), original);
    let before = bytes(&roots[0].0);
    assert_eq!(
        inspect(&repo, &request).unwrap_err().message,
        "publication-reclamation-blob-changed"
    );
    assert_eq!(bytes(&roots[0].0), before);
}

#[test]
fn native_reclamation_planning_bounds_are_validated_without_filesystem_mutation() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let one = retired(&repo, "plan-one");
    let _catalog = bind(&roots[1], &repo);
    let request = selection(&repo, &one);
    commit(&repo, &request).unwrap();
    let before = bytes(&roots[0].0);
    let defaults = PublicationReclamationLimits::default();
    for limits in [
        PublicationReclamationLimits {
            maximum_files: 0,
            ..defaults
        },
        PublicationReclamationLimits {
            maximum_files: 1025,
            ..defaults
        },
        PublicationReclamationLimits {
            maximum_bytes_hashed: 0,
            ..defaults
        },
        PublicationReclamationLimits {
            maximum_bytes_hashed: u64::MAX,
            ..defaults
        },
    ] {
        assert_eq!(
            repo.inspect_publication_reclamation(&request, limits, TIMEOUT)
                .unwrap_err()
                .code,
            PlatformErrorCode::InvalidArgument
        );
    }
    assert_eq!(bytes(&roots[0].0), before);
}

#[test]
fn native_reclamation_planning_recomputes_after_unrelated_publications_and_control_changes() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let one = retired(&repo, "plan-one");
    let catalog = bind(&roots[1], &repo);
    let request = selection(&repo, &one);
    commit(&repo, &request).unwrap();
    let original = inspect(&repo, &request).unwrap();
    assert_eq!(original.content.shared_blobs_retained, 0);
    let two = publish(&repo, "alice", "plan-later");
    let mut desired = deployment("plan-later", "alice", &release());
    desired.publication = Some(two.id.clone());
    run(catalog.apply(desired)).unwrap();
    let changed = inspect(&repo, &request).unwrap();
    assert_ne!(changed.catalog_fence, original.catalog_fence);
    assert!(changed.reference_revision > original.reference_revision);
    assert!(changed.content.shared_blobs_retained > 0);
    assert!(changed.content.last_reference_blob_bytes < original.content.last_reference_blob_bytes);
    hidden(&repo, &one);
    assert!(repo.publication_execution_eligibility(&two).is_ok());
}

#[test]
fn native_reclamation_planning_holds_actual_reference_writer_through_content_observation() {
    use std::sync::atomic::{AtomicUsize, Ordering};
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
    let one = retired(&repo, "plan-locks");
    let native = Arc::new(store(&roots[1], &repo));
    let observed = Arc::new(ObservedNative {
        native: native.clone(),
        visits: AtomicUsize::new(0),
    });
    let owner: Arc<dyn PublicationReferenceAuthority> = observed.clone();
    repo.install_publication_reference_authority(&owner)
        .unwrap();
    let request = selection(&repo, &one);
    commit(&repo, &request).unwrap();
    assert_eq!(observed.visits.load(Ordering::SeqCst), 2);
    let plan = inspect(&repo, &request).unwrap();
    assert!(plan.content.bytes_hashed > 0);
    assert_eq!(observed.visits.load(Ordering::SeqCst), 3);
    assert!(native.writer.try_lock().is_ok());
    assert!(native.current.try_write().is_ok());
}

#[test]
fn native_reclamation_planning_refuses_changed_selected_file_sets_without_cleanup() {
    for extra in [false, true] {
        let roots = [TempRoot::new(), TempRoot::new()];
        let repo = artifacts(&roots[0]);
        let one = retired(&repo, "plan-files");
        let _catalog = bind(&roots[1], &repo);
        let request = selection(&repo, &one);
        commit(&repo, &request).unwrap();
        let capacity = repo.publication_capacity_snapshot().unwrap();
        let directory = roots[0].0.join("publications").join(one.id.hex());
        if extra {
            fs::write(directory.join("unexpected"), b"extra").unwrap();
        } else {
            fs::remove_file(directory.join("component.wasm")).unwrap();
        }
        let before = bytes(&roots[0].0);
        assert_eq!(
            inspect(&repo, &request).unwrap_err().code,
            PlatformErrorCode::CorruptArtifact
        );
        assert_eq!(bytes(&roots[0].0), before);
        assert_eq!(repo.publication_capacity_snapshot().unwrap(), capacity);
    }
}

//! Real native web files and control owners; admission fixture is noncryptographic.
use super::*;
use latent_artifacts::{
    PublicationReclamationLimits, PublicationReclamationLookup, PublicationReclamationRequest,
    PublicationReclamationResult, ReleaseEvidenceUpload,
};
use std::{
    fs,
    path::{Path, PathBuf},
};

fn bound(root: &TempRoot, repo: &Arc<DirectoryArtifactRepository>) -> Arc<Store> {
    let store = Arc::new(catalog(root, repo));
    store.bind_publication_reference_authority(repo).unwrap();
    store
}
fn cleanup_request(
    repo: &DirectoryArtifactRepository,
    deletion: PublicationDeletionRequest,
) -> PublicationReclamationRequest {
    let observation = repo
        .inspect_publication_reclamation(
            &deletion,
            PublicationReclamationLimits::default(),
            TIMEOUT,
        )
        .unwrap();
    PublicationReclamationRequest {
        deletion,
        expected_catalog_fence: observation.catalog_fence,
        limits: PublicationReclamationLimits::default(),
    }
}
fn deleted_web(
    repo: &DirectoryArtifactRepository,
    publication: &PublicationRef,
) -> PublicationReclamationRequest {
    revoke(repo, publication);
    let deletion = selection(repo, publication);
    repo.tombstone_publications(&deletion, TIMEOUT, &mut |_| Ok(()))
        .unwrap();
    cleanup_request(repo, deletion)
}
fn reclaim(
    repo: &DirectoryArtifactRepository,
    request: &PublicationReclamationRequest,
) -> Result<PublicationReclamationResult, PlatformError> {
    repo.reclaim_tombstoned_publications(request, TIMEOUT, &mut |_| Ok(()))
}
fn payload(root: &TempRoot, publication: &PublicationRef) -> PathBuf {
    root.0.join("web/publications").join(publication.id.hex())
}
fn bytes(root: &Path) -> BTreeMap<PathBuf, Vec<u8>> {
    fn walk(root: &Path, path: &Path, out: &mut BTreeMap<PathBuf, Vec<u8>>) {
        for entry in fs::read_dir(path).unwrap() {
            let entry = entry.unwrap();
            if entry.file_type().unwrap().is_dir() {
                walk(root, &entry.path(), out);
            } else {
                assert!(out.len() < 10_000);
                out.insert(
                    entry.path().strip_prefix(root).unwrap().to_path_buf(),
                    fs::read(entry.path()).unwrap(),
                );
            }
        }
    }
    let mut out = BTreeMap::new();
    walk(root, root, &mut out);
    out
}
fn copy_tree(source: &Path, target: &Path) {
    fs::create_dir_all(target).unwrap();
    for entry in fs::read_dir(source).unwrap() {
        let entry = entry.unwrap();
        let next = target.join(entry.file_name());
        if entry.file_type().unwrap().is_dir() {
            copy_tree(&entry.path(), &next);
        } else {
            fs::copy(entry.path(), next).unwrap();
        }
    }
}
fn try_open(root: &TempRoot) -> Result<DirectoryArtifactRepository, PlatformError> {
    DirectoryArtifactRepository::open_enforced(
        &root.0,
        DirectoryArtifactRepositoryConfig::default(),
        AdmissionStorageLimits::default(),
        Arc::new(StaticWebHost),
    )
}
fn hidden(repo: &DirectoryArtifactRepository, publication: &PublicationRef) {
    assert_eq!(
        repo.web_publication_status(publication).unwrap_err().code,
        PlatformErrorCode::NotFound
    );
    assert!(repo.select_web_publication(publication).is_err());
    assert!(repo.read_web_asset(publication, "/index.html").is_err());
}

fn variant(repo: &DirectoryArtifactRepository, index: usize) -> PublicationRef {
    let mut upload = static_web_upload();
    let mut manifest: json::Value = json::from_slice(&upload.manifest).unwrap();
    manifest["annotations"]["org.opencontainers.image.revision"] =
        json::json!(format!("variant-{index}"));
    upload.manifest = json::to_vec(&manifest).unwrap();
    let reference = repo
        .publish_web_package(
            publication_context("alice", &format!("web-{index}"), 0),
            upload,
            &mut |_| Ok(()),
        )
        .unwrap()
        .receipt
        .publication;
    repo.transition_web_publication(
        publication_context("alice", &format!("revoke-{index}"), 1),
        &reference,
        ReleaseLifecycleAction::Revoke,
        ReleaseLifecycleReason::OperatorRevocation,
        &mut |_| Ok(()),
    )
    .unwrap();
    reference
}
fn delete_batch(
    repo: &DirectoryArtifactRepository,
    references: &[PublicationRef],
    operation: &str,
) -> PublicationReclamationRequest {
    let snapshot = repo
        .publication_retention_snapshot(&references[0].scope, references, TIMEOUT)
        .unwrap();
    let deletion = PublicationDeletionRequest {
        scope: references[0].scope.clone(),
        actor: actor(),
        operation_id: operation.into(),
        expected_catalog_fence: snapshot.catalog_fence,
        targets: snapshot.selections.into_iter().map(|s| s.target).collect(),
    };
    repo.tombstone_publications(&deletion, TIMEOUT, &mut |_| Ok(()))
        .unwrap();
    cleanup_request(repo, deletion)
}

mod recovery;

#[test]
fn native_web_cleanup_refunds_payload_slots_and_survives_receipt_replay_and_restart() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = static_repo(&roots[0]);
    let publication = publish_static(&repo, "alice");
    let store = bound(&roots[1], &repo);
    let request = deleted_web(&repo, &publication);
    let before = repo.publication_capacity_snapshot().unwrap();
    let result = reclaim(&repo, &request).unwrap();
    assert!(!result.replay);
    assert_eq!(result.receipt.request, request);
    assert_eq!(
        result.receipt.content.publication_file_bytes,
        before.storage.publication_file_bytes
    );
    assert!(!payload(&roots[0], &publication).exists());
    let after = repo.publication_capacity_snapshot().unwrap();
    assert_eq!(after.storage.publication_file_bytes, 0);
    assert_eq!(after.storage.shared_blob_bytes, 0);
    assert_eq!(after.storage.retained_publications, 0);
    assert_eq!(after.indexed_publications, 0);
    assert_eq!(after.release_directories, 0);
    assert!(after.storage.retention_control_bytes > 0);
    assert!(after.storage.web_control_bytes > 0);
    hidden(&repo, &publication);
    let stable = bytes(&roots[0].0);
    assert!(reclaim(&repo, &request).unwrap().replay);
    assert_eq!(publish_static(&repo, "alice"), publication);
    assert!(repo
        .publish_web_package(
            publication_context("alice", "new-publish-id", 0),
            static_web_upload(),
            &mut |_| Ok(())
        )
        .is_err());
    assert_eq!(bytes(&roots[0].0), stable);
    drop(store);
    drop(repo);
    let repo = static_repo(&roots[0]);
    let _store = bound(&roots[1], &repo);
    assert_eq!(repo.publication_capacity_snapshot().unwrap(), after);
    hidden(&repo, &publication);
    assert!(reclaim(&repo, &request).unwrap().replay);
    assert_eq!(
        repo.publication_reclamation_operation(
            &request.deletion.scope,
            &request.deletion.operation_id
        )
        .unwrap(),
        PublicationReclamationLookup::Found(result.receipt)
    );
    assert_eq!(bytes(&roots[0].0), stable);
}

#[test]
fn native_web_cleanup_preserves_other_tenant_shared_blobs_and_later_web_commits() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = static_repo(&roots[0]);
    let one = publish_static(&repo, "alice");
    let two = publish_static(&repo, "bob");
    let store = bound(&roots[1], &repo);
    let first = deleted_web(&repo, &one);
    let result = reclaim(&repo, &first).unwrap();
    assert!(result.receipt.content.shared_blobs_retained > 0);
    assert!(repo.read_web_asset(&two, "/index.html").is_ok());
    let second = deleted_web(&repo, &two);
    let before = repo.publication_capacity_snapshot().unwrap();
    drop(store);
    drop(repo);
    let repo = static_repo(&roots[0]);
    let _store = bound(&roots[1], &repo);
    // Recovered terminal grants can carry a different transient metadata charge.
    // Durable namespaces and payload slots, unlike that cache, must be identical.
    let reopened = repo.publication_capacity_snapshot().unwrap();
    assert_eq!(reopened.storage, before.storage);
    assert_eq!(reopened.indexed_publications, before.indexed_publications);
    assert_eq!(reopened.release_directories, before.release_directories);
    hidden(&repo, &one);
    hidden(&repo, &two);
    let result = reclaim(&repo, &second).unwrap();
    assert!(result.receipt.content.last_reference_blobs > 0);
    assert_eq!(repo.publication_storage_snapshot().unwrap().shared_blobs, 0);
    assert_eq!(
        repo.publication_capacity_snapshot()
            .unwrap()
            .indexed_publications,
        0
    );
    assert!(reclaim(&repo, &first).unwrap().replay);
}

#[test]
fn native_web_cleanup_preflight_rejection_and_exact_work_bounds_preserve_bytes() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = static_repo(&roots[0]);
    let publication = publish_static(&repo, "alice");
    let _store = bound(&roots[1], &repo);
    let mut request = deleted_web(&repo, &publication);
    let observation = repo
        .inspect_publication_reclamation(&request.deletion, request.limits, TIMEOUT)
        .unwrap();
    let before = bytes(&roots[0].0);
    let capacity = repo.publication_capacity_snapshot().unwrap();
    assert!(repo
        .reclaim_tombstoned_publications(&request, TIMEOUT, &mut |_| Err(static_web_denied(
            "audit-full"
        )))
        .is_err());
    request.limits.maximum_files =
        2 * (observation.content.publication_files + observation.content.selected_blobs);
    request.limits.maximum_bytes_hashed = 2 * observation.content.bytes_hashed;
    for files in [true, false] {
        let mut short = request.clone();
        if files {
            short.limits.maximum_files -= 1;
        } else {
            short.limits.maximum_bytes_hashed -= 1;
        }
        assert_eq!(
            repo.reclaim_tombstoned_publications(&short, TIMEOUT, &mut |_| panic!(
                "over work budget"
            ))
            .unwrap_err()
            .code,
            PlatformErrorCode::ResourceExhausted
        );
    }
    assert_eq!(bytes(&roots[0].0), before);
    assert_eq!(repo.publication_capacity_snapshot().unwrap(), capacity);
    assert_eq!(
        reclaim(&repo, &request).unwrap().receipt.content,
        observation.content
    );
}

#[test]
fn native_web_cleanup_rechecks_preparation_ownership_and_unrelated_publication_changes() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = static_repo(&roots[0]);
    let publication = publish_static(&repo, "alice");
    let store = bound(&roots[1], &repo);
    let request = deleted_web(&repo, &publication);
    let before = bytes(&roots[0].0);
    let mut held = None;
    assert!(repo
        .reclaim_tombstoned_publications(&request, TIMEOUT, &mut |_| {
            held = Some(repo.clone().owned_preparation_source().unwrap());
            Ok(())
        })
        .is_err());
    let cloned = held.as_ref().unwrap().clone();
    drop(held);
    assert!(reclaim(&repo, &request).is_err());
    drop(cloned);
    assert_eq!(bytes(&roots[0].0), before);
    assert_eq!(
        repo.reclaim_tombstoned_publications(&request, TIMEOUT, &mut |_| {
            publish_static(&repo, "bob");
            Ok(())
        })
        .unwrap_err()
        .code,
        PlatformErrorCode::StateConflict
    );
    assert!(payload(&roots[0], &publication).exists());
    let fresh = cleanup_request(&repo, request.deletion);
    drop(store);
    assert!(reclaim(&repo, &fresh).is_err());
    assert!(payload(&roots[0], &publication).exists());
}

#[test]
fn native_web_cleanup_exact_multi_publication_batch_releases_shared_blobs_once() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = static_repo(&roots[0]);
    let store = bound(&roots[1], &repo);
    let mut references: Vec<_> = (0..8).map(|i| variant(&repo, i)).collect();
    references.sort_by(|a, b| a.id.cmp(&b.id));
    let request = delete_batch(&repo, &references, "web-batch");
    let before = repo.publication_storage_snapshot().unwrap();
    let result = reclaim(&repo, &request).unwrap();
    assert_eq!(result.receipt.content.publications, 8);
    assert_eq!(
        result.receipt.content.last_reference_blob_bytes,
        before.shared_blob_bytes
    );
    assert_eq!(
        result.receipt.content.publication_file_bytes,
        before.publication_file_bytes
    );
    assert_eq!(
        repo.publication_capacity_snapshot()
            .unwrap()
            .indexed_publications,
        0
    );
    drop(store);
    drop(repo);
    let repo = static_repo(&roots[0]);
    let _store = bound(&roots[1], &repo);
    assert!(reclaim(&repo, &request).unwrap().replay);
    for reference in &references {
        hidden(&repo, reference);
    }
    assert_eq!(
        repo.publication_storage_snapshot()
            .unwrap()
            .retained_publications,
        0
    );
}

#[test]
fn native_web_cleanup_evicted_receipt_is_unknown_without_resurrection_authority() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = static_repo(&roots[0]);
    let store = bound(&roots[1], &repo);
    let mut first = None;
    for i in 0..65 {
        let publication = variant(&repo, i);
        let request = delete_batch(
            &repo,
            std::slice::from_ref(&publication),
            &format!("cleanup-{i}"),
        );
        reclaim(&repo, &request).unwrap();
        if first.is_none() {
            first = Some((publication, request));
        }
    }
    let (publication, request) = first.unwrap();
    let before = bytes(&roots[0].0);
    assert_eq!(
        repo.publication_reclamation_operation(
            &request.deletion.scope,
            &request.deletion.operation_id
        )
        .unwrap(),
        PublicationReclamationLookup::Unknown
    );
    assert!(repo
        .reclaim_tombstoned_publications(&request, TIMEOUT, &mut |_| panic!(
            "evicted operation cannot authorize cleanup"
        ))
        .is_err());
    assert_eq!(bytes(&roots[0].0), before);
    hidden(&repo, &publication);
    drop(store);
    drop(repo);
    let repo = static_repo(&roots[0]);
    hidden(&repo, &publication);
    assert_eq!(
        repo.publication_reclamation_operation(
            &request.deletion.scope,
            &request.deletion.operation_id
        )
        .unwrap(),
        PublicationReclamationLookup::Unknown
    );
    assert_eq!(
        repo.publication_capacity_snapshot()
            .unwrap()
            .release_directories,
        0
    );
}

#[test]
fn native_web_cleanup_near_budget_refuses_before_preflight_without_refund() {
    for metadata in [true, false] {
        let roots = [TempRoot::new(), TempRoot::new()];
        let repo = static_repo(&roots[0]);
        let publication = publish_static(&repo, "alice");
        let store = bound(&roots[1], &repo);
        let request = deleted_web(&repo, &publication);
        let used = repo.publication_capacity_snapshot().unwrap();
        drop(store);
        drop(repo);
        let mut config = DirectoryArtifactRepositoryConfig::default();
        if metadata {
            config.max_index_bytes = used.index_bytes + 1024;
        } else {
            config.max_storage_bytes = used.charged_storage_bytes + 1024;
        }
        let repo = Arc::new(
            DirectoryArtifactRepository::open_enforced(
                &roots[0].0,
                config,
                AdmissionStorageLimits::default(),
                Arc::new(StaticWebHost),
            )
            .unwrap(),
        );
        let _store = bound(&roots[1], &repo);
        let request = cleanup_request(&repo, request.deletion);
        let before = bytes(&roots[0].0);
        let used = repo.publication_capacity_snapshot().unwrap();
        assert_eq!(
            repo.reclaim_tombstoned_publications(&request, TIMEOUT, &mut |_| panic!(
                "cleanup exposure not admitted"
            ))
            .unwrap_err()
            .code,
            PlatformErrorCode::ResourceExhausted
        );
        assert_eq!(bytes(&roots[0].0), before);
        assert_eq!(repo.publication_capacity_snapshot().unwrap(), used);
    }
}

#[test]
fn native_web_cleanup_rejects_foreign_changed_unknown_and_oversized_requests() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = static_repo(&roots[0]);
    let publication = publish_static(&repo, "alice");
    let _store = bound(&roots[1], &repo);
    let request = deleted_web(&repo, &publication);
    let mut foreign = request.clone();
    foreign.deletion.scope = LifecycleScope::Tenant(TenantId("bob".into()));
    foreign.deletion.targets[0].publication.scope = foreign.deletion.scope.clone();
    let mut changed = request.clone();
    changed.deletion.targets[0].expected_generation += 1;
    let mut unknown = request.clone();
    unknown.deletion.operation_id = "unknown-operation".into();
    let mut too_many = request.clone();
    too_many.deletion.targets = vec![request.deletion.targets[0].clone(); 33];
    let before = bytes(&roots[0].0);
    for rejected in [foreign, changed, unknown, too_many] {
        assert!(repo
            .reclaim_tombstoned_publications(&rejected, TIMEOUT, &mut |_| panic!(
                "request must be refused before preflight"
            ))
            .is_err());
        assert_eq!(bytes(&roots[0].0), before);
    }
    assert!(repo
        .reclaim_tombstoned_publications(&request, Duration::ZERO, &mut |_| panic!(
            "expired request"
        ))
        .is_err());
    assert_eq!(bytes(&roots[0].0), before);
    reclaim(&repo, &request).unwrap();
    assert!(repo
        .reclaim_tombstoned_capsules(&request, TIMEOUT, &mut |_| panic!(
            "capsule-only replay of web receipt"
        ))
        .is_err());
}

#[test]
fn native_web_cleanup_finite_release_sequence_refunds_payload_not_independent_history() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = static_repo(&roots[0]);
    let store = bound(&roots[1], &repo);
    let mut previous_control = 0;
    for i in 0..3 {
        let publication = variant(&repo, i);
        let request = delete_batch(
            &repo,
            std::slice::from_ref(&publication),
            &format!("sequence-{i}"),
        );
        let before = repo.publication_storage_snapshot().unwrap();
        let result = reclaim(&repo, &request).unwrap();
        let after = repo.publication_storage_snapshot().unwrap();
        assert_eq!(
            before.publication_file_bytes,
            result.receipt.content.publication_file_bytes
        );
        assert_eq!(
            before.shared_blob_bytes,
            result.receipt.content.last_reference_blob_bytes
        );
        assert_eq!(after.publication_file_bytes, 0);
        assert_eq!(after.shared_blob_bytes, 0);
        assert!(after.retention_control_bytes >= previous_control);
        previous_control = after.retention_control_bytes;
        assert!(roots[0].0.join("web/HEAD").is_file());
        hidden(&repo, &publication);
        println!("web-release-sequence {} publication-file-bytes={} canonical-blob-bytes={} retained-control-bytes={}",
                 i + 1, result.receipt.content.publication_file_bytes,
                 result.receipt.content.last_reference_blob_bytes, after.retention_control_bytes);
    }
    let final_capacity = repo.publication_capacity_snapshot().unwrap();
    drop(store);
    drop(repo);
    let repo = static_repo(&roots[0]);
    let _store = bound(&roots[1], &repo);
    assert_eq!(
        repo.publication_capacity_snapshot().unwrap(),
        final_capacity
    );
}

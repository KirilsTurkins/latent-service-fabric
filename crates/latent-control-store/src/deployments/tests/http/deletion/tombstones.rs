//! Componentless web visibility and native HTTP references, not a signing model.
use super::*;
use latent_artifacts::{
    DevelopmentRetentionFault, PublicationContentReclamation, PublicationDeletionLookup,
};
const TIMEOUT: Duration = Duration::from_secs(10);
fn revoke(repo: &DirectoryArtifactRepository, publication: &PublicationRef) {
    repo.transition_web_publication(
        publication_context(publication.scope.tenant().unwrap().0.as_str(), "revoke", 1),
        publication,
        ReleaseLifecycleAction::Revoke,
        ReleaseLifecycleReason::OperatorRevocation,
        &mut |_| Ok(()),
    )
    .unwrap();
}
#[test]
fn native_web_tombstone_holds_last_reader_and_http_reference_then_survives_other_web_commits() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = static_repo(&roots[0]);
    let publication = publish_static(&repo, "alice");
    let unrelated = publish_static(&repo, "bob");
    let held = repo.select_web_publication(&publication).unwrap();
    let cloned = held.eligibility().clone();
    let store = Arc::new(catalog(&roots[1], &repo));
    store.bind_publication_reference_authority(&repo).unwrap();
    execute(
        &store,
        request(
            &store,
            "apply",
            static_definition("alice", "site", &publication, "/", "prefix"),
            0,
        ),
    );
    revoke(&repo, &publication);
    let deletion = selection(&repo, &publication);
    assert_eq!(
        repo.tombstone_publications(&deletion, TIMEOUT, &mut |_| Ok(()))
            .unwrap_err()
            .message,
        "publication-deletion-readers-active"
    );
    drop(held);
    assert!(repo
        .tombstone_publications(&deletion, TIMEOUT, &mut |_| Ok(()))
        .is_err());
    drop(cloned);
    assert_eq!(
        repo.tombstone_publications(&deletion, TIMEOUT, &mut |_| Ok(()))
            .unwrap_err()
            .message,
        "publication-deletion-referenced"
    );
    delete(&store, "remove-route", "alice", "site", 1);
    let before = repo.publication_storage_snapshot().unwrap();
    let result = repo
        .tombstone_publications(&deletion, TIMEOUT, &mut |_| Ok(()))
        .unwrap();
    assert_eq!(
        repo.web_publication_status(&publication).unwrap_err().code,
        PlatformErrorCode::NotFound
    );
    assert_eq!(
        repo.select_web_publication(&publication)
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::NotFound
    );
    assert_eq!(publish_static(&repo, "alice"), publication); // exact original receipt, not re-admission
    assert_eq!(
        repo.web_publication_status(&publication).unwrap_err().code,
        PlatformErrorCode::NotFound
    );
    assert!(repo.select_web_publication(&unrelated).is_ok());
    revoke(&repo, &unrelated); // persists the entire web catalog after the tombstone
    let after = repo.publication_storage_snapshot().unwrap();
    assert_eq!(before.shared_blob_bytes, after.shared_blob_bytes);
    assert_eq!(before.publication_file_bytes, after.publication_file_bytes);
    assert_eq!(before.retained_publications, after.retained_publications);
    assert_eq!(
        repo.reclaim_uncommitted_content(32).unwrap(),
        PublicationContentReclamation::default()
    );
    drop(store);
    drop(repo);
    let repo = static_repo(&roots[0]);
    let store = Arc::new(catalog(&roots[1], &repo));
    store.bind_publication_reference_authority(&repo).unwrap();
    assert_eq!(
        repo.web_publication_status(&publication).unwrap_err().code,
        PlatformErrorCode::NotFound
    );
    assert_eq!(
        repo.publication_deletion_operation(&deletion.scope, &deletion.operation_id)
            .unwrap(),
        PublicationDeletionLookup::Found(result.receipt)
    );
    assert!(
        repo.tombstone_publications(&deletion, TIMEOUT, &mut |_| Ok(()))
            .unwrap()
            .replay
    );
    assert_eq!(publish_static(&repo, "alice"), publication);
    assert!(repo.select_web_publication(&publication).is_err());
}
#[test]
fn native_web_tombstone_intent_reopen_recovers_without_a_fresh_mutation() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = static_repo(&roots[0]);
    let publication = publish_static(&repo, "alice");
    revoke(&repo, &publication);
    let store = Arc::new(catalog(&roots[1], &repo));
    store.bind_publication_reference_authority(&repo).unwrap();
    let deletion = selection(&repo, &publication);
    repo.inject_retention_fault_for_test(DevelopmentRetentionFault::AfterIntent);
    assert!(repo
        .tombstone_publications(&deletion, TIMEOUT, &mut |_| Ok(()))
        .is_err());
    assert_eq!(
        repo.publication_deletion_operation(&deletion.scope, &deletion.operation_id)
            .unwrap(),
        PublicationDeletionLookup::Uncertain
    );
    drop(store);
    drop(repo);
    let repo = static_repo(&roots[0]);
    assert_eq!(
        repo.web_publication_status(&publication).unwrap_err().code,
        PlatformErrorCode::NotFound
    );
    assert!(matches!(
        repo.publication_deletion_operation(&deletion.scope, &deletion.operation_id)
            .unwrap(),
        PublicationDeletionLookup::Found(_)
    ));
    assert!(!roots[0].0.join("lifecycle/retention/INTENT").exists());
}

#[test]
fn native_web_reclamation_planning_retains_shared_content_and_survives_reopen() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = static_repo(&roots[0]);
    let publication = publish_static(&repo, "alice");
    let unrelated = publish_static(&repo, "bob");
    let store = Arc::new(catalog(&roots[1], &repo));
    store.bind_publication_reference_authority(&repo).unwrap();
    revoke(&repo, &publication);
    let request = selection(&repo, &publication);
    repo.tombstone_publications(&request, TIMEOUT, &mut |_| Ok(()))
        .unwrap();
    let before = repo.publication_capacity_snapshot().unwrap();
    let limits = latent_artifacts::PublicationReclamationLimits::default();
    let plan = repo
        .inspect_publication_reclamation(&request, limits, TIMEOUT)
        .unwrap();
    assert_eq!(plan.content.publications, 1);
    assert!(plan.content.publication_files > 0);
    assert!(plan.content.shared_blobs_retained > 0);
    assert_eq!(repo.publication_capacity_snapshot().unwrap(), before);
    // An unrelated serving read may lazily build a charged renderer projection.
    // That cache activity is outside the read-only reclamation assessment.
    assert!(repo.select_web_publication(&unrelated).is_ok());
    assert!(repo.select_web_publication(&publication).is_err());
    drop(store);
    drop(repo);
    let repo = static_repo(&roots[0]);
    let store = Arc::new(catalog(&roots[1], &repo));
    store.bind_publication_reference_authority(&repo).unwrap();
    let reopened = repo.publication_capacity_snapshot().unwrap();
    assert_eq!(
        repo.inspect_publication_reclamation(&request, limits, TIMEOUT)
            .unwrap(),
        plan
    );
    assert_eq!(repo.publication_capacity_snapshot().unwrap(), reopened);
    assert_eq!(reopened.storage, before.storage);
}

#[test]
fn native_web_physical_reclamation_refuses_before_preflight_and_preserves_all_bytes() {
    use latent_artifacts::{PublicationReclamationLimits, PublicationReclamationRequest};
    fn files(root: &std::path::Path) -> std::collections::BTreeMap<std::path::PathBuf, Vec<u8>> {
        let mut all = std::collections::BTreeMap::new();
        let mut pending = vec![root.to_path_buf()];
        while let Some(path) = pending.pop() {
            for entry in std::fs::read_dir(path).unwrap() {
                let entry = entry.unwrap();
                if entry.file_type().unwrap().is_dir() {
                    pending.push(entry.path());
                } else {
                    assert!(all.len() < 1000);
                    all.insert(
                        entry.path().strip_prefix(root).unwrap().to_path_buf(),
                        std::fs::read(entry.path()).unwrap(),
                    );
                }
            }
        }
        all
    }
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = static_repo(&roots[0]);
    let one = publish_static(&repo, "alice");
    let store = Arc::new(catalog(&roots[1], &repo));
    store.bind_publication_reference_authority(&repo).unwrap();
    revoke(&repo, &one);
    let deletion = selection(&repo, &one);
    repo.tombstone_publications(&deletion, TIMEOUT, &mut |_| Ok(()))
        .unwrap();
    let limits = PublicationReclamationLimits::default();
    let plan = repo
        .inspect_publication_reclamation(&deletion, limits, TIMEOUT)
        .unwrap();
    let before = files(&roots[0].0);
    let capacity = repo.publication_capacity_snapshot().unwrap();
    let request = PublicationReclamationRequest {
        deletion,
        expected_catalog_fence: plan.catalog_fence,
        limits,
    };
    assert_eq!(
        repo.reclaim_tombstoned_capsules(&request, TIMEOUT, &mut |_| panic!(
            "web cleanup has not been qualified"
        ))
        .unwrap_err()
        .message,
        "publication-reclamation-capsule-target-required"
    );
    assert_eq!(before, files(&roots[0].0));
    assert_eq!(capacity, repo.publication_capacity_snapshot().unwrap());
}

mod web_cleanup;

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

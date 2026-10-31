//! Real componentless publication and persisted HTTP trigger reference ownership.
use super::*;
use latent_artifacts::PublicationDeletionRequest;
use std::time::Duration;

fn selection(
    repo: &DirectoryArtifactRepository,
    publication: &PublicationRef,
) -> PublicationDeletionRequest {
    let selected = repo
        .publication_retention_snapshot(
            &publication.scope,
            std::slice::from_ref(publication),
            Duration::from_secs(10),
        )
        .unwrap();
    PublicationDeletionRequest {
        scope: publication.scope.clone(),
        actor: actor(),
        operation_id: "delete-original".into(),
        expected_catalog_fence: selected.catalog_fence,
        targets: selected
            .selections
            .into_iter()
            .map(|value| value.target)
            .collect(),
    }
}
#[test]
fn native_static_http_reference_blocks_deletion_after_revocation_and_reopen() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = static_repo(&roots[0]);
    let publication = publish_static(&repo, "alice");
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
    repo.transition_web_publication(
        publication_context("alice", "revoke", 1),
        &publication,
        ReleaseLifecycleAction::Revoke,
        ReleaseLifecycleReason::OperatorRevocation,
        &mut |_| Ok(()),
    )
    .unwrap();
    let request = selection(&repo, &publication);
    assert_eq!(
        repo.inspect_publication_deletion(&request, Duration::from_secs(10))
            .unwrap_err()
            .message,
        "publication-deletion-referenced"
    );
    drop(store);
    drop(repo);
    let repo = static_repo(&roots[0]);
    let store = Arc::new(catalog(&roots[1], &repo));
    store.bind_publication_reference_authority(&repo).unwrap();
    let request = selection(&repo, &publication);
    assert_eq!(
        repo.inspect_publication_deletion(&request, Duration::from_secs(10))
            .unwrap_err()
            .message,
        "publication-deletion-referenced"
    );
    delete(&store, "remove-route", "alice", "site", 1);
    assert!(repo
        .inspect_publication_deletion(&request, Duration::from_secs(10))
        .is_ok());
    assert!(repo.select_web_publication(&publication).is_err());
}

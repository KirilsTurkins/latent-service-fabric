//! Native reads share the deletion exclusion; these are not storage models.
use super::super::integrity::faults::AfterMetadataScanGuard;
use super::*;
use crate::{
    PublicationDeletionRequest, ReleaseActor, ReleaseActorKind, ReleaseLifecycleAction,
    ReleaseLifecycleReason, ReleaseMutationContext, ReleaseOperationPrecondition,
};

fn revoked(
    root: &TempRoot,
) -> (
    Arc<DirectoryArtifactRepository>,
    ReleaseDigest,
    crate::PublicationRef,
) {
    let repo = Arc::new(repository(root.path()));
    let digest = block_on(repo.publish(artifact("read-guard", b"native bytes")))
        .unwrap()
        .release_digest;
    let publication = repo
        .select_execution_publication(&latent_core::TenantId("examples".into()), &digest, None)
        .unwrap();
    repo.change_publication_lifecycle(
        ReleaseMutationContext {
            scope: publication.scope.clone(),
            actor: ReleaseActor {
                subject: "native-reader-test".into(),
                kind: ReleaseActorKind::Host,
            },
            operation: Some(ReleaseOperationPrecondition {
                operation_id: "revoke".into(),
                expected_generation: 1,
            }),
        },
        &publication,
        ReleaseLifecycleAction::Revoke,
        ReleaseLifecycleReason::OperatorRevocation,
        &mut |_| Ok(()),
    )
    .unwrap();
    (repo, digest, publication)
}
fn selection(
    repo: &DirectoryArtifactRepository,
    publication: &crate::PublicationRef,
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
        actor: ReleaseActor {
            subject: "native-reader-test".into(),
            kind: ReleaseActorKind::Host,
        },
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
fn physical_metadata_read_excludes_deletion_until_native_scan_retires() {
    let root = TempRoot::new();
    let (repo, digest, publication) = revoked(&root);
    let request = selection(&repo, &publication);
    let worker_repo = repo.clone();
    let worker_id = publication.id.clone();
    let (ready, waiting) = std::sync::mpsc::sync_channel(1);
    let (resume, resumed) = std::sync::mpsc::sync_channel(1);
    let worker = thread::spawn(move || {
        let _hook = AfterMetadataScanGuard::new(move |_| {
            ready.send(()).unwrap();
            resumed.recv_timeout(Duration::from_secs(10)).unwrap();
        });
        worker_repo
            .selected_historical_snapshot(&digest, Some(&worker_id))
            .unwrap();
    });
    waiting.recv_timeout(Duration::from_secs(10)).unwrap();
    assert_eq!(
        repo.inspect_publication_deletion(&request, Duration::from_secs(10))
            .unwrap_err()
            .message,
        "publication-deletion-readers-active"
    );
    resume.send(()).unwrap();
    worker.join().unwrap();
    // No reference owner is installed in this artifact-only test. Reaching that
    // later refusal proves the actual physical read exclusion has retired.
    assert_eq!(
        repo.inspect_publication_deletion(&request, Duration::from_secs(10))
            .unwrap_err()
            .message,
        "publication-deletion-reference-authority-unavailable"
    );
}
#[test]
fn exclusive_deletion_gate_refuses_new_native_reads_and_preparation_sources() {
    let root = TempRoot::new();
    let (repo, digest, publication) = revoked(&root);
    let exclusion = repo.read_owners.exclusive().unwrap();
    assert!(repo.clone().owned_preparation_source().is_none());
    assert!(repo.preparation_source().is_none());
    let error = repo
        .selected_historical_snapshot(&digest, Some(&publication.id))
        .err()
        .unwrap();
    assert_eq!(error.message, "publication-deletion-readers-active");
    drop(exclusion);
    assert!(repo.preparation_source().is_some());
    repo.selected_historical_snapshot(&digest, Some(&publication.id))
        .unwrap();
}

use super::lifecycle::{accept, context};
use super::*;
use crate::{ManagedPublicationUpload, ReleaseLifecycleAction, ReleaseLifecycleReason};

#[test]
fn capacity_observes_retained_history_shared_links_and_near_budget_rejection() {
    let root = TempRoot::new();
    let config = DirectoryArtifactRepositoryConfig {
        max_index_entries: 3,
        ..Default::default()
    };
    let repo = Arc::new(DirectoryArtifactRepository::open(root.path(), config).unwrap());
    let mut receipts = Vec::new();
    let mut observations = Vec::new();
    for index in 0..3 {
        let value = artifact(&format!("revision-{index}"), b"shared immutable component");
        let receipt = block_on(repo.publish_managed(
            context(&format!("publish-{index}"), 0),
            ManagedPublicationUpload::Local(value),
            &mut accept,
        ))
        .unwrap();
        receipts.push(receipt);
        observations.push(repo.publication_capacity_snapshot().unwrap());
    }
    let before = observations[2];
    assert_eq!(before.indexed_publications, 3);
    assert_eq!(before.release_directories, 3);
    assert!(observations
        .windows(2)
        .all(|pair| pair[1].charged_storage_bytes > pair[0].charged_storage_bytes));
    assert!(before.storage.publication_file_bytes > before.storage.shared_blob_bytes);
    let pin = repo.clone().owned_preparation_source().unwrap();
    let rollback = repo
        .publication_execution_eligibility(&receipts[0].publication)
        .unwrap();
    repo.change_publication_lifecycle(
        context("retire-last", 1),
        &receipts[2].publication,
        ReleaseLifecycleAction::Retire,
        ReleaseLifecycleReason::OperatorRetirement,
        &mut accept,
    )
    .unwrap();
    assert_eq!(
        repo.publication_capacity_snapshot().unwrap().storage,
        before.storage
    );
    assert_eq!(
        repo.reclaim_uncommitted_content(32).unwrap(),
        crate::PublicationContentReclamation::default()
    );
    assert_eq!(
        block_on(repo.publish(artifact("overflow", b"different")))
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    rollback.check_current().unwrap();
    assert_eq!(
        repo.fetch_publication(&receipts[0].publication)
            .unwrap()
            .component_bytes,
        b"shared immutable component"
    );
    drop(rollback);
    drop(pin);
    drop(repo);
    let reopened = DirectoryArtifactRepository::open(root.path(), config).unwrap();
    assert_eq!(
        reopened.publication_capacity_snapshot().unwrap().storage,
        before.storage
    );
    assert_eq!(
        reopened
            .publication_capacity_snapshot()
            .unwrap()
            .indexed_publications,
        3
    );
    assert!(reopened
        .publication_execution_eligibility(&receipts[2].publication)
        .and_then(|eligibility| eligibility.check_current())
        .is_err());
    reopened
        .publication_execution_eligibility(&receipts[0].publication)
        .unwrap()
        .check_current()
        .unwrap();
}

#[test]
fn capacity_is_unavailable_during_writes_and_indeterminate_maintenance() {
    let root = TempRoot::new();
    let repo = repository(root.path());
    {
        let _writer = repo.publish_lock.lock().unwrap();
        assert_eq!(
            repo.publication_capacity_snapshot().unwrap_err().code,
            PlatformErrorCode::Unavailable
        );
    }
    repo.inject_parent_sync_failure_once();
    assert!(block_on(repo.publish(artifact("orphan", b"orphan"))).is_err());
    assert!(repo.publication_capacity_snapshot().is_err());
    drop(repo);
    let repo = repository(root.path());
    let before = repo.publication_capacity_snapshot().unwrap();
    super::super::shared_content::interrupt_reclamation_at(1);
    assert!(repo.reclaim_uncommitted_content(1).is_err());
    assert!(repo.publication_capacity_snapshot().is_err());
    drop(repo);
    let repo = repository(root.path());
    repo.reclaim_uncommitted_content(32).unwrap();
    let after = repo.publication_capacity_snapshot().unwrap();
    assert!(after.charged_storage_bytes < before.charged_storage_bytes);
    assert_eq!(after.indexed_publications, 0);
}

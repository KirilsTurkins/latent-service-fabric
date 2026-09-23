//! Scoped authority, legacy replay, bounded shared content and real restart.
use super::lifecycle::{accept, context, scope};
use super::*;
use crate::{
    LifecycleScope, ManagedPublicationReceipt, ManagedPublicationUpload, PublicationRef,
    ReleaseLifecycleAction, ReleaseLifecycleReason, ReleaseLifecycleState,
};
use latent_core::{PlatformError, TenantId};

fn publish(
    repo: &DirectoryArtifactRepository,
    value: CapsuleArtifact,
    id: &str,
) -> ManagedPublicationReceipt {
    block_on(repo.publish_managed(
        context(id, 0),
        ManagedPublicationUpload::Local(value),
        &mut accept,
    ))
    .unwrap()
}
fn selector(receipt: &ManagedPublicationReceipt) -> PublicationRef {
    receipt.publication.clone()
}

#[test]
fn sealed_preparation_preserves_exact_publication_through_coexistence_and_revocation() {
    let root = TempRoot::new();
    let repo = Arc::new(repository(root.path()));
    let first = artifact("first", b"shared execution bytes");
    let second = artifact("second", &first.component_bytes);
    let release = &first.descriptor.release_digest;
    let p1 = publish(&repo, first.clone(), "source-first");
    let owned = repo.clone().owned_preparation_source().unwrap();
    let old = owned
        .execution_eligibility_selected(release, Some(&p1.publication.id))
        .unwrap()
        .unwrap();
    let stamp = owned
        .identity_selected(release, Some(&p1.publication.id))
        .unwrap()
        .unwrap();
    let p2 = publish(&repo, second.clone(), "source-second");
    let second_stamp = owned
        .identity_selected(release, Some(&p2.publication.id))
        .unwrap()
        .unwrap();
    assert_ne!(stamp, second_stamp);
    assert_ne!(stamp.cache_digest(), second_stamp.cache_digest());
    assert_eq!(stamp.publication(), &p1.publication.id);
    assert!(
        owned.identity(release).is_err(),
        "fresh ambiguous legacy read is refused"
    );
    assert_eq!(
        owned
            .fetch_blocking_selected(
                release,
                Some(&p1.publication.id),
                repo.repository_read_limits()
            )
            .unwrap(),
        first
    );
    assert_eq!(
        owned
            .fetch_blocking_selected(
                release,
                Some(&p2.publication.id),
                repo.repository_read_limits()
            )
            .unwrap(),
        second
    );
    assert!(owned
        .identity_selected(
            &crate::content_digest(b"wrong component"),
            Some(&p2.publication.id)
        )
        .is_err());
    let unrelated = repo.select_execution_publication(
        &TenantId("foreign".into()),
        release,
        Some(&p1.publication.id),
    );
    assert_eq!(unrelated.unwrap_err().code, PlatformErrorCode::NotFound);
    assert_eq!(
        repo.select_execution_publication(
            &TenantId("foreign".into()),
            &crate::content_digest(b"unrelated bytes"),
            Some(&p1.publication.id)
        )
        .unwrap_err()
        .code,
        PlatformErrorCode::NotFound,
        "foreign selectors reveal no component association"
    );
    repo.change_publication_lifecycle(
        context("source-revoke", 1),
        &selector(&p1),
        ReleaseLifecycleAction::Revoke,
        ReleaseLifecycleReason::OperatorRevocation,
        &mut accept,
    )
    .unwrap();
    assert!(old.check_current().is_err());
    assert!(owned
        .fetch_blocking_selected(
            release,
            Some(&p1.publication.id),
            repo.repository_read_limits()
        )
        .is_err());
    let denied = repo
        .selected_historical_snapshot(release, Some(&p1.publication.id))
        .unwrap();
    let (_, state) = denied.into_parts();
    let crate::HistoricalExecutionState::Denied(denied) = state else {
        panic!("revocation must stay negative")
    };
    assert_eq!(denied.publication(), &p1.publication.id);
    assert_eq!(
        owned
            .fetch_blocking_selected(
                release,
                Some(&p2.publication.id),
                repo.repository_read_limits()
            )
            .unwrap(),
        second
    );
    drop(owned);
    drop(repo);
    assert!(old.check_current().is_err());
    let reopened = repository(root.path());
    assert_eq!(
        reopened
            .selected_metadata(release, Some(&p2.publication.id))
            .unwrap()
            .manifest(),
        &second.manifest
    );
    assert!(reopened
        .selected_execution_eligibility(release, Some(&p1.publication.id))
        .is_err());
}

#[test]
fn same_component_metadata_revisions_keep_independent_authority_and_exact_replay() {
    let root = TempRoot::new();
    let repo = repository(root.path());
    let first = artifact("first", b"same wasm");
    let p1 = publish(&repo, first.clone(), "first-create");
    let old_token = repo
        .publication_execution_eligibility(&p1.publication)
        .unwrap();
    let old_revoke = repo
        .change_publication_lifecycle(
            context("old-revoke", 1),
            &p1.publication,
            ReleaseLifecycleAction::Revoke,
            ReleaseLifecycleReason::OperatorRevocation,
            &mut accept,
        )
        .unwrap();
    assert!(old_token.check_current().is_err());
    let second = artifact("second", &first.component_bytes);
    let p2 = publish(&repo, second.clone(), "second-create");
    assert_ne!(p1.publication.id, p2.publication.id);
    let token = repo
        .publication_execution_eligibility(&p2.publication)
        .unwrap();
    assert_eq!(repo.fetch_publication(&p2.publication).unwrap(), second);
    let ambiguous = repo
        .preparation_source()
        .unwrap()
        .identity(&first.descriptor.release_digest)
        .unwrap_err();
    assert_eq!(ambiguous.code, PlatformErrorCode::StateConflict);
    assert!(!ambiguous.retryable);
    assert!(ambiguous.message.contains("publication-selector-ambiguous"));
    assert_eq!(
        block_on(repo.publish_managed(
            context("first-create", 0),
            ManagedPublicationUpload::Local(first.clone()),
            &mut accept
        ))
        .unwrap(),
        p1
    );
    assert_eq!(
        repo.change_publication_lifecycle(
            context("old-revoke", 1),
            &p1.publication,
            ReleaseLifecycleAction::Revoke,
            ReleaseLifecycleReason::OperatorRevocation,
            &mut accept
        )
        .unwrap(),
        old_revoke
    );
    repo.change_publication_lifecycle(
        context("retire-first", 2),
        &selector(&p1),
        ReleaseLifecycleAction::Retire,
        ReleaseLifecycleReason::EndOfSupport,
        &mut accept,
    )
    .unwrap();
    token.check_current().unwrap();
    assert_eq!(
        repo.publication_lifecycle_status(&p2.publication)
            .unwrap()
            .unwrap()
            .record
            .generation,
        1
    );
    assert!(
        repo.preparation_source()
            .unwrap()
            .identity(&first.descriptor.release_digest)
            .is_err(),
        "retirement does not resolve ambiguity"
    );
    drop(repo);
    let reopened = repository(root.path());
    assert_eq!(
        reopened
            .publication_lifecycle_status(&p1.publication)
            .unwrap()
            .unwrap()
            .record
            .state,
        ReleaseLifecycleState::Retired
    );
    assert_eq!(reopened.fetch_publication(&p2.publication).unwrap(), second);
    assert_eq!(
        reopened
            .change_publication_lifecycle(
                context("old-revoke", 1),
                &p1.publication,
                ReleaseLifecycleAction::Revoke,
                ReleaseLifecycleReason::OperatorRevocation,
                &mut accept
            )
            .unwrap(),
        old_revoke
    );
    assert_eq!(
        block_on(reopened.publish_managed(
            context("first-create", 0),
            ManagedPublicationUpload::Local(first),
            &mut accept
        ))
        .unwrap(),
        p1
    );
}

#[test]
fn tenant_selection_never_reveals_or_reuses_foreign_publications() {
    let root = TempRoot::new();
    let repo = repository(root.path());
    let value = artifact("scope-a", b"same wasm");
    let first = publish(&repo, value.clone(), "create-a");
    let foreign_scope = LifecycleScope::Tenant(TenantId("foreign".into()));
    assert!(repo
        .resolve_publication(&foreign_scope, &first.publication)
        .is_err());
    let mut forged = first.publication.clone();
    forged.scope = foreign_scope.clone();
    assert!(repo
        .resolve_publication(&foreign_scope, &forged)
        .unwrap()
        .is_none());
    let mut foreign_value = value.clone();
    foreign_value.manifest.metadata.tenant = Some(TenantId("foreign".into()));
    foreign_value.manifest.metadata.name = "echo".into();
    foreign_value.manifest.world.0 = foreign_value
        .manifest
        .world
        .0
        .replace("examples:", "foreign:");
    for export in &mut foreign_value.manifest.exports {
        export.contract.0 = export.contract.0.replace("examples:", "foreign:");
    }
    let mut foreign_context = context("create-b", 0);
    foreign_context.scope = foreign_scope.clone();
    let second = block_on(repo.publish_managed(
        foreign_context,
        ManagedPublicationUpload::Local(foreign_value),
        &mut accept,
    ))
    .unwrap();
    assert_eq!(
        repo.resolve_publication(&scope(), &first.publication)
            .unwrap(),
        Some(first.publication.clone())
    );
    assert_eq!(
        repo.resolve_publication(&foreign_scope, &second.publication)
            .unwrap(),
        Some(second.publication.clone())
    );
    assert_ne!(first.publication.id, second.publication.id);
    assert!(repo
        .publication_execution_eligibility(&first.publication)
        .unwrap()
        .authorize_tenant(&TenantId("foreign".into()))
        .is_err());
    assert_eq!(
        repo.change_publication_lifecycle(
            context("foreign-revoke", 1),
            &selector(&second),
            ReleaseLifecycleAction::Revoke,
            ReleaseLifecycleReason::OperatorRevocation,
            &mut accept
        )
        .unwrap_err()
        .code,
        PlatformErrorCode::InvalidArgument
    );
    repo.publication_execution_eligibility(&second.publication)
        .unwrap()
        .check_current()
        .unwrap();
}

#[test]
fn orphan_reclamation_keeps_shared_component_and_committed_history_pins() {
    use std::os::unix::fs::MetadataExt;
    let root = TempRoot::new();
    let repo = repository(root.path());
    let first = artifact("shared-first", b"shared bytes");
    let p1 = publish(&repo, first.clone(), "create-first");
    let committed = root
        .path()
        .join("publications")
        .join(p1.publication.id.hex())
        .join("component.wasm");
    let shared = root
        .path()
        .join("blobs")
        .join(&first.descriptor.release_digest.0[7..]);
    assert_eq!(
        fs::metadata(&committed).unwrap().ino(),
        fs::metadata(&shared).unwrap().ino()
    );
    repo.inject_parent_sync_failure_once();
    let orphan = artifact("shared-orphan", &first.component_bytes);
    assert!(block_on(repo.publish_managed(
        context("orphan", 0),
        ManagedPublicationUpload::Local(orphan),
        &mut accept
    ))
    .is_err());
    assert!(
        repo.reclaim_uncommitted_content(1).is_err(),
        "uncertain commit needs restart reconciliation"
    );
    drop(repo);
    let repo = Arc::new(repository(root.path()));
    let before = repo.publication_storage_snapshot().unwrap();
    assert_eq!(before.retained_publications, 2);
    let pin = Arc::clone(&repo).owned_preparation_source().unwrap();
    let token = repo
        .publication_execution_eligibility(&p1.publication)
        .unwrap();
    assert_eq!(repo.reclaim_uncommitted_content(1).unwrap().publications, 1);
    let collected = repo.reclaim_uncommitted_content(64).unwrap();
    assert!(collected.blobs > 0);
    let after = repo.publication_storage_snapshot().unwrap();
    assert_eq!(after.retained_publications, 1);
    assert!(after.shared_blob_bytes < before.shared_blob_bytes);
    assert_eq!(fs::read(&committed).unwrap(), first.component_bytes);
    assert!(shared.is_file());
    token.check_current().unwrap();
    assert_eq!(repo.fetch_publication(&p1.publication).unwrap(), first);
    drop(pin);
    assert_eq!(
        repo.reclaim_uncommitted_content(64).unwrap(),
        crate::PublicationContentReclamation::default()
    );
    assert!(repo.reclaim_uncommitted_content(0).is_err());
    assert!(repo.reclaim_uncommitted_content(1025).is_err());
}

#[test]
fn publication_disk_limit_rejects_before_staging_and_incomplete_files_stay_charged() {
    let root = TempRoot::new();
    let repo = DirectoryArtifactRepository::open(
        root.path(),
        DirectoryArtifactRepositoryConfig {
            max_storage_bytes: 1,
            ..DirectoryArtifactRepositoryConfig::default()
        },
    )
    .unwrap();
    assert_eq!(
        block_on(repo.publish(artifact("quota", b"bytes")))
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(repo.publication_storage_snapshot().unwrap().shared_blobs, 0);
    assert_eq!(fs::read_dir(root.path().join(".tmp")).unwrap().count(), 0);
    drop(repo);
    let debris = root.path().join("publications/incomplete");
    fs::create_dir(&debris).unwrap();
    fs::write(debris.join("partial"), b"12").unwrap();
    assert!(DirectoryArtifactRepository::open(
        root.path(),
        DirectoryArtifactRepositoryConfig {
            max_storage_bytes: 1,
            ..DirectoryArtifactRepositoryConfig::default()
        }
    )
    .is_err());
    let repo = repository(root.path());
    assert_eq!(
        repo.publication_storage_snapshot()
            .unwrap()
            .incomplete_file_bytes,
        2
    );
    assert_eq!(
        repo.reclaim_uncommitted_content(2).unwrap(),
        crate::PublicationContentReclamation::default()
    );
    assert!(
        debris.join("partial").is_file(),
        "unknown partial directories require offline operator repair"
    );
}

#[test]
fn concurrent_same_component_publications_have_independent_generations() {
    let root = TempRoot::new();
    let repo = Arc::new(repository(root.path()));
    let start = Arc::new(Barrier::new(4));
    let mut workers = Vec::new();
    for index in 0..4 {
        let repo = Arc::clone(&repo);
        let start = Arc::clone(&start);
        workers.push(thread::spawn(move || {
            let value = artifact(&format!("concurrent-{index}"), b"same component");
            let until = Instant::now() + Duration::from_secs(5);
            start.wait();
            loop {
                let result = block_on(repo.publish_managed(
                    context(&format!("create-{index}"), 0),
                    ManagedPublicationUpload::Local(value.clone()),
                    &mut accept,
                ));
                match result {
                    Err(PlatformError { ref message, .. })
                        if message == "admission-work-busy" && Instant::now() < until =>
                    {
                        thread::yield_now()
                    }
                    other => break other.unwrap(),
                }
            }
        }));
    }
    let receipts: Vec<_> = workers.into_iter().map(|w| w.join().unwrap()).collect();
    let ids: std::collections::BTreeSet<_> = receipts.iter().map(|r| &r.publication.id).collect();
    assert_eq!(ids.len(), 4);
    for receipt in receipts {
        assert_eq!(
            repo.publication_lifecycle_status(&receipt.publication)
                .unwrap()
                .unwrap()
                .record
                .generation,
            1
        );
        repo.publication_execution_eligibility(&receipt.publication)
            .unwrap()
            .check_current()
            .unwrap();
    }
}

#[test]
fn indeterminate_reclamation_does_not_refund_until_recovery() {
    for point in [1, 2] {
        let root = TempRoot::new();
        let repo = repository(root.path());
        let first = artifact("retained", b"shared");
        let receipt = publish(&repo, first.clone(), "first");
        repo.inject_parent_sync_failure_once();
        assert!(block_on(repo.publish(artifact("orphan", b"shared"))).is_err());
        drop(repo);
        let repo = repository(root.path());
        if point == 2 {
            assert_eq!(repo.reclaim_uncommitted_content(1).unwrap().publications, 1);
        }
        let charged = repo.publication_storage_snapshot().unwrap();
        super::super::shared_content::interrupt_reclamation_at(point);
        assert!(repo.reclaim_uncommitted_content(1).is_err());
        assert_eq!(repo.publication_storage_snapshot().unwrap(), charged);
        assert!(
            repo.reclaim_uncommitted_content(1).is_err(),
            "uncertain owner is quarantined"
        );
        drop(repo);
        let repo = repository(root.path());
        repo.reclaim_uncommitted_content(64).unwrap();
        assert_eq!(repo.fetch_publication(&receipt.publication).unwrap(), first);
        assert_eq!(
            repo.publication_storage_snapshot()
                .unwrap()
                .retained_publications,
            1
        );
    }
}

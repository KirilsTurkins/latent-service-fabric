//! Native artifact plus native control-store checks, not a reference-store model.
use super::*;
use latent_artifacts::{
    PublicationDeletionRequest, PublicationReferenceAuthority, PublicationRetentionAction,
    PublicationRetentionRequest,
};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    time::Duration,
};

const TIMEOUT: Duration = Duration::from_secs(10);
fn selection(
    repo: &DirectoryArtifactRepository,
    publication: &PublicationRef,
) -> PublicationDeletionRequest {
    let selected = repo
        .publication_retention_snapshot(
            &publication.scope,
            std::slice::from_ref(publication),
            TIMEOUT,
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
fn bytes(root: &Path) -> BTreeMap<PathBuf, Vec<u8>> {
    let mut result = BTreeMap::new();
    let mut pending = vec![root.to_owned()];
    while let Some(directory) = pending.pop() {
        for entry in std::fs::read_dir(directory).unwrap() {
            let entry = entry.unwrap();
            if entry.file_type().unwrap().is_dir() {
                pending.push(entry.path());
            } else {
                result.insert(
                    entry.path().strip_prefix(root).unwrap().to_owned(),
                    std::fs::read(entry.path()).unwrap(),
                );
            }
        }
    }
    result
}
fn bind(root: &TempRoot, repo: &Arc<DirectoryArtifactRepository>) -> Arc<Store> {
    let catalog = Arc::new(store(root, repo));
    catalog.bind_publication_reference_authority(repo).unwrap();
    catalog
}
fn refusal(
    repo: &DirectoryArtifactRepository,
    request: &PublicationDeletionRequest,
    message: &str,
) {
    assert_eq!(
        repo.inspect_publication_deletion(request, TIMEOUT)
            .unwrap_err()
            .message,
        message
    );
}
#[test]
fn native_deletion_assessment_preserves_every_file_charge_and_operation_identity() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let publication = publish(&repo, "alice", "one");
    let _catalog = bind(&roots[1], &repo);
    let request = selection(&repo, &publication);
    refusal(
        &repo,
        &request,
        "publication-deletion-requires-terminal-publication",
    );
    revoke(&repo, &publication);
    let request = selection(&repo, &publication);
    let before = [bytes(&roots[0].0), bytes(&roots[1].0)];
    let charge = repo.publication_capacity_snapshot().unwrap();
    for _ in 0..3 {
        let result = repo
            .inspect_publication_deletion(&request, TIMEOUT)
            .unwrap();
        assert_eq!(result.request, request);
        assert_eq!(result.reference_revision, 0);
    }
    assert_eq!(repo.publication_capacity_snapshot().unwrap(), charge);
    assert_eq!([bytes(&roots[0].0), bytes(&roots[1].0)], before);
    assert_eq!(
        repo.publication_retention_operation(&request.scope, &request.operation_id)
            .unwrap(),
        latent_artifacts::PublicationRetentionLookup::Unknown
    );
}
#[test]
fn native_retired_deployment_reference_survives_reopen_until_explicit_removal() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let publication = publish(&repo, "alice", "one");
    let catalog = bind(&roots[1], &repo);
    let desired = deployment("base", "alice", &release());
    run(catalog.apply(desired.clone())).unwrap();
    revoke(&repo, &publication);
    let request = selection(&repo, &publication);
    refusal(&repo, &request, "publication-deletion-referenced");
    drop(catalog);
    drop(repo);
    let repo = artifacts(&roots[0]);
    let catalog = bind(&roots[1], &repo);
    let request = selection(&repo, &publication);
    refusal(&repo, &request, "publication-deletion-referenced");
    run(catalog.delete(&desired.id)).unwrap();
    let result = repo
        .inspect_publication_deletion(&request, TIMEOUT)
        .unwrap();
    assert_eq!(result.reference_revision, 2);
}
#[test]
fn native_missing_foreign_dropped_and_replaced_reference_owners_fail_closed() {
    let roots = [
        TempRoot::new(),
        TempRoot::new(),
        TempRoot::new(),
        TempRoot::new(),
    ];
    let repo = artifacts(&roots[0]);
    let publication = publish(&repo, "alice", "one");
    revoke(&repo, &publication);
    let request = selection(&repo, &publication);
    refusal(
        &repo,
        &request,
        "publication-deletion-reference-authority-unavailable",
    );
    let foreign = artifacts(&roots[2]);
    let foreign_catalog = Arc::new(store(&roots[3], &foreign));
    assert!(foreign_catalog
        .bind_publication_reference_authority(&repo)
        .is_err());
    let catalog = bind(&roots[1], &repo);
    catalog.bind_publication_reference_authority(&repo).unwrap();
    assert!(repo.inspect_publication_deletion(&request, TIMEOUT).is_ok());
    drop(catalog);
    refusal(
        &repo,
        &request,
        "publication-deletion-reference-authority-unavailable",
    );
    let reopened = Arc::new(store(&roots[1], &repo));
    assert!(reopened
        .bind_publication_reference_authority(&repo)
        .is_err());
    refusal(
        &repo,
        &request,
        "publication-deletion-reference-authority-unavailable",
    );
}
#[test]
fn native_preparation_sources_and_all_clones_prevent_deletion_assessment() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let publication = publish(&repo, "alice", "one");
    revoke(&repo, &publication);
    let _catalog = bind(&roots[1], &repo);
    let request = selection(&repo, &publication);
    let owned = repo.clone().owned_preparation_source().unwrap();
    let copied = owned.clone();
    let borrowed = repo.preparation_source().unwrap();
    let borrowed_copy = borrowed.clone();
    drop(owned);
    drop(borrowed);
    refusal(&repo, &request, "publication-deletion-readers-active");
    drop(copied);
    refusal(&repo, &request, "publication-deletion-readers-active");
    drop(borrowed_copy);
    assert!(repo.inspect_publication_deletion(&request, TIMEOUT).is_ok());
}
#[test]
fn native_retention_pin_is_a_negative_deletion_reference_not_execution_authority() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let publication = publish(&repo, "alice", "one");
    revoke(&repo, &publication);
    let _catalog = bind(&roots[1], &repo);
    let selected = selection(&repo, &publication);
    let pin = PublicationRetentionRequest {
        scope: selected.scope,
        actor: selected.actor,
        operation_id: "keep-rollback".into(),
        expected_catalog_fence: selected.expected_catalog_fence,
        targets: selected.targets,
        action: PublicationRetentionAction::Pin,
    };
    repo.change_publication_retention(&pin, TIMEOUT, &mut |_| Ok(()))
        .unwrap();
    refusal(
        &repo,
        &selection(&repo, &publication),
        "publication-deletion-retention-pin",
    );
    let mut unpin = pin;
    unpin.operation_id = "release-rollback".into();
    unpin.action = PublicationRetentionAction::Unpin;
    unpin.expected_catalog_fence = selection(&repo, &publication).expected_catalog_fence;
    repo.change_publication_retention(&unpin, TIMEOUT, &mut |_| Ok(()))
        .unwrap();
    assert!(repo
        .inspect_publication_deletion(&selection(&repo, &publication), TIMEOUT)
        .is_ok());
    assert!(repo
        .execution_eligibility_selected(&release(), Some(&publication.id))
        .is_err());
}
#[test]
fn native_assessment_rechecks_generations_catalog_changes_and_exact_tenant() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let publication = publish(&repo, "alice", "one");
    let _catalog = bind(&roots[1], &repo);
    let stale = selection(&repo, &publication);
    revoke(&repo, &publication);
    assert!(repo.inspect_publication_deletion(&stale, TIMEOUT).is_err());
    let mut request = selection(&repo, &publication);
    publish(&repo, "bob", "unrelated");
    assert!(repo
        .inspect_publication_deletion(&request, TIMEOUT)
        .is_err());
    request = selection(&repo, &publication);
    request.scope = LifecycleScope::Tenant(TenantId("bob".into()));
    request.targets[0].publication.scope = request.scope.clone();
    let foreign = repo
        .inspect_publication_deletion(&request, TIMEOUT)
        .unwrap_err();
    request.targets[0].publication.id = format!("publication:sha256:{}", "55".repeat(32))
        .parse()
        .unwrap();
    let missing = repo
        .inspect_publication_deletion(&request, TIMEOUT)
        .unwrap_err();
    assert_eq!(foreign, missing);
}
#[test]
fn native_writer_excludes_assessment_and_remains_held_through_reference_callback() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let publication = publish(&repo, "alice", "one");
    revoke(&repo, &publication);
    let catalog = bind(&roots[1], &repo);
    let request = selection(&repo, &publication);
    let writer = catalog.writer.lock().unwrap();
    refusal(
        &repo,
        &request,
        "publication-deletion-reference-authority-unavailable",
    );
    drop(writer);
    let mut called = false;
    catalog
        .with_unreferenced_publications(&repo.lifecycle_authority(), &[publication], &mut |_| {
            called = true;
            assert!(catalog.writer.try_lock().is_err());
            assert!(catalog.current.try_write().is_err());
            Ok(())
        })
        .unwrap();
    assert!(called);
}
#[test]
fn native_batch_validation_and_elapsed_deadline_leave_no_deletion_intent() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let publication = publish(&repo, "alice", "one");
    revoke(&repo, &publication);
    let _catalog = bind(&roots[1], &repo);
    let mut request = selection(&repo, &publication);
    let before = bytes(&roots[0].0);
    assert!(repo
        .inspect_publication_deletion(&request, Duration::ZERO)
        .is_err());
    let target = request.targets[0].clone();
    request.targets.push(target.clone());
    assert!(repo
        .inspect_publication_deletion(&request, TIMEOUT)
        .is_err());
    request.targets = vec![target; 33];
    assert!(repo
        .inspect_publication_deletion(&request, TIMEOUT)
        .is_err());
    assert_eq!(bytes(&roots[0].0), before);
}
#[test]
fn terminal_native_rollout_keeps_both_publications_after_routes_are_removed() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let base = publish(&repo, "alice", "base");
    let catalog = bind(&roots[1], &repo);
    run(catalog.apply(deployment("base", "alice", &release()))).unwrap();
    let candidate = publish(&repo, "alice", "candidate");
    let mut desired = deployment("candidate", "alice", &release());
    desired.publication = Some(candidate.id.clone());
    desired.route_weight = 5000;
    let id = RolloutId("retained".into());
    execute(
        &catalog,
        RolloutRequest::Start {
            context: rollout_context("start", 0),
            spec: StartRolloutSpec {
                id: id.clone(),
                base: DeploymentExpectation {
                    id: DeploymentId("base".into()),
                    generation: 1,
                },
                candidate: desired,
                candidate_weights: vec![5000, 10000],
                canary_policy: None,
            },
        },
    );
    execute(
        &catalog,
        RolloutRequest::Change {
            context: rollout_context("complete", 1),
            id,
            command: RolloutCommand::Advance { next_step: 1 },
        },
    );
    // A completed rollout is retained rollback authority, not a live route.
    for desired in run(catalog.list()).unwrap() {
        run(catalog.delete(&desired.id)).unwrap();
    }
    for (index, publication) in [&base, &candidate].into_iter().enumerate() {
        repo.change_publication_lifecycle(
            context("alice", &format!("revoke-{index}"), 1),
            publication,
            ReleaseLifecycleAction::Revoke,
            ReleaseLifecycleReason::OperatorRevocation,
            &mut |_| Ok(()),
        )
        .unwrap();
        refusal(
            &repo,
            &selection(&repo, publication),
            "publication-deletion-referenced",
        );
    }
}

#[test]
fn unrelated_native_control_commit_is_rechecked_without_refreshing_the_publication_selection() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let old = publish(&repo, "alice", "old");
    revoke(&repo, &old);
    publish(&repo, "bob", "active");
    let catalog = bind(&roots[1], &repo);
    let request = selection(&repo, &old);
    assert_eq!(
        repo.inspect_publication_deletion(&request, TIMEOUT)
            .unwrap()
            .reference_revision,
        0
    );
    run(catalog.apply(deployment("other", "bob", &release()))).unwrap();
    assert_eq!(
        repo.inspect_publication_deletion(&request, TIMEOUT)
            .unwrap()
            .reference_revision,
        1
    );
}
#[test]
fn native_unconfirmed_reference_head_never_acts_as_an_empty_catalog() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let publication = publish(&repo, "alice", "old");
    revoke(&repo, &publication);
    let catalog = bind(&roots[1], &repo);
    let request = selection(&repo, &publication);
    let before = bytes(&roots[1].0);
    catalog.current.write().unwrap().confirmed = false;
    refusal(
        &repo,
        &request,
        "publication-deletion-reference-authority-unavailable",
    );
    assert_eq!(bytes(&roots[1].0), before);
}

mod tombstones;

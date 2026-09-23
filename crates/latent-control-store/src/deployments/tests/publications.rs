//! Real catalog authority with independent publications containing identical bytes.
use std::sync::Arc;

use latent_artifacts::{
    ArtifactRepository, DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig,
    LifecycleScope, ManagedPublicationUpload, PublicationRef, PublicationSelector, ReleaseActor,
    ReleaseActorKind, ReleaseLifecycleAction, ReleaseLifecycleReason, ReleaseMutationContext,
    ReleaseOperationPrecondition,
};
use latent_core::{DeploymentId, RouteGeneration, TenantId};
use latent_manifest::__serde_json as json;
use latent_routing::{RevisionPolicySource, RouteResolver};

use super::fixtures::*;
use crate::{rollouts::*, DeploymentStore};

mod history;
mod operations;

fn actor() -> ReleaseActor {
    ReleaseActor {
        subject: "publication-test".into(),
        kind: ReleaseActorKind::Host,
    }
}
fn context(tenant: &str, operation: &str, generation: u64) -> ReleaseMutationContext {
    ReleaseMutationContext {
        scope: LifecycleScope::Tenant(TenantId(tenant.into())),
        actor: actor(),
        operation: Some(ReleaseOperationPrecondition {
            operation_id: operation.into(),
            expected_generation: generation,
        }),
    }
}
fn publish(repo: &DirectoryArtifactRepository, tenant: &str, variant: &str) -> PublicationRef {
    publish_artifact(repo, tenant, variant, artifact("shared-executable"))
}
pub(super) fn publish_artifact(
    repo: &DirectoryArtifactRepository,
    tenant: &str,
    variant: &str,
    mut value: latent_artifacts::CapsuleArtifact,
) -> PublicationRef {
    value.manifest.metadata.tenant = Some(TenantId(tenant.into()));
    let contract = latent_core::ContractId(format!("{tenant}:echo/api@1.0.0"));
    value.manifest.world = contract.clone();
    value.manifest.exports[0].contract = contract.clone();
    value.contracts[0].id = contract.clone();
    value.contracts[0].package_name = format!("{tenant}:echo");
    value.contracts[0].interfaces[0].id = latent_core::InterfaceId(contract.0);
    value
        .manifest
        .metadata
        .annotations
        .insert("inventory-revision".into(), variant.into());
    run(repo.publish_managed(
        context(tenant, variant, 0),
        ManagedPublicationUpload::Local(value),
        &mut |_| Ok(()),
    ))
    .unwrap()
    .publication
}
fn release() -> latent_core::ReleaseDigest {
    artifact("shared-executable").descriptor.release_digest
}
fn target(tenant: &str, route: Option<&str>) -> latent_routing::InvocationTarget {
    let mut target = super::fixtures::target(tenant, route);
    target.contract = latent_core::ContractId(format!("{tenant}:echo/api@1.0.0"));
    target
}
fn artifacts(root: &TempRoot) -> Arc<DirectoryArtifactRepository> {
    Arc::new(
        DirectoryArtifactRepository::open(&root.0, DirectoryArtifactRepositoryConfig::default())
            .unwrap(),
    )
}
fn store(root: &TempRoot, repository: &Arc<DirectoryArtifactRepository>) -> Store {
    run(Store::open_with_catalog(
        &root.0,
        repository.clone(),
        Limits::default(),
        repository.lifecycle_authority(),
        super::lifecycle::profile("47.0.4"),
    ))
    .unwrap()
}
fn revoke(repository: &DirectoryArtifactRepository, reference: &PublicationRef) {
    let tenant = reference.scope.tenant().unwrap();
    repository
        .change_publication_lifecycle(
            context(&tenant.0, "revoke", 1),
            &PublicationSelector::Publication(reference.clone()),
            ReleaseLifecycleAction::Revoke,
            ReleaseLifecycleReason::OperatorRevocation,
            &mut |_| Ok(()),
        )
        .unwrap();
}

#[test]
fn scoped_routes_keep_selected_publications_across_coexistence_revocation_and_restart() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repository = artifacts(&roots[0]);
    let first = publish(&repository, "alice", "first");
    let catalog = store(&roots[1], &repository);
    let legacy = deployment("base", "alice", &release());
    run(catalog.apply(legacy.clone())).unwrap();
    let pinned = catalog.pin().unwrap();
    let original = pinned
        .resolve(&target("alice", Some("base")), None)
        .unwrap();
    assert_eq!(original.publication.as_ref(), Some(&first.id));

    let second = publish(&repository, "alice", "corrected-inventory");
    let other = publish(&repository, "bob", "first");
    assert!(repository
        .select_execution_publication(&TenantId("alice".into()), &release(), None)
        .is_err());
    // Reapplying the existing deployment keeps its captured legacy selection.
    run(catalog.apply(legacy.clone())).unwrap();
    assert_eq!(
        catalog
            .resolve(&target("alice", Some("base")), None)
            .unwrap()
            .publication,
        Some(first.id.clone())
    );
    let mut corrected = deployment("corrected", "alice", &release());
    corrected.publication = Some(second.id.clone());
    run(catalog.apply(corrected)).unwrap();
    run(catalog.apply(deployment("bob", "bob", &release()))).unwrap();
    let resolved = catalog.resolve(&target("bob", None), None).unwrap();
    assert_eq!(resolved.publication.as_ref(), Some(&other.id));
    let mut forged = original.clone();
    forged.publication = Some(second.id.clone());
    assert!(pinned.admission_policy(&forged).is_err());
    let mut foreign = deployment("foreign", "bob", &release());
    foreign.publication = Some(first.id.clone());
    assert!(run(catalog.apply(foreign)).is_err());

    revoke(&repository, &first);
    assert_code(pinned.admission_policy(&original), Code::PermissionDenied);
    assert_code(
        catalog.resolve(&target("alice", Some("base")), None),
        Code::PermissionDenied,
    );
    assert_eq!(
        catalog
            .resolve(&target("alice", Some("corrected")), None)
            .unwrap()
            .publication,
        Some(second.id.clone())
    );
    assert_eq!(
        catalog
            .resolve(&target("bob", None), None)
            .unwrap()
            .publication,
        Some(other.id.clone())
    );
    let generation = catalog.generation();
    drop(pinned);
    drop(catalog);
    drop(repository);

    let repository = artifacts(&roots[0]);
    let catalog = store(&roots[1], &repository);
    assert_eq!(catalog.generation(), generation);
    assert_eq!(
        run(DeploymentStore::get(&catalog, &legacy.id)).unwrap(),
        Some(legacy)
    );
    assert_code(
        catalog.resolve(&target("alice", Some("base")), None),
        Code::PermissionDenied,
    );
    assert_eq!(
        catalog
            .resolve(&target("alice", Some("corrected")), None)
            .unwrap()
            .publication,
        Some(second.id)
    );
    assert_eq!(
        catalog
            .resolve(&target("bob", None), None)
            .unwrap()
            .publication,
        Some(other.id)
    );
}

fn obsolete_catalog(root: &TempRoot) -> Vec<u8> {
    let path = root.0.join("catalog.json");
    let mut value: json::Value = json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    value["format_version"] = json::json!(2);
    value["payload"]
        .as_object_mut()
        .unwrap()
        .remove("publication_pins");
    for service in value["payload"]["snapshot"]["services"]
        .as_array_mut()
        .unwrap()
    {
        for revision in service["revisions"].as_array_mut().unwrap() {
            revision.as_object_mut().unwrap().remove("publication");
            revision["attributes"]
                .as_object_mut()
                .unwrap()
                .remove("lsf.publication");
        }
    }
    let mut record: super::super::persistence::Record = json::from_value(value).unwrap();
    record.checksum = latent_artifacts::content_digest(&json::to_vec(&record.payload).unwrap()).0;
    let bytes = json::to_vec(&record).unwrap();
    std::fs::write(path, &bytes).unwrap();
    bytes
}

#[test]
fn obsolete_catalog_rejection_never_infers_unique_or_ambiguous_publications() {
    for ambiguous in [false, true] {
        let roots = [TempRoot::new(), TempRoot::new()];
        let repository = artifacts(&roots[0]);
        publish(&repository, "alice", "first");
        let catalog = store(&roots[1], &repository);
        run(catalog.apply(deployment("base", "alice", &release()))).unwrap();
        drop(catalog);
        let bytes = obsolete_catalog(&roots[1]);
        if ambiguous {
            publish(&repository, "alice", "second");
        }
        assert!(run(Store::open_with_catalog(
            &roots[1].0,
            repository.clone(),
            Limits::default(),
            repository.lifecycle_authority(),
            super::lifecycle::profile("47.0.4")
        ))
        .is_err());
        assert_eq!(
            std::fs::read(roots[1].0.join("catalog.json")).unwrap(),
            bytes
        );
    }
}

fn rollout_context(operation: &str, expected_revision: u64) -> RolloutContext {
    RolloutContext {
        tenant: TenantId("alice".into()),
        actor: actor(),
        operation: RolloutOperationPrecondition {
            operation_id: operation.into(),
            expected_revision,
        },
    }
}
fn execute(catalog: &Store, request: RolloutRequest) -> RolloutCommitResult {
    let prepared = run(catalog.prepare_rollout(request)).unwrap();
    let committed = catalog.commit_rollout(prepared).unwrap();
    committed.durability.as_ref().unwrap();
    committed
}

#[test]
fn same_component_rollout_restores_exact_base_after_revocation_and_restart() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repository = artifacts(&roots[0]);
    let first = publish(&repository, "alice", "base");
    let catalog = store(&roots[1], &repository);
    let base = deployment("base", "alice", &release());
    run(catalog.apply(base.clone())).unwrap();
    let second = publish(&repository, "alice", "candidate");
    let mut candidate = deployment("candidate", "alice", &release());
    candidate.publication = Some(second.id.clone());
    candidate.route_weight = 5000;
    let id = RolloutId("shared-code".into());
    let start = RolloutRequest::Start {
        context: rollout_context("start", 0),
        spec: StartRolloutSpec {
            id: id.clone(),
            base: DeploymentExpectation {
                id: DeploymentId("base".into()),
                generation: 1,
            },
            candidate,
            candidate_weights: vec![5000, 10000],
            canary_policy: None,
        },
    };
    let started = execute(&catalog, start.clone());
    execute(
        &catalog,
        RolloutRequest::Change {
            context: rollout_context("complete", 1),
            id: id.clone(),
            command: RolloutCommand::Advance { next_step: 1 },
        },
    );
    let retained = catalog
        .get_rollout(&TenantId("alice".into()), &id)
        .unwrap()
        .unwrap();
    assert_eq!(retained.base.publication.as_ref(), Some(&first.id));
    assert_eq!(retained.candidate.publication.as_ref(), Some(&second.id));
    publish(&repository, "alice", "third");
    revoke(&repository, &second);
    drop(catalog);
    drop(repository);

    let repository = artifacts(&roots[0]);
    let catalog = store(&roots[1], &repository);
    let replay = execute(&catalog, start);
    assert!(replay.replayed);
    assert_eq!(replay.receipt, started.receipt);
    let restored = execute(
        &catalog,
        RolloutRequest::Change {
            context: rollout_context("rollback", 2),
            id,
            command: RolloutCommand::Rollback {
                target_generation: RouteGeneration(1),
            },
        },
    );
    assert_eq!(restored.receipt.state, RolloutState::RolledBack);
    assert_eq!(run(catalog.list()).unwrap(), vec![base]);
    assert_eq!(
        catalog
            .resolve(&target("alice", None), None)
            .unwrap()
            .publication,
        Some(first.id)
    );
}

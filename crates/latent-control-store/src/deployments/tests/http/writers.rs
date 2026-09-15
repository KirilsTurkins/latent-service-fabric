use super::*;
use crate::deployment_operations::{DeploymentOperationContext, DeploymentOperationRequest};
use crate::rollouts::{
    DeploymentExpectation, RolloutCommand, RolloutContext, RolloutId, RolloutOperationPrecondition,
    RolloutRequest, StartRolloutSpec,
};
use latent_routing::{RouteCompiler, RouteSnapshotPublisher, RouteSnapshotSource};

fn retained(root: &TempRoot) -> json::Value {
    let value: json::Value =
        json::from_slice(&std::fs::read(root.0.join("catalog.json")).unwrap()).unwrap();
    assert_eq!(value["format_version"], 7);
    value["payload"]["control"]["http_routes"].clone()
}

#[test]
fn http_history_survives_managed_deployments_rollouts_and_snapshot_writers() {
    let (roots, repo, store, publication) = setup();
    let http = request(
        &store,
        "http-create",
        definition(&store, "alice", "browser", "web", "/", "prefix"),
        0,
    );
    let receipt = execute(&store, http.clone()).value().receipt.clone();
    let original = retained(&roots[1]);
    let mut other = deployment("other", "alice", &receipt.component);
    other.publication = Some(publication.id);
    let prepared = run(store.prepare_operation(DeploymentOperationRequest::Apply {
        context: DeploymentOperationContext {
            tenant: TenantId("alice".into()),
            actor: actor(),
            operation_id: "managed".into(),
            expected_state_version: receipt.state_version,
        },
        manifest: other,
        expected_generation: 0,
    }))
    .unwrap();
    store
        .commit_operation(prepared)
        .unwrap()
        .value()
        .durability
        .as_ref()
        .unwrap();
    assert_eq!(retained(&roots[1]), original);
    assert!(selected(&store, "alice", "/").is_ok());
    run(store.delete(&DeploymentId("other".into()))).unwrap();
    assert_eq!(retained(&roots[1]), original);

    // A supported synchronous rollout in another tenant must preserve HTTP
    // state. Async web rollout compatibility belongs to the web release profile.
    let component = artifact("other-tenant-rollout");
    let old = super::super::publications::publish_artifact(&repo, "bob", "old", component.clone());
    let next =
        super::super::publications::publish_artifact(&repo, "bob", "next", component.clone());
    let mut base = deployment("base", "bob", &component.descriptor.release_digest);
    base.publication = Some(old.id);
    run(store.apply(base)).unwrap();
    let base_generation = store.read_publication().routes.versions[&DeploymentId("base".into())];
    let mut candidate = deployment("candidate", "bob", &component.descriptor.release_digest);
    candidate.publication = Some(next.id);
    candidate.route_weight = 2500;
    let context = |id: &str, revision| RolloutContext {
        tenant: TenantId("bob".into()),
        actor: actor(),
        operation: RolloutOperationPrecondition {
            operation_id: id.into(),
            expected_revision: revision,
        },
    };
    let prepared = run(store.prepare_rollout(RolloutRequest::Start {
        context: context("start", 0),
        spec: StartRolloutSpec {
            id: RolloutId("web-upgrade".into()),
            base: DeploymentExpectation {
                id: DeploymentId("base".into()),
                generation: base_generation,
            },
            candidate,
            candidate_weights: vec![2500, 10000],
            canary_policy: None,
        },
    }))
    .unwrap();
    store.commit_rollout(prepared).unwrap().durability.unwrap();
    assert_eq!(retained(&roots[1]), original);
    assert!(selected(&store, "alice", "/").is_ok());
    let prepared = run(store.prepare_rollout(RolloutRequest::Change {
        context: context("pause", 1),
        id: RolloutId("web-upgrade".into()),
        command: RolloutCommand::Pause,
    }))
    .unwrap();
    store.commit_rollout(prepared).unwrap().durability.unwrap();
    let previous = run(RouteSnapshotSource::current(&store)).unwrap();
    let next = run(RouteCompiler::compile(&store, Some(&previous))).unwrap();
    run(RouteSnapshotPublisher::publish(&store, next)).unwrap();
    assert_eq!(retained(&roots[1]), original);
    assert!(selected(&store, "alice", "/").is_ok());
    let web = run(store.get(&DeploymentId("web".into())))
        .unwrap()
        .unwrap();
    run(store.apply(web)).unwrap();
    assert!(selected(&store, "alice", "/").is_err());
    assert!(execute(&store, http.clone()).value().replayed);
    drop(store);
    let store = catalog(&roots[1], &repo);
    assert_eq!(retained(&roots[1]), original);
    assert!(execute(&store, http).value().replayed);
    assert!(selected(&store, "alice", "/").is_err());
    assert_eq!(
        store
            .get_rollout(&TenantId("bob".into()), &RolloutId("web-upgrade".into()))
            .unwrap()
            .unwrap()
            .revision,
        2
    );
}

#[test]
fn http_cancelled_preparation_releases_every_owned_charge_and_work_permit() {
    let (_roots, _repo, store, _) = setup();
    let command = request(
        &store,
        "abandoned",
        definition(&store, "alice", "browser", "web", "/", "prefix"),
        0,
    );
    let before = store.http_budget.used();
    let prepared = store.prepare_trigger_operation(command.clone()).unwrap();
    assert!(store.http_budget.used() > before);
    assert!(store.prepare_trigger_operation(command.clone()).is_err());
    drop(prepared);
    assert_eq!(store.http_budget.used(), before);
    assert!(get(&store, "alice", "browser").value().trigger.is_none());
    execute(&store, command);
}

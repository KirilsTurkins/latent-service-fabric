use super::fixtures::*;
use crate::{deployment_operations::*, DeploymentStore};
use latent_artifacts::{ReleaseActor, ReleaseActorKind};
use latent_core::{DeploymentId, ReleaseDigest, RouteGeneration, TenantId};
use latent_manifest::__serde_json as json;
use latent_routing::RouteResolver;
use std::sync::{atomic::Ordering, Arc};

mod mixed;
mod ownership;
mod persistence;

fn alice() -> TenantId {
    TenantId("alice".into())
}
fn context(operation: &str, state: u64) -> DeploymentOperationContext {
    DeploymentOperationContext {
        tenant: alice(),
        actor: ReleaseActor {
            kind: ReleaseActorKind::Host,
            subject: "managed-test".into(),
        },
        operation_id: operation.into(),
        expected_state_version: state,
    }
}
fn apply(
    operation: &str,
    state: u64,
    id: &str,
    generation: u64,
    release: &ReleaseDigest,
) -> DeploymentOperationRequest {
    DeploymentOperationRequest::Apply {
        context: context(operation, state),
        manifest: deployment(id, "alice", release),
        expected_generation: generation,
    }
}
fn delete(operation: &str, state: u64, id: &str, generation: u64) -> DeploymentOperationRequest {
    DeploymentOperationRequest::Delete {
        context: context(operation, state),
        id: DeploymentId(id.into()),
        expected_generation: generation,
    }
}
fn execute(
    store: &Store,
    request: DeploymentOperationRequest,
) -> DeploymentOperationRead<DeploymentOperationCommit> {
    let prepared = run(store.prepare_operation(request)).unwrap();
    let preview = prepared.preview().clone();
    let value = store.commit_operation(prepared).unwrap();
    assert_eq!(value.value().receipt, preview);
    value.value().durability.as_ref().unwrap();
    value
}
fn bytes(root: &TempRoot) -> Vec<u8> {
    std::fs::read(root.0.join("catalog.json")).unwrap()
}
fn stored(root: &TempRoot) -> json::Value {
    json::from_slice(&bytes(root)).unwrap()
}
fn lookup(store: &Store, operation: &str) -> DeploymentOperationRead<DeploymentOperationLookup> {
    run(store.get_operation(&alice(), operation)).unwrap()
}
fn open_limits(
    root: &TempRoot,
    releases: &Arc<Releases>,
    limits: DeploymentOperationLimits,
) -> Store {
    run(Store::open_with_operation_limits(
        &root.0,
        releases.clone(),
        Limits::default(),
        limits,
    ))
    .unwrap()
}

#[test]
fn managed_first_publication_replays_exact_history_after_restart_without_fetch() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("managed-one");
    let store = open(&root, &releases);
    let id = DeploymentId("blue".into());
    let empty = run(store.get_operation_snapshot(&alice(), &id)).unwrap();
    assert!(empty.value().deployment.is_none());
    assert_eq!(empty.value().state_version, 0);
    assert_eq!(empty.value().route_generation, RouteGeneration(0));
    assert!(empty.value().confirmed);
    drop(empty);
    let request = apply("create-blue", 0, "blue", 0, &one);
    let first = execute(&store, request.clone());
    assert!(!first.value().replayed);
    assert_eq!(first.value().receipt.state_version, 1);
    assert_eq!(first.value().receipt.route_generation, RouteGeneration(1));
    assert_eq!(
        first.value().receipt.request_digest,
        request.request_digest().unwrap()
    );
    let persisted = stored(&root);
    assert_eq!(persisted["format_version"], 4);
    assert!(persisted["payload"]["control"]["rollouts"]["rows"]
        .as_array()
        .unwrap()
        .is_empty());
    let original_bytes = bytes(&root);
    let receipt = first.value().receipt.clone();
    drop(first);
    drop(store);
    let store = open(&root, &releases);
    assert_eq!(bytes(&root), original_bytes);
    assert_eq!(
        lookup(&store, "create-blue").value(),
        &DeploymentOperationLookup::Found(receipt.clone())
    );
    let fetched = releases.fetches.load(Ordering::Relaxed);
    let replay = execute(&store, request);
    assert!(replay.value().replayed);
    assert_eq!(replay.value().receipt, receipt);
    assert_eq!(releases.fetches.load(Ordering::Relaxed), fetched);
    assert_eq!(bytes(&root), original_bytes);
}

#[test]
fn delete_recreate_and_late_apply_replay_preserve_original_result() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("original");
    let two = releases.add("replacement");
    let store = open(&root, &releases);
    let request = apply("create", 0, "blue", 0, &one);
    let first = execute(&store, request.clone());
    let removed = execute(&store, delete("remove", 1, "blue", 1));
    assert_eq!(removed.value().receipt.object_generation, 1);
    assert_eq!(removed.value().receipt.component, one);
    assert!(removed.value().deployment.is_none());
    let recreated = execute(&store, apply("recreate", 2, "blue", 0, &two));
    assert_eq!(recreated.value().receipt.object_generation, 3);
    let before = bytes(&root);
    let replay = execute(&store, request);
    assert_eq!(replay.value().deployment, first.value().deployment);
    assert_eq!(replay.value().receipt, first.value().receipt);
    let live = run(store.get_operation_snapshot(&alice(), &DeploymentId("blue".into()))).unwrap();
    assert_eq!(
        live.value().deployment.as_ref().unwrap().manifest.release,
        two
    );
    assert_eq!(live.value().state_version, 3);
    assert_eq!(
        lookup(&store, "remove").value(),
        &DeploymentOperationLookup::Found(removed.value().receipt.clone())
    );
    assert_eq!(bytes(&root), before);
}

#[test]
fn finite_receipt_eviction_cannot_replay_an_absent_object_creation() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("aba");
    let store = open_limits(
        &root,
        &releases,
        DeploymentOperationLimits {
            maximum_receipts: 2,
            ..DeploymentOperationLimits::default()
        },
    );
    let request = apply("create", 0, "blue", 0, &one);
    drop(execute(&store, request.clone()));
    drop(execute(&store, delete("remove", 1, "blue", 1)));
    drop(execute(&store, apply("other", 2, "green", 0, &one)));
    assert_eq!(
        lookup(&store, "create").value(),
        &DeploymentOperationLookup::Unknown {
            retained_floor: 2,
            high_watermark: 3
        }
    );
    let before = bytes(&root);
    let failure = run(store.prepare_operation(request.clone())).err().unwrap();
    assert_eq!(failure.code, Code::StateConflict);
    assert_eq!(failure.message, "deployment-state-version-conflict");
    assert!(
        run(store.get_versioned(&alice(), &DeploymentId("blue".into())))
            .unwrap()
            .is_none()
    );
    assert_eq!(bytes(&root), before);
    drop(store);
    let reopened = open(&root, &releases);
    assert_eq!(
        stored(&root)["payload"]["control"]["deployment_operations"]["receipt_slots"],
        2
    );
    assert_code(
        run(reopened.prepare_operation(request)),
        Code::StateConflict,
    );
    drop(execute(&reopened, apply("next", 3, "green", 3, &one)));
    assert_eq!(
        lookup(&reopened, "remove").value(),
        &DeploymentOperationLookup::Unknown {
            retained_floor: 3,
            high_watermark: 4
        }
    );
}

#[test]
fn operation_identity_binds_actor_scope_body_and_both_preconditions() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("identity");
    let two = releases.add("other-content");
    let store = open(&root, &releases);
    let request = apply("exact", 0, "blue", 0, &one);
    drop(execute(&store, request.clone()));
    let before = bytes(&root);
    for kind in 0..5 {
        let mut altered = request.clone();
        let DeploymentOperationRequest::Apply {
            context,
            manifest,
            expected_generation,
        } = &mut altered
        else {
            unreachable!()
        };
        match kind {
            0 => context.actor.subject = "another-operator".into(),
            1 => context.expected_state_version = 1,
            2 => *expected_generation = 1,
            3 => manifest.release = two.clone(),
            4 => {
                manifest.id.0 = "another-object".into();
                manifest.metadata.name = "another-object".into();
            }
            _ => unreachable!(),
        }
        assert_code(run(store.prepare_operation(altered)), Code::StateConflict);
    }
    let foreign = run(store.get_operation(&TenantId("bob".into()), "exact")).unwrap();
    assert!(matches!(
        foreign.value(),
        DeploymentOperationLookup::Unknown { .. }
    ));
    let hidden =
        run(store.get_operation_snapshot(&TenantId("bob".into()), &DeploymentId("blue".into())))
            .unwrap();
    assert!(hidden.value().deployment.is_none());
    assert_eq!(bytes(&root), before);
}

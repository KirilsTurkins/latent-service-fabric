mod admission;
pub(super) mod fixtures;
mod golden;
mod lifecycle;
#[cfg(unix)]
mod lock_release;
#[cfg(feature = "catalog-observation")]
mod observation;
mod pagination;
mod recovery;
#[cfg(target_os = "linux")]
mod resources;
mod reuse_integrity;
mod root_identity;
mod runtime_compatibility;
mod scoped_routes;
mod supply_chain;
mod verified_metadata;
mod versioned;

use std::sync::atomic::Ordering;
use std::sync::{Arc, Barrier};

use latent_artifacts::content_digest;
use latent_core::{DeploymentId, RouteGeneration, TenantId};
use latent_manifest::{ExecutionBackendKind, StateModel};
use latent_routing::{RouteCompiler, RouteResolver, RouteSnapshotPublisher, RouteSnapshotSource};

use super::deployment_revision_id;
use crate::{CompiledRouteStore, DeploymentStore};
use fixtures::*;

#[test]
fn apply_read_list_delete_and_pinned_revision() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let two = releases.add("two");
    let store = open(&root, &releases);
    let first = deployment("blue", "alice", &one);
    let id = first.id.clone();
    run(store.apply(first.clone())).unwrap();
    assert_eq!(store.generation(), RouteGeneration(1));
    assert_eq!(
        run(DeploymentStore::get(&store, &id)).unwrap(),
        Some(first.clone())
    );
    assert_eq!(run(store.list()).unwrap(), vec![first]);
    let pinned = store.pin().unwrap();
    let resolved = pinned.resolve(&target("alice", None), Some("key")).unwrap();
    run(store.apply(deployment("blue", "alice", &two))).unwrap();
    let current = store.resolve(&target("alice", None), Some("key")).unwrap();
    assert_eq!(current.release, two);
    assert_ne!(current.revision, resolved.revision);
    assert_eq!(
        pinned.resolve(&target("alice", None), Some("key")).unwrap(),
        resolved
    );
    assert_eq!(resolved.release, one);
    assert_eq!(resolved.route_generation, RouteGeneration(1));
    run(store.delete(&id)).unwrap();
    assert_eq!(store.generation(), RouteGeneration(3));
    assert_code(
        store.resolve(&target("alice", None), None),
        Code::RouteUnavailable,
    );
    assert_eq!(
        pinned
            .resolve(&target("alice", None), None)
            .unwrap()
            .release,
        one
    );
    assert_code(run(store.delete(&id)), Code::NotFound);
    assert!(run(DeploymentStore::get(&store, &id)).unwrap().is_none());
}

#[test]
fn tenants_and_named_routes_never_cross_boundaries() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let two = releases.add("two");
    let store = open(&root, &releases);
    let deployments = vec![
        deployment("alice-blue", "alice", &one),
        deployment("bob-blue", "bob", &two),
    ];
    run(store.apply_many(deployments)).unwrap();
    for key in [None, Some(""), Some("same-key")] {
        assert_eq!(
            store.resolve(&target("alice", None), key).unwrap().release,
            one
        );
        assert_eq!(
            store.resolve(&target("bob", None), key).unwrap().release,
            two
        );
    }
    assert_code(
        store.resolve(&target("alice", Some("bob-blue")), None),
        Code::RouteUnavailable,
    );
    assert_code(
        store.resolve(&target("unknown", None), None),
        Code::RouteUnavailable,
    );
    let mut wrong = target("alice", None);
    wrong.function.0 = "missing".to_owned();
    assert_code(store.resolve(&wrong, None), Code::IncompatibleContract);
    wrong.contract.0 = "missing:contract/api@1.0.0".to_owned();
    assert_code(store.resolve(&wrong, None), Code::IncompatibleContract);
    wrong.service.0 = "missing".to_owned();
    assert_code(store.resolve(&wrong, None), Code::RouteUnavailable);
}

#[test]
fn weighting_is_deterministic_order_independent_and_restart_stable() {
    let root = TempRoot::new();
    let other = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let two = releases.add("two");
    let blue = deployment("blue", "alice", &one);
    let mut green = deployment("green", "alice", &two);
    green.route_weight = 3;
    let store = open(&root, &releases);
    let reverse = open(&other, &releases);
    run(store.apply_many(vec![blue.clone(), green.clone()])).unwrap();
    run(reverse.apply_many(vec![green, blue.clone()])).unwrap();
    let mut choices = Vec::new();
    for index in 0..2048 {
        let key = format!("key-{index}");
        let result = store.resolve(&target("alice", None), Some(&key)).unwrap();
        let reordered = reverse.resolve(&target("alice", None), Some(&key)).unwrap();
        assert_eq!(result, reordered);
        choices.push(result);
    }
    let blue_count = choices
        .iter()
        .filter(|choice| choice.release == one)
        .count();
    assert!(
        (400..=625).contains(&blue_count),
        "blue count: {blue_count}"
    );
    let named = store
        .resolve(&target("alice", Some("blue")), Some("any"))
        .unwrap();
    assert_eq!(named.release, one);
    let mut changed = blue.clone();
    changed.route_weight = 10_000;
    let identity = deployment_revision_id(&blue).unwrap();
    assert_eq!(identity, deployment_revision_id(&changed).unwrap());
    changed.resources.cpu_fuel -= 1;
    assert_ne!(identity, deployment_revision_id(&changed).unwrap());
    changed = blue.clone();
    changed.metadata.namespace = Some("other".to_owned());
    assert_ne!(identity, deployment_revision_id(&changed).unwrap());
    changed = blue;
    changed.metadata.tenant = Some(TenantId("bob".to_owned()));
    assert_ne!(identity, deployment_revision_id(&changed).unwrap());
    drop(store);
    let store = open(&root, &releases);
    for (index, choice) in choices.iter().enumerate() {
        let key = format!("key-{index}");
        let restored = store.resolve(&target("alice", None), Some(&key)).unwrap();
        assert_eq!(restored, *choice);
    }
}

#[test]
fn invalid_batches_leave_generation_and_state_unchanged() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let store = open(&root, &releases);
    let blue = deployment("blue", "alice", &one);
    run(store.apply(blue.clone())).unwrap();
    let before = snapshot(&store);
    for weight in [0, 10_001, u16::MAX] {
        let mut invalid = blue.clone();
        invalid.route_weight = weight;
        assert_code(run(store.apply(invalid)), Code::InvalidArgument);
    }
    assert_code(
        run(store.apply_many(vec![blue.clone(), blue.clone()])),
        Code::AlreadyExists,
    );
    let mut conflict = blue.clone();
    conflict.metadata.tenant = Some(TenantId("bob".to_owned()));
    assert_code(run(store.apply(conflict)), Code::PermissionDenied);
    let mut namespace = deployment("green", "alice", &one);
    namespace.metadata.namespace = Some("other".to_owned());
    assert_code(run(store.apply(namespace)), Code::PermissionDenied);
    let missing = deployment("missing", "alice", &content_digest(b"missing"));
    let batch = vec![deployment("valid", "alice", &one), missing];
    assert_code(run(store.apply_many(batch)), Code::NotFound);
    assert_code(
        run(store.apply(deployment("default", "alice", &one))),
        Code::AlreadyExists,
    );
    assert_eq!(snapshot(&store), before);
    assert_eq!(run(store.list()).unwrap(), vec![blue]);
}

#[test]
fn rejects_unsupported_releases_and_contract_conflicts() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let two = releases.add("two");
    let store = open(&root, &releases);
    run(store.apply(deployment("blue", "alice", &one))).unwrap();
    for backend in [
        ExecutionBackendKind::Container,
        ExecutionBackendKind::MicroVm,
        ExecutionBackendKind::EphemeralProcess,
        ExecutionBackendKind::RemoteProvider,
    ] {
        releases
            .values
            .write()
            .unwrap()
            .get_mut(&two)
            .unwrap()
            .manifest
            .execution
            .backend = backend;
        assert_code(
            run(store.apply(deployment("green", "alice", &two))),
            Code::InvalidArgument,
        );
    }
    releases.add("two");
    for state in [
        StateModel::Entity,
        StateModel::DurableWorkflow,
        StateModel::TransactionalKeyed,
    ] {
        releases
            .values
            .write()
            .unwrap()
            .get_mut(&two)
            .unwrap()
            .manifest
            .execution
            .state_model = state;
        assert_code(
            run(store.apply(deployment("green", "alice", &two))),
            Code::InvalidArgument,
        );
    }
    releases.add("two");
    releases
        .values
        .write()
        .unwrap()
        .get_mut(&two)
        .unwrap()
        .contracts[0]
        .interfaces[0]
        .functions[0]
        .asynchronous = true;
    assert_code(
        run(store.apply(deployment("green", "alice", &two))),
        Code::IncompatibleContract,
    );
    releases
        .values
        .write()
        .unwrap()
        .get_mut(&two)
        .unwrap()
        .contracts
        .clear();
    assert_code(
        run(store.apply(deployment("green", "alice", &two))),
        Code::IncompatibleContract,
    );
    releases.add("two");
    releases
        .values
        .write()
        .unwrap()
        .get_mut(&two)
        .unwrap()
        .component_bytes
        .push(0);
    assert_code(
        run(store.apply(deployment("green", "alice", &two))),
        Code::CorruptArtifact,
    );
    assert_eq!(store.generation(), RouteGeneration(1));
}

#[test]
fn duplicate_contract_and_function_ids_are_rejected() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let store = open(&root, &releases);
    {
        let mut values = releases.values.write().unwrap();
        let artifact = values.get_mut(&one).unwrap();
        artifact.contracts.push(artifact.contracts[0].clone());
    }
    assert_code(
        run(store.apply(deployment("blue", "alice", &one))),
        Code::AlreadyExists,
    );
    releases.add("one");
    {
        let mut values = releases.values.write().unwrap();
        let functions = &mut values.get_mut(&one).unwrap().contracts[0].interfaces[0].functions;
        functions.push(functions[0].clone());
    }
    assert_code(
        run(store.apply(deployment("blue", "alice", &one))),
        Code::AlreadyExists,
    );
    assert_eq!(store.generation(), RouteGeneration(0));
}

#[test]
fn compiler_publisher_and_coalescing_source_enforce_complete_generations() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let store = open(&root, &releases);
    run(store.apply(deployment("blue", "alice", &one))).unwrap();
    let old = snapshot(&store);
    let next = run(RouteCompiler::compile(&store, Some(&old))).unwrap();
    let mut invalid = next.clone();
    invalid.services.clear();
    assert_code(run(store.publish(invalid)), Code::InvalidArgument);
    run(CompiledRouteStore::put(&store, next.clone())).unwrap();
    assert_code(run(store.publish(next.clone())), Code::StateConflict);
    assert_code(
        run(RouteCompiler::compile(&store, Some(&old))),
        Code::StateConflict,
    );
    assert_eq!(
        run(store.watch(old.generation)).unwrap(),
        vec![next.clone()]
    );
    assert!(run(store.watch(next.generation)).unwrap().is_empty());
    assert_code(
        run(store.watch(RouteGeneration(999))),
        Code::InvalidArgument,
    );
    assert!(run(CompiledRouteStore::get(&store, old.generation))
        .unwrap()
        .is_none());
}

#[test]
fn root_ownership_limits_and_hot_path_are_explicit() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let store = open(&root, &releases);
    assert_code(
        run(Store::open(
            root.0.clone(),
            releases.clone(),
            Limits::default(),
        )),
        Code::Unavailable,
    );
    run(store.apply(deployment("blue", "alice", &one))).unwrap();
    let calls = releases.fetches.load(Ordering::Relaxed);
    for _ in 0..100 {
        store.resolve(&target("alice", None), Some("key")).unwrap();
    }
    assert_eq!(releases.fetches.load(Ordering::Relaxed), calls);
    let guard = store.current.write().unwrap();
    assert_code(
        store.resolve(&target("alice", None), None),
        Code::Unavailable,
    );
    drop(guard);
    assert_code(
        store.resolve(&target("alice", None), Some(&"x".repeat(4097))),
        Code::InvalidArgument,
    );
    drop(store);
    let limits = Limits {
        max_state_bytes: 1024,
        ..Limits::default()
    };
    assert_code(
        run(Store::open(root.0.clone(), releases, limits)),
        Code::ResourceExhausted,
    );
}

#[test]
fn configured_bounds_reject_mutations_before_persistence() {
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let limits = [
        Limits {
            max_state_bytes: 1024,
            ..Limits::default()
        },
        Limits {
            max_route_entries: 1,
            ..Limits::default()
        },
    ];
    for limit in limits {
        let root = TempRoot::new();
        let store = run(Store::open(root.0.clone(), releases.clone(), limit)).unwrap();
        assert_code(
            run(store.apply(deployment("blue", "alice", &one))),
            Code::ResourceExhausted,
        );
        assert_eq!(store.generation(), RouteGeneration(0));
    }
    let root = TempRoot::new();
    let limit = Limits {
        max_identifier_bytes: 32,
        ..Limits::default()
    };
    let store = run(Store::open(root.0.clone(), releases, limit)).unwrap();
    let oversized = deployment(&"x".repeat(33), "alice", &one);
    assert_code(run(store.apply(oversized)), Code::InvalidArgument);
    assert_eq!(store.generation(), RouteGeneration(0));
}

#[test]
fn concurrent_writers_cannot_overwrite_a_newer_generation() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let store = open(&root, &releases);
    *releases.fetch_gate.lock().unwrap() = Some(Arc::new(Barrier::new(2)));
    let results = std::thread::scope(|scope| {
        let blue = scope.spawn(|| run(store.apply(deployment("blue", "alice", &one))));
        let green = scope.spawn(|| run(store.apply(deployment("green", "alice", &one))));
        [blue.join().unwrap(), green.join().unwrap()]
    });
    assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
    for failure in results.into_iter().filter_map(Result::err) {
        assert_eq!(failure.code, Code::StateConflict);
    }
    assert_eq!(store.generation(), RouteGeneration(1));
    assert_eq!(run(store.list()).unwrap().len(), 1);
    *releases.fetch_gate.lock().unwrap() = None;
    let batch = vec![
        deployment("blue", "alice", &one),
        deployment("green", "alice", &one),
    ];
    run(store.apply_many(batch)).unwrap();
    assert_eq!(store.generation(), RouteGeneration(2));
    assert_eq!(run(store.list()).unwrap().len(), 2);
}

#[test]
fn concurrent_snapshot_replacement_never_exposes_half_a_batch() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let two = releases.add("two");
    let store = open(&root, &releases);
    let initial = vec![
        deployment("blue", "alice", &one),
        deployment("green", "alice", &one),
    ];
    run(store.apply_many(initial)).unwrap();
    let barrier = Barrier::new(5);
    std::thread::scope(|scope| {
        for _ in 0..4 {
            let store = &store;
            let barrier = &barrier;
            scope.spawn(move || {
                for iteration in 0..20 {
                    barrier.wait();
                    let view = loop {
                        match store.pin() {
                            Ok(view) => break view,
                            Err(failure) => {
                                assert_eq!(failure.code, Code::Unavailable);
                                std::thread::yield_now();
                            }
                        }
                    };
                    let blue = view.resolve(&target("alice", Some("blue")), None).unwrap();
                    let green = view.resolve(&target("alice", Some("green")), None).unwrap();
                    assert_eq!(blue.release, green.release);
                    assert_eq!(blue.route_generation, green.route_generation);
                    assert!((iteration + 1..=iteration + 2).contains(&view.generation().0));
                    barrier.wait();
                    assert_eq!(store.generation(), RouteGeneration(iteration + 2));
                }
            });
        }
        for iteration in 0..20 {
            barrier.wait();
            let release = if iteration % 2 == 0 { &two } else { &one };
            let batch = vec![
                deployment("blue", "alice", release),
                deployment("green", "alice", release),
            ];
            run(store.apply_many(batch)).unwrap();
            barrier.wait();
        }
    });
    assert_eq!(run(store.list()).unwrap().len(), 2);
    assert!(run(DeploymentStore::get(
        &store,
        &DeploymentId("blue".to_owned())
    ))
    .unwrap()
    .is_some());
}

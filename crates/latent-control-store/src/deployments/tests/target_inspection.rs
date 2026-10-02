//! Catalog ownership tests; real Java preparation is qualified independently.
use super::fixtures::*;
use crate::{
    target_inspection::{TargetInspectionRequest, TargetObservationState, TargetReason},
    DeploymentStore,
};
use latent_routing::RouteResolver;
use std::{sync::atomic::Ordering, sync::Arc};

fn query(tenant: &str) -> TargetInspectionRequest {
    TargetInspectionRequest {
        target: target(tenant, None),
        revision: None,
        publication: None,
        routing_key: None,
    }
}

#[test]
fn target_candidates_use_existing_tenant_indexes_and_never_fetch_or_change_state() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let blue = releases.add("blue");
    let green = releases.add("green");
    let store = open(&root, &releases);
    run(store.apply_many(vec![
        deployment("blue", "alice", &blue),
        deployment("green", "alice", &green),
        deployment("foreign", "bob", &green),
    ]))
    .unwrap();
    let before = snapshot(&store);
    let fetches = releases.fetches.load(Ordering::Relaxed);
    let observed = store.inspect_target(query("alice")).unwrap();
    assert_eq!(observed.candidates.len(), 2);
    assert!(observed.selected_revision.is_none());
    assert!(observed
        .candidates
        .iter()
        .all(|candidate| candidate.export_compatible
            && !candidate.http_compatible
            && !candidate.eligible
            && candidate
                .reasons
                .contains(&TargetReason::UnmanagedPublication)));
    assert_eq!(
        store.finish_target_inspection(&observed).unwrap(),
        TargetObservationState::Coherent
    );
    assert_eq!(snapshot(&store), before);
    assert_eq!(releases.fetches.load(Ordering::Relaxed), fetches);
    let mut request = query("alice");
    request.routing_key = Some("supported-context".into());
    let selected = store.inspect_target(request).unwrap();
    assert_eq!(
        selected.selected_revision,
        Some(
            store
                .resolve(&target("alice", None), Some("supported-context"))
                .unwrap()
                .revision
        )
    );
    let foreign = store.inspect_target(query("unknown")).unwrap();
    assert!(foreign.candidates.is_empty() && foreign.selected_revision.is_none());
}

#[test]
fn changed_target_snapshot_is_stale_and_exact_filters_never_pick_another_revision() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let two = releases.add("two");
    let store = open(&root, &releases);
    run(store.apply(deployment("blue", "alice", &one))).unwrap();
    let observed = store.inspect_target(query("alice")).unwrap();
    let id = observed.candidates[0].revision.clone();
    let mut request = query("alice");
    request.revision = Some(id);
    let exact = store.inspect_target(request.clone()).unwrap();
    assert_eq!(exact.candidates.len(), 1);
    run(store.apply(deployment("blue", "alice", &two))).unwrap();
    assert_eq!(
        store.finish_target_inspection(&observed).unwrap(),
        TargetObservationState::Stale
    );
    assert!(store.inspect_target(request).unwrap().candidates.is_empty());
    assert_eq!(observed.candidates[0].component, one);
}

#[test]
fn inspection_candidate_and_physical_read_owner_limits_fail_closed() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let release = releases.add("one");
    let store = open(&root, &releases);
    run(store.apply_many(
        (0..33)
            .map(|index| deployment(&format!("d-{index:03}"), "alice", &release))
            .collect(),
    ))
    .unwrap();
    assert_code(
        store.inspect_target(query("alice")),
        Code::ResourceExhausted,
    );
    assert_eq!(snapshot(&store).generation.0, 1);
    let mut invalid = query("alice");
    invalid.target.function.0 = "x".repeat(513);
    assert_code(store.inspect_target(invalid), Code::InvalidArgument);
}

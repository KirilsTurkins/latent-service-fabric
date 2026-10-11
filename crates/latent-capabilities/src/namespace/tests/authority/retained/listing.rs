use super::*;
use latent_state::namespace::lifecycle::{NamespaceLifecycleLimits, NamespaceLifecycleRegistry};

fn prepare(fixture: &Fixture, operation: &str) -> (OwnedPolicyDecision, OwnedPolicyDecision) {
    let mut document = fixture.document.clone();
    for (index, subject) in ["alice", "bob"].into_iter().enumerate() {
        let caller = principal(subject);
        let resource = scope(&caller, None, &RecoverySelection::OriginalCaller);
        document["rules"][index]["resources"]["scopes"]
            .as_array_mut()
            .unwrap()
            .push(serde_json::to_value(&resource).unwrap());
        document["rules"][index]["operations"] =
            serde_json::json!(["namespace-inspect", "namespace-list"]);
    }
    fixture.update(Some(&document), operation);
    decisions(fixture, "alice")
}

fn decisions(fixture: &Fixture, subject: &str) -> (OwnedPolicyDecision, OwnedPolicyDecision) {
    let actor = principal(subject);
    let resource = scope(&actor, None, &RecoverySelection::OriginalCaller);
    let snapshot = fixture.snapshot();
    let listing = fixture.decision(&snapshot, &actor, &resource, "namespace-list");
    let inspection = fixture.decision(&snapshot, &actor, &resource, "namespace-inspect");
    (
        fixture.policy.retain_decision(&listing).unwrap(),
        fixture.policy.retain_decision(&inspection).unwrap(),
    )
}

#[test]
fn retained_listing_requires_both_exact_caller_decisions_and_the_actual_catalog_handle() {
    let fixture = Fixture::new();
    let (listing, inspection) = prepare(&fixture, "approve-listing");
    let (_, other_inspection) = decisions(&fixture, "bob");
    let read = fixture.read();
    let lifecycle = fixture.namespaces.lifecycle();
    let handle = lifecycle.pin(&read).unwrap();
    let foreign = NamespaceLifecycleRegistry::new(NamespaceLifecycleLimits::default()).unwrap();
    let foreign_handle = foreign.pin(&read).unwrap();
    assert!(lifecycle.owns_handle(&handle));
    assert!(!lifecycle.owns_handle(&foreign_handle));
    let mut published = false;
    NamespaceControl::with_listing_retained(
        &fixture.policy,
        &listing,
        &inspection,
        lifecycle,
        &handle,
        &read,
        || {
            published = true;
            Ok(())
        },
    )
    .unwrap();
    assert!(published);
    for (actual_listing, actual_inspection, actual_handle) in [
        (&inspection, &inspection, &handle),
        (&listing, &other_inspection, &handle),
        (&listing, &inspection, &foreign_handle),
    ] {
        assert!(NamespaceControl::with_listing_retained(
            &fixture.policy,
            actual_listing,
            actual_inspection,
            lifecycle,
            actual_handle,
            &read,
            || panic!("foreign listing scope or owner published")
        )
        .is_err());
    }
    assert_eq!(lifecycle.retained_owners(), 1);
    drop(handle);
    assert_eq!(lifecycle.retained_owners(), 0);
}

#[test]
fn retained_listing_handle_blocks_drain_and_cannot_cross_accepted_lifecycle_changes() {
    let fixture = Fixture::new();
    let (listing, inspection) = prepare(&fixture, "approve-listing-lifecycle");
    let read = fixture.read();
    let lifecycle = fixture.namespaces.lifecycle();
    let handle = lifecycle.pin(&read).unwrap();
    let mut next = read.record().clone();
    next.status = latent_state::namespace::NamespaceStatus::Quiescing;
    next.version.generation += 1;
    assert!(matches!(
        lifecycle.begin_transition(&read, &next, true),
        Err(latent_state::namespace::NamespaceError::InUse)
    ));
    let completion = lifecycle.begin_transition(&read, &next, false).unwrap();
    assert!(NamespaceControl::with_listing_retained(
        &fixture.policy,
        &listing,
        &inspection,
        lifecycle,
        &handle,
        &read,
        || panic!("accepted transition exposed old view")
    )
    .is_err());
    fixture
        .database
        .apply(AtomicBatch {
            expectations: vec![read.expectation()],
            mutations: vec![RowMutation {
                key: read.expectation().key,
                value: Some(next.encode().unwrap()),
            }],
        })
        .unwrap();
    let after = fixture.read();
    completion.resolve(&after).unwrap();
    assert!(NamespaceControl::with_listing_retained(
        &fixture.policy,
        &listing,
        &inspection,
        lifecycle,
        &handle,
        &after,
        || panic!("old handle renewed after transition")
    )
    .is_err());
    let current = lifecycle.pin(&after).unwrap();
    NamespaceControl::with_listing_retained(
        &fixture.policy,
        &listing,
        &inspection,
        lifecycle,
        &current,
        &after,
        || Ok(()),
    )
    .unwrap();
    assert_eq!(lifecycle.retained_owners(), 2);
    drop(handle);
    drop(current);
    assert_eq!(lifecycle.retained_owners(), 0);
}

#[test]
fn replacement_listing_permission_cannot_revive_the_original_retained_page_grant() {
    let fixture = Fixture::new();
    let (listing, inspection) = prepare(&fixture, "approve-original-listing");
    let read = fixture.read();
    let lifecycle = fixture.namespaces.lifecycle();
    let handle = lifecycle.pin(&read).unwrap();
    fixture.update(None, "withdraw-original-listing");
    let (current_listing, current_inspection) = prepare(&fixture, "approve-replacement-listing");
    assert!(NamespaceControl::with_listing_retained(
        &fixture.policy,
        &listing,
        &inspection,
        lifecycle,
        &handle,
        &read,
        || panic!("replacement renewed original permission")
    )
    .is_err());
    NamespaceControl::with_listing_retained(
        &fixture.policy,
        &current_listing,
        &current_inspection,
        lifecycle,
        &handle,
        &read,
        || Ok(()),
    )
    .unwrap();
    assert_eq!(lifecycle.retained_owners(), 1);
    drop(handle);
    assert_eq!(lifecycle.retained_owners(), 0);
}

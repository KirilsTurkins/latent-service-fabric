use super::*;

fn prepare(fixture: &Fixture, operation_id: &str) -> (OwnedPolicyDecision, OwnedPolicyDecision) {
    let actor = principal("alice");
    let scope = scope(&actor, None, &RecoverySelection::OriginalCaller);
    let mut document = fixture.document.clone();
    document["rules"][0]["resources"]["scopes"]
        .as_array_mut()
        .unwrap()
        .push(serde_json::to_value(&scope).unwrap());
    document["rules"][0]["operations"] =
        serde_json::json!(["namespace-inspect", "effect-plan", "effect-terminate"]);
    fixture.update(Some(&document), operation_id);
    let snapshot = fixture.snapshot();
    let operation = fixture.decision(&snapshot, &actor, &scope, "effect-terminate");
    let inspection = fixture.decision(&snapshot, &actor, &scope, "namespace-inspect");
    (
        fixture.policy.retain_decision(&operation).unwrap(),
        fixture.policy.retain_decision(&inspection).unwrap(),
    )
}

#[test]
fn configured_precondition_is_shared_by_inspection_and_action_without_reissuing_grant() {
    let fixture = Fixture::new();
    let (operation, inspection) = prepare(&fixture, "approve-effect-management");
    assert_eq!(
        operation.configuration_digest(),
        inspection.configuration_digest()
    );
    let old = operation.configuration_digest();
    let read = fixture.read();
    let mut accepted = false;
    NamespaceControl::with_operation_retained(
        &fixture.policy,
        &operation,
        &inspection,
        fixture.namespaces.lifecycle(),
        &read,
        "effect-terminate",
        || {
            accepted = true;
            Ok(())
        },
    )
    .unwrap();
    assert!(accepted);
    fixture.update(None, "withdraw-effect-management");
    accepted = false;
    assert!(NamespaceControl::with_operation_retained(
        &fixture.policy,
        &operation,
        &inspection,
        fixture.namespaces.lifecycle(),
        &read,
        "effect-terminate",
        || {
            accepted = true;
            Ok(())
        }
    )
    .is_err());
    assert!(!accepted);
    assert_eq!(operation.configuration_digest(), old);
}

#[test]
fn revoked_original_management_decision_cannot_be_revived_by_replacement_configuration() {
    let fixture = Fixture::new();
    let (operation, inspection) = prepare(&fixture, "approve-effect-management");
    let read = fixture.read();
    let (new_operation, new_inspection) = prepare(&fixture, "replace-effect-management");
    assert_ne!(
        operation.configuration_digest(),
        new_operation.configuration_digest()
    );
    let row = batch(&read, "old-management");
    assert!(fixture
        .database
        .apply_fenced(row, || NamespaceControl::with_operation_retained(
            &fixture.policy,
            &operation,
            &inspection,
            fixture.namespaces.lifecycle(),
            &read,
            "effect-terminate",
            || Ok(())
        ))
        .is_err());
    absent(&fixture, "old-management");
    NamespaceControl::with_operation_retained(
        &fixture.policy,
        &new_operation,
        &new_inspection,
        fixture.namespaces.lifecycle(),
        &read,
        "effect-terminate",
        || Ok(()),
    )
    .unwrap();
}

#[test]
fn original_action_and_actual_namespace_lifecycle_are_checked_before_writer_acceptance() {
    let fixture = Fixture::new();
    let (operation, inspection) = prepare(&fixture, "approve-effect-management");
    let before = fixture.read();
    assert!(NamespaceControl::with_operation_retained(
        &fixture.policy,
        &operation,
        &inspection,
        fixture.namespaces.lifecycle(),
        &before,
        "effect-redrive",
        || panic!("different action accepted")
    )
    .is_err());
    let mut next = before.record().clone();
    next.status = latent_state::namespace::NamespaceStatus::Quiescing;
    next.version.generation += 1;
    let completion = fixture
        .namespaces
        .lifecycle()
        .begin_transition(&before, &next, false)
        .unwrap();
    assert!(NamespaceControl::with_operation_retained(
        &fixture.policy,
        &operation,
        &inspection,
        fixture.namespaces.lifecycle(),
        &before,
        "effect-terminate",
        || panic!("stale lifecycle accepted")
    )
    .is_err());
    fixture
        .database
        .apply(AtomicBatch {
            expectations: vec![before.expectation()],
            mutations: vec![RowMutation {
                key: before.expectation().key,
                value: Some(next.encode().unwrap()),
            }],
        })
        .unwrap();
    let after = fixture.read();
    completion.resolve(&after).unwrap();
    NamespaceControl::with_operation_retained(
        &fixture.policy,
        &operation,
        &inspection,
        fixture.namespaces.lifecycle(),
        &after,
        "effect-terminate",
        || Ok(()),
    )
    .unwrap();
}

//! Retained acquisition uses actual policy/catalog/engine rows, not a copied allow.
use super::*;
mod management;

fn retained(fixture: &Fixture) -> OwnedPolicyDecision {
    let actor = principal("alice");
    let scope = scope(
        &actor,
        Some("alice-order"),
        &RecoverySelection::OriginalCaller,
    );
    let snapshot = fixture.snapshot();
    let decision = fixture.decision(&snapshot, &actor, &scope, "acquire-command");
    fixture.policy.retain_decision(&decision).unwrap()
}

fn seal(
    fixture: &Fixture,
    decision: OwnedPolicyDecision,
    read: &NamespaceRead,
    original_deadline: Instant,
) -> Result<NamespaceAuthority, PlatformError> {
    NamespaceAuthority::seal_retained(
        &fixture.policy,
        decision,
        read,
        NamespaceAdmission {
            activation: ActivationId("retained-activation".into()),
            deadline: original_deadline,
            recovery: &RecoverySelection::OriginalCaller,
            state_schema: &schema(),
        },
        fixture.namespaces.lifecycle().pin(read).unwrap(),
    )
}

fn advance_generation(fixture: &Fixture, read: &NamespaceRead) -> NamespaceRead {
    let mut next = read.record().clone();
    next.version.generation = next.version.generation.checked_add(1).unwrap();
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
    fixture.read()
}

#[test]
fn retained_admission_uses_fresh_engine_generation_and_original_activation_deadline() {
    let fixture = Fixture::new();
    let decision = retained(&fixture);
    let before = fixture.read();
    let after = advance_generation(&fixture, &before);
    let original_deadline = Instant::now() + Duration::from_secs(5);
    let authority = seal(&fixture, decision, &after, original_deadline).unwrap();
    assert_ne!(authority.version(), before.record().version);
    assert_eq!(authority.version(), after.record().version);
    assert_eq!(
        authority.activation_id(),
        &ActivationId("retained-activation".into())
    );
    assert_eq!(authority.deadline(), original_deadline);
    assert_eq!(authority.ownership().caller.owner_subject, "alice");
    assert_eq!(
        authority.publication,
        fixture.publication.publication().as_str()
    );
    // No commit acceptance happened merely by rebasing the observed row.
    assert!(authority.cancellation().request());
}

#[test]
fn retained_admission_final_gate_still_accepts_inside_the_actual_writer_once() {
    let fixture = Fixture::new();
    let decision = retained(&fixture);
    let before = fixture.read();
    let after = advance_generation(&fixture, &before);
    let authority = seal(&fixture, decision, &after, deadline()).unwrap();
    let actor = principal("alice");
    let scope = scope(
        &actor,
        Some("alice-order"),
        &RecoverySelection::OriginalCaller,
    );
    let snapshot = fixture.snapshot();
    let commit = fixture.decision(&snapshot, &actor, &scope, "commit");
    let pending = batch(&after, "retained-final");
    let acceptance = authority
        .prepare_commit_io(&fixture.policy, &commit, &after, &pending)
        .unwrap();
    let mut accepted = None;
    fixture
        .database
        .apply_fenced(pending, || {
            acceptance.accept().map(|value| accepted = Some(value))
        })
        .unwrap();
    assert_eq!(accepted.unwrap().activation_id(), authority.activation_id());
    assert!(!authority.cancellation().request());
    let view = fixture.database.snapshot().unwrap();
    for family in [Family::State, Family::Outbox, Family::Command] {
        assert_eq!(
            view.get(&RowKey {
                family,
                key: b"retained-final".to_vec()
            })
            .unwrap(),
            Some(b"retained".to_vec())
        );
    }
}

#[test]
fn refreshed_policy_permission_cannot_revive_the_original_retained_acquisition() {
    let fixture = Fixture::new();
    let original = retained(&fixture);
    fixture.update(Some(&fixture.document), "new-policy-revision");
    let fresh_new_admission = retained(&fixture);
    let read = fixture.read();
    assert!(seal(&fixture, original, &read, deadline()).is_err());
    assert!(seal(&fixture, fresh_new_admission, &read, deadline()).is_ok());
}

#[test]
fn retained_policy_owner_mismatch_rejects_before_the_callback() {
    let original_owner = Fixture::new();
    let other_owner = Fixture::new();
    let decision = retained(&original_owner);
    let mut callback_ran = false;
    assert!(other_owner
        .policy
        .with_retained_decision(&decision, &mut |_, _| {
            callback_ran = true;
            Ok(())
        })
        .is_err());
    assert!(!callback_ran);
}

#[test]
fn exact_publication_revocation_rejects_retained_admission_despite_shared_component() {
    let fixture = Fixture::new();
    let decision = retained(&fixture);
    let reference = latent_artifacts::PublicationRef {
        id: fixture.publication.publication().clone(),
        scope: latent_artifacts::LifecycleScope::Tenant(TenantId("a".into())),
    };
    fixture
        .catalog
        .change_publication_lifecycle(
            latent_artifacts::ReleaseMutationContext {
                scope: reference.scope.clone(),
                actor: latent_artifacts::ReleaseActor {
                    subject: "operator".into(),
                    kind: latent_artifacts::ReleaseActorKind::Administrator,
                },
                operation: Some(latent_artifacts::ReleaseOperationPrecondition {
                    operation_id: "retained-revoke-publication".into(),
                    expected_generation: 1,
                }),
            },
            &reference,
            latent_artifacts::ReleaseLifecycleAction::Revoke,
            latent_artifacts::ReleaseLifecycleReason::OperatorRevocation,
            &mut |_| Ok(()),
        )
        .unwrap();
    assert!(seal(&fixture, decision, &fixture.read(), deadline()).is_err());
    fixture.other.check_current().unwrap();
}

#[test]
fn expired_original_deadline_does_not_gain_a_new_policy_wall_time() {
    let fixture = Fixture::new();
    let decision = retained(&fixture);
    assert!(seal(&fixture, decision, &fixture.read(), Instant::now()).is_err());
}

#[test]
fn new_incarnation_cannot_rebase_the_original_retained_scope() {
    let fixture = Fixture::new();
    let decision = retained(&fixture);
    let read = fixture.read();
    let mut replacement = read.record().clone();
    replacement.version.incarnation += 1;
    replacement.version.generation += 1;
    fixture
        .database
        .apply(AtomicBatch {
            expectations: vec![read.expectation()],
            mutations: vec![RowMutation {
                key: read.expectation().key,
                value: Some(replacement.encode().unwrap()),
            }],
        })
        .unwrap();
    assert!(seal(&fixture, decision, &fixture.read(), deadline()).is_err());
}

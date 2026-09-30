//! Actual policy/catalog and redb authority schedules, compiled/run on Linux.
use super::*;
use latent_state::embedded::{
    AtomicBatch, Family, FencedStoreError, RowKey, RowMutation, StoreError,
};
use latent_state::namespace::catalog::{
    NamespaceMutation, NamespaceOperationContext, NamespaceRead,
};
use latent_state::namespace::NamespaceTransition;
mod fixture;
use fixture::*;

fn batch(read: &NamespaceRead, name: &str) -> AtomicBatch {
    AtomicBatch {
        expectations: vec![read.expectation()],
        mutations: [Family::State, Family::Outbox, Family::Command]
            .into_iter()
            .map(|family| RowMutation {
                key: RowKey {
                    family,
                    key: name.as_bytes().to_vec(),
                },
                value: Some(b"retained".to_vec()),
            })
            .collect(),
    }
}
fn absent(fixture: &Fixture, name: &str) {
    let view = fixture.database.snapshot().unwrap();
    for family in [Family::State, Family::Outbox, Family::Command] {
        assert!(view
            .get(&RowKey {
                family,
                key: name.as_bytes().to_vec()
            })
            .unwrap()
            .is_none());
    }
}

fn persist_control(
    fixture: &Fixture,
    prepared: PreparedNamespaceControl<'_>,
) -> (
    latent_state::namespace::catalog::NamespaceOperationReceipt,
    bool,
) {
    let (batch, receipt, replay, fence) = prepared.into_parts();
    let mut completion = None;
    fixture
        .database
        .apply_fenced(batch, || fence.accept().map(|value| completion = value))
        .unwrap();
    assert_eq!(completion.is_some(), !replay);
    if let Some(completion) = completion {
        let row = latent_state::namespace::catalog::NamespaceCatalog::read_in(
            &fixture.database.snapshot().unwrap(),
            &receipt.record.tenant,
            &receipt.record.id,
        )
        .unwrap()
        .unwrap();
        completion.resolve(&row).unwrap();
    }
    (receipt, replay)
}

fn approve_management(fixture: &Fixture, scope: &latent_policy::capability::StateResourceScope) {
    let mut document = fixture.document.clone();
    document["rules"][0]["resources"]["scopes"]
        .as_array_mut()
        .unwrap()
        .push(serde_json::to_value(scope).unwrap());
    document["rules"][0]["operations"] =
        serde_json::json!(["namespace-quiesce", "namespace-retire", "namespace-inspect"]);
    fixture.update(Some(&document), "approve-lifecycle");
}

fn lifecycle_mutation(read: &NamespaceRead, action: NamespaceTransition) -> NamespaceMutation {
    NamespaceMutation::Transition {
        id: read.record().id.clone(),
        expected: read.record().version,
        action,
    }
}

#[test]
fn policy_revoked_before_actual_writer_acceptance_leaves_all_families_unmodified() {
    let fixture = Fixture::new();
    let actor = principal("alice");
    let scope = scope(
        &actor,
        Some("alice-order"),
        &RecoverySelection::OriginalCaller,
    );
    let snapshot = fixture.snapshot();
    let initial = fixture.decision(&snapshot, &actor, &scope, "acquire-command");
    let commit = fixture.decision(&snapshot, &actor, &scope, "commit");
    let read = fixture.read();
    let authority = NamespaceAuthority::seal(
        &fixture.policy,
        &initial,
        &read,
        NamespaceAdmission {
            activation: ActivationId("a1".into()),
            deadline: deadline(),
            recovery: &RecoverySelection::OriginalCaller,
            state_schema: &schema(),
        },
        fixture.namespaces.lifecycle().pin(&read).unwrap(),
    )
    .unwrap();
    let batch = batch(&read, "revoked");
    let acceptance = authority
        .prepare_commit_io(&fixture.policy, &commit, &read, &batch)
        .unwrap();
    fixture.update(None, "revoke");
    assert!(matches!(
        fixture
            .database
            .apply_fenced(batch, || acceptance.accept().map(|_| ())),
        Err(FencedStoreError::Fence(_))
    ));
    absent(&fixture, "revoked");
}

#[test]
fn publication_revoked_before_writer_acceptance_does_not_revoke_shared_component_correction() {
    let fixture = Fixture::new();
    let actor = principal("alice");
    let scope = scope(
        &actor,
        Some("alice-order"),
        &RecoverySelection::OriginalCaller,
    );
    let snapshot = fixture.snapshot();
    let initial = fixture.decision(&snapshot, &actor, &scope, "acquire-command");
    let commit = fixture.decision(&snapshot, &actor, &scope, "commit");
    let read = fixture.read();
    let authority = NamespaceAuthority::seal(
        &fixture.policy,
        &initial,
        &read,
        NamespaceAdmission {
            activation: ActivationId("p1".into()),
            deadline: deadline(),
            recovery: &RecoverySelection::OriginalCaller,
            state_schema: &schema(),
        },
        fixture.namespaces.lifecycle().pin(&read).unwrap(),
    )
    .unwrap();
    let pending = batch(&read, "publication-revoked");
    let acceptance = authority
        .prepare_commit_io(&fixture.policy, &commit, &read, &pending)
        .unwrap();
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
                    operation_id: "revoke-publication".into(),
                    expected_generation: 1,
                }),
            },
            &reference,
            latent_artifacts::ReleaseLifecycleAction::Revoke,
            latent_artifacts::ReleaseLifecycleReason::OperatorRevocation,
            &mut |_| Ok(()),
        )
        .unwrap();
    assert!(matches!(
        fixture
            .database
            .apply_fenced(pending, || acceptance.accept().map(|_| ())),
        Err(FencedStoreError::Fence(_))
    ));
    absent(&fixture, "publication-revoked");
    fixture.other.check_current().unwrap();
}

#[test]
fn approved_shared_scope_allows_current_members_and_withdrawal_denies_historical_replay() {
    let fixture = Fixture::new();
    let alice = principal("alice");
    let bob = principal("bob");
    let selection = RecoverySelection::Shared {
        name: "approved-team".into(),
    };
    let shared = scope(&alice, Some("shared-order"), &selection);
    let mut document = fixture.document.clone();
    for rule in document["rules"].as_array_mut().unwrap() {
        rule["resources"]["scopes"]
            .as_array_mut()
            .unwrap()
            .push(serde_json::to_value(&shared).unwrap());
    }
    fixture.update(Some(&document), "approve-shared");
    let snapshot = fixture.snapshot();
    let alice_decision = fixture.decision(&snapshot, &alice, &shared, "read-result");
    let bob_decision = fixture.decision(&snapshot, &bob, &shared, "read-result");
    let read = fixture.read();
    let alice_authority = NamespaceAuthority::seal(
        &fixture.policy,
        &alice_decision,
        &read,
        NamespaceAdmission {
            activation: ActivationId("shared-a".into()),
            deadline: deadline(),
            recovery: &selection,
            state_schema: &schema(),
        },
        fixture.namespaces.lifecycle().pin(&read).unwrap(),
    )
    .unwrap();
    let bob_authority = NamespaceAuthority::seal(
        &fixture.policy,
        &bob_decision,
        &read,
        NamespaceAdmission {
            activation: ActivationId("shared-b".into()),
            deadline: deadline(),
            recovery: &selection,
            state_schema: &schema(),
        },
        fixture.namespaces.lifecycle().pin(&read).unwrap(),
    )
    .unwrap();
    let historical = alice_authority.ownership().clone();
    assert_ne!(
        historical.caller.owner_subject,
        bob_authority.ownership().caller.owner_subject
    );
    bob_authority
        .with_recovery_access(
            &fixture.policy,
            &bob_decision,
            &read,
            "read-result",
            &historical,
            || Ok(()),
        )
        .unwrap();
    fixture.update(Some(&fixture.document), "withdraw-shared");
    assert!(bob_authority
        .with_recovery_access(
            &fixture.policy,
            &bob_decision,
            &read,
            "read-result",
            &historical,
            || Ok(())
        )
        .is_err());
    let current = fixture.snapshot();
    assert!(fixture
        .decision_for(&current, &bob, &shared, "read-result", &fixture.publication)
        .is_err());
}

#[test]
fn real_writer_cancellation_before_acceptance_aborts_and_after_acceptance_preserves_commit() {
    let fixture = Fixture::new();
    let actor = principal("alice");
    let scope = scope(
        &actor,
        Some("alice-order"),
        &RecoverySelection::OriginalCaller,
    );
    let snapshot = fixture.snapshot();
    let initial = fixture.decision(&snapshot, &actor, &scope, "acquire-command");
    let commit = fixture.decision(&snapshot, &actor, &scope, "commit");
    let read = fixture.read();
    let authority = NamespaceAuthority::seal(
        &fixture.policy,
        &initial,
        &read,
        NamespaceAdmission {
            activation: ActivationId("a1".into()),
            deadline: deadline(),
            recovery: &RecoverySelection::OriginalCaller,
            state_schema: &schema(),
        },
        fixture.namespaces.lifecycle().pin(&read).unwrap(),
    )
    .unwrap();
    let pending = batch(&read, "cancelled");
    let acceptance = authority
        .prepare_commit_io(&fixture.policy, &commit, &read, &pending)
        .unwrap();
    assert!(authority.cancellation().request());
    assert!(matches!(
        fixture
            .database
            .apply_fenced(pending, || acceptance.accept().map(|_| ())),
        Err(FencedStoreError::Fence(_))
    ));
    absent(&fixture, "cancelled");
    let authority = NamespaceAuthority::seal(
        &fixture.policy,
        &initial,
        &read,
        NamespaceAdmission {
            activation: ActivationId("a2".into()),
            deadline: deadline(),
            recovery: &RecoverySelection::OriginalCaller,
            state_schema: &schema(),
        },
        fixture.namespaces.lifecycle().pin(&read).unwrap(),
    )
    .unwrap();
    let pending = batch(&read, "committed");
    let acceptance = authority
        .prepare_commit_io(&fixture.policy, &commit, &read, &pending)
        .unwrap();
    let control = authority.cancellation();
    fixture
        .database
        .apply_fenced(pending, || {
            let accepted = acceptance.accept()?;
            assert_eq!(accepted.activation_id().0, "a2");
            assert!(!control.request());
            Ok::<_, latent_state::namespace::NamespaceError>(())
        })
        .unwrap();
    assert!(!control.request());
    let view = fixture.database.snapshot().unwrap();
    for family in [Family::State, Family::Outbox, Family::Command] {
        assert_eq!(
            view.get(&RowKey {
                family,
                key: b"committed".to_vec()
            })
            .unwrap()
            .as_deref(),
            Some(b"retained".as_slice())
        );
    }
    let pending = batch(&read, "duplicate");
    let acceptance = authority
        .prepare_commit_io(&fixture.policy, &commit, &read, &pending)
        .unwrap();
    assert!(matches!(
        fixture
            .database
            .apply_fenced(pending, || acceptance.accept().map(|_| ())),
        Err(FencedStoreError::Fence(_))
    ));
    absent(&fixture, "duplicate");
}

#[test]
fn lifecycle_cas_rejects_stale_handles_and_recreation_cannot_revive_result_ownership() {
    let fixture = Fixture::new();
    let actor = principal("alice");
    let scope = scope(
        &actor,
        Some("alice-order"),
        &RecoverySelection::OriginalCaller,
    );
    let snapshot = fixture.snapshot();
    let initial = fixture.decision(&snapshot, &actor, &scope, "acquire-command");
    let commit = fixture.decision(&snapshot, &actor, &scope, "commit");
    let read = fixture.read();
    let authority = NamespaceAuthority::seal(
        &fixture.policy,
        &initial,
        &read,
        NamespaceAdmission {
            activation: ActivationId("a1".into()),
            deadline: deadline(),
            recovery: &RecoverySelection::OriginalCaller,
            state_schema: &schema(),
        },
        fixture.namespaces.lifecycle().pin(&read).unwrap(),
    )
    .unwrap();
    let original = authority.ownership().clone();
    for (index, action) in [
        NamespaceTransition::Quiesce,
        NamespaceTransition::Retire,
        NamespaceTransition::Destroy,
        NamespaceTransition::Recreate {
            state_schema: schema(),
            quota: latent_state::namespace::NamespaceQuota::default(),
        },
    ]
    .into_iter()
    .enumerate()
    {
        let current = fixture.read();
        let mutation = NamespaceMutation::Transition {
            id: current.record().id.clone(),
            expected: current.record().version,
            action,
        };
        let prepared = fixture
            .namespaces
            .prepare(
                &fixture.database,
                NamespaceOperationContext {
                    tenant: TenantId("a".into()),
                    actor: "operator".into(),
                    operation_id: format!("transition-{index}"),
                },
                &mutation,
                0,
            )
            .unwrap();
        fixture.database.apply(prepared.batch).unwrap();
        assert!(authority
            .with_operation(&fixture.policy, &commit, &fixture.read(), "commit", || Ok(
                ()
            ))
            .is_err());
    }
    let pending = batch(&read, "stale");
    let acceptance = authority
        .prepare_commit_io(&fixture.policy, &commit, &read, &pending)
        .unwrap();
    assert!(matches!(
        fixture
            .database
            .apply_fenced(pending, || acceptance.accept().map(|_| ())),
        Err(FencedStoreError::Store(StoreError::Conflict))
    ));
    assert!(authority.cancellation().request()); // engine OCC never consumed it
    absent(&fixture, "stale");
    assert_eq!(original.incarnation, 1);
    assert_eq!(fixture.read().record().version.incarnation, 2);
    assert!(NamespaceAuthority::seal(
        &fixture.policy,
        &initial,
        &fixture.read(),
        NamespaceAdmission {
            activation: ActivationId("a2".into()),
            deadline: deadline(),
            recovery: &RecoverySelection::OriginalCaller,
            state_schema: &schema()
        },
        fixture.namespaces.lifecycle().pin(&read).unwrap(),
    )
    .is_err());
}

#[test]
fn result_replay_and_effect_inspection_require_current_subject_entity_and_policy() {
    let fixture = Fixture::new();
    let alice = principal("alice");
    let alice_scope = scope(
        &alice,
        Some("alice-order"),
        &RecoverySelection::OriginalCaller,
    );
    let bob = principal("bob");
    let bob_scope = scope(&bob, Some("bob-order"), &RecoverySelection::OriginalCaller);
    let snapshot = fixture.snapshot();
    let alice_decision = fixture.decision(&snapshot, &alice, &alice_scope, "read-result");
    let bob_decision = fixture.decision(&snapshot, &bob, &bob_scope, "read-result");
    let alice_effect = fixture.decision(&snapshot, &alice, &alice_scope, "inspect-effect");
    let bob_cancel = fixture.decision(&snapshot, &bob, &bob_scope, "cancel-command");
    let read = fixture.read();
    let alice_authority = NamespaceAuthority::seal(
        &fixture.policy,
        &alice_decision,
        &read,
        NamespaceAdmission {
            activation: ActivationId("lookup-a".into()),
            deadline: deadline(),
            recovery: &RecoverySelection::OriginalCaller,
            state_schema: &schema(),
        },
        fixture.namespaces.lifecycle().pin(&read).unwrap(),
    )
    .unwrap();
    let bob_authority = NamespaceAuthority::seal(
        &fixture.policy,
        &bob_decision,
        &read,
        NamespaceAdmission {
            activation: ActivationId("lookup-b".into()),
            deadline: deadline(),
            recovery: &RecoverySelection::OriginalCaller,
            state_schema: &schema(),
        },
        fixture.namespaces.lifecycle().pin(&read).unwrap(),
    )
    .unwrap();
    let historical = alice_authority.ownership().clone();
    let mut released = 0;
    alice_authority
        .with_recovery_access(
            &fixture.policy,
            &alice_decision,
            &read,
            "read-result",
            &historical,
            || {
                released += 1;
                Ok(())
            },
        )
        .unwrap();
    alice_authority
        .with_recovery_access(
            &fixture.policy,
            &alice_effect,
            &read,
            "inspect-effect",
            &historical,
            || {
                released += 1;
                Ok(())
            },
        )
        .unwrap();
    for (op, decision) in [
        ("read-result", &bob_decision),
        ("cancel-command", &bob_cancel),
    ] {
        assert!(bob_authority
            .with_recovery_access(&fixture.policy, decision, &read, op, &historical, || {
                released += 1;
                Ok(())
            })
            .is_err());
    }
    assert_eq!(released, 2);
    fixture.update(None, "withdraw-result-access");
    assert!(alice_authority
        .with_recovery_access(
            &fixture.policy,
            &alice_decision,
            &read,
            "read-result",
            &historical,
            || {
                released += 1;
                Ok(())
            }
        )
        .is_err());
    assert_eq!(released, 2);
}

#[test]
fn scoped_pages_cannot_cross_caller_entity_activation_or_owned_view_and_revoke_promptly() {
    let fixture = Fixture::new();
    let actor = principal("alice");
    let scope = scope(
        &actor,
        Some("alice-order"),
        &RecoverySelection::OriginalCaller,
    );
    let snapshot = fixture.snapshot();
    let query = fixture.decision(&snapshot, &actor, &scope, "acquire-query");
    let next = fixture.decision(&snapshot, &actor, &scope, "page-next");
    let read = fixture.read();
    let authority = NamespaceAuthority::seal(
        &fixture.policy,
        &query,
        &read,
        NamespaceAdmission {
            activation: ActivationId("reused-id".into()),
            deadline: deadline(),
            recovery: &RecoverySelection::OriginalCaller,
            state_schema: &schema(),
        },
        fixture.namespaces.lifecycle().pin(&read).unwrap(),
    )
    .unwrap();
    let other = NamespaceAuthority::seal(
        &fixture.policy,
        &query,
        &read,
        NamespaceAdmission {
            activation: ActivationId("reused-id".into()),
            deadline: deadline(),
            recovery: &RecoverySelection::OriginalCaller,
            state_schema: &schema(),
        },
        fixture.namespaces.lifecycle().pin(&read).unwrap(),
    )
    .unwrap();
    let mut page = authority.bind_page("owned-view-1").unwrap();
    page.advance(Some(b"position".to_vec())).unwrap();
    let mut released = 0;
    authority
        .with_page_access(&fixture.policy, &next, &read, &page, "owned-view-1", || {
            released += 1;
            Ok(())
        })
        .unwrap();
    assert_eq!(page.position(), Some(b"position".as_slice()));
    assert!(other
        .with_page_access(&fixture.policy, &next, &read, &page, "owned-view-1", || {
            released += 1;
            Ok(())
        })
        .is_err());
    assert!(authority
        .with_page_access(&fixture.policy, &next, &read, &page, "other-view", || {
            released += 1;
            Ok(())
        })
        .is_err());
    fixture.update(None, "revoke-page");
    assert!(authority
        .with_page_access(&fixture.policy, &next, &read, &page, "owned-view-1", || {
            released += 1;
            Ok(())
        })
        .is_err());
    assert_eq!(released, 1);
}

#[test]
fn forged_shared_selection_schema_mismatch_and_ungranted_publication_never_seal_authority() {
    let fixture = Fixture::new();
    let actor = principal("alice");
    let scope = scope(
        &actor,
        Some("alice-order"),
        &RecoverySelection::OriginalCaller,
    );
    let snapshot = fixture.snapshot();
    let initial = fixture.decision(&snapshot, &actor, &scope, "acquire-command");
    let read = fixture.read();
    assert!(NamespaceAuthority::seal(
        &fixture.policy,
        &initial,
        &read,
        NamespaceAdmission {
            activation: ActivationId("forged".into()),
            deadline: deadline(),
            recovery: &RecoverySelection::Shared {
                name: "team".into()
            },
            state_schema: &schema()
        },
        fixture.namespaces.lifecycle().pin(&read).unwrap(),
    )
    .is_err());
    assert!(NamespaceAuthority::seal(
        &fixture.policy,
        &initial,
        &read,
        NamespaceAdmission {
            activation: ActivationId("schema".into()),
            deadline: deadline(),
            recovery: &RecoverySelection::OriginalCaller,
            state_schema: &format!("sha256:{}", "9".repeat(64))
        },
        fixture.namespaces.lifecycle().pin(&read).unwrap(),
    )
    .is_err());
    assert!(fixture
        .decision_for(&snapshot, &actor, &scope, "acquire-command", &fixture.other)
        .is_err());
    let mut wrong_tenant = actor.clone();
    wrong_tenant.tenant = Some(TenantId("b".into()));
    wrong_tenant.claims.insert("tenant".into(), "a".into());
    assert!(fixture
        .decision_for(
            &snapshot,
            &wrong_tenant,
            &scope,
            "acquire-command",
            &fixture.publication
        )
        .is_err());
}

#[test]
fn delegated_scope_withdrawal_invalidates_execution_result_and_cancel_controls() {
    let fixture = Fixture::new();
    let actor = principal("alice");
    let selection = RecoverySelection::Delegated {
        delegation: "approved-1".into(),
        service: "integration".into(),
    };
    let delegated = scope(&actor, Some("alice-order"), &selection);
    let mut document = fixture.document.clone();
    document["rules"][0]["resources"]["scopes"]
        .as_array_mut()
        .unwrap()
        .push(serde_json::to_value(&delegated).unwrap());
    fixture.update(Some(&document), "approve-delegation");
    let snapshot = fixture.snapshot();
    let initial = fixture.decision(&snapshot, &actor, &delegated, "acquire-command");
    let result = fixture.decision(&snapshot, &actor, &delegated, "read-result");
    let cancel = fixture.decision(&snapshot, &actor, &delegated, "cancel-command");
    let read = fixture.read();
    let authority = NamespaceAuthority::seal(
        &fixture.policy,
        &initial,
        &read,
        NamespaceAdmission {
            activation: ActivationId("delegated".into()),
            deadline: deadline(),
            recovery: &selection,
            state_schema: &schema(),
        },
        fixture.namespaces.lifecycle().pin(&read).unwrap(),
    )
    .unwrap();
    let owner = authority.ownership().clone();
    authority
        .with_recovery_access(
            &fixture.policy,
            &result,
            &read,
            "read-result",
            &owner,
            || Ok(()),
        )
        .unwrap();
    fixture.update(Some(&fixture.document), "withdraw-delegation");
    for (op, decision) in [("read-result", &result), ("cancel-command", &cancel)] {
        assert!(authority
            .with_recovery_access(&fixture.policy, decision, &read, op, &owner, || Ok(()))
            .is_err());
    }
}

#[test]
fn lifecycle_domain_replay_is_currently_authorized_and_active_owners_block_retirement() {
    let fixture = Fixture::new();
    let actor = principal("alice");
    let scope = scope(&actor, None, &RecoverySelection::OriginalCaller);
    approve_management(&fixture, &scope);
    let snapshot = fixture.snapshot();
    let quiesce = fixture.decision(&snapshot, &actor, &scope, "namespace-quiesce");
    let retire = fixture.decision(&snapshot, &actor, &scope, "namespace-retire");
    let inspection = fixture.decision(&snapshot, &actor, &scope, "namespace-inspect");
    let owner = fixture.namespaces.lifecycle().pin(&fixture.read()).unwrap();
    let quiesce_mutation = lifecycle_mutation(&fixture.read(), NamespaceTransition::Quiesce);
    let prepared = NamespaceControl::prepare(
        &fixture.policy,
        &quiesce,
        &fixture.namespaces,
        &fixture.database,
        NamespaceControlRequest {
            mutation: &quiesce_mutation,
            operation_id: "quiesce",
            inspection: None,
        },
        1,
    )
    .unwrap();
    let (receipt, replay) = persist_control(&fixture, prepared);
    assert!(!replay);
    assert!(NamespaceControl::prepare(
        &fixture.policy,
        &quiesce,
        &fixture.namespaces,
        &fixture.database,
        NamespaceControlRequest {
            mutation: &quiesce_mutation,
            operation_id: "quiesce",
            inspection: None
        },
        0,
    )
    .is_err());
    let replay = NamespaceControl::prepare(
        &fixture.policy,
        &quiesce,
        &fixture.namespaces,
        &fixture.database,
        NamespaceControlRequest {
            mutation: &quiesce_mutation,
            operation_id: "quiesce",
            inspection: Some(&inspection),
        },
        1,
    )
    .unwrap();
    let (historical, replay) = persist_control(&fixture, replay);
    assert!(replay);
    assert_eq!(receipt, historical);
    let mutation = NamespaceMutation::Transition {
        id: receipt.record.id,
        expected: receipt.record.version,
        action: NamespaceTransition::Retire,
    };
    let prepared = NamespaceControl::prepare(
        &fixture.policy,
        &retire,
        &fixture.namespaces,
        &fixture.database,
        NamespaceControlRequest {
            mutation: &mutation,
            operation_id: "retire",
            inspection: None,
        },
        0,
    )
    .unwrap();
    let (batch, _, _, fence) = prepared.into_parts();
    assert!(matches!(
        fixture
            .database
            .apply_fenced(batch, || fence.accept().map(|_| ())),
        Err(FencedStoreError::Fence(
            latent_state::namespace::NamespaceError::InUse
        ))
    ));
    assert_eq!(fixture.read().record().status, NamespaceStatus::Quiescing);
    drop(owner);
    fixture.update(None, "revoke-management");
    assert!(NamespaceControl::prepare(
        &fixture.policy,
        &quiesce,
        &fixture.namespaces,
        &fixture.database,
        NamespaceControlRequest {
            mutation: &quiesce_mutation,
            operation_id: "quiesce",
            inspection: Some(&inspection)
        },
        0
    )
    .is_err());
}

#[test]
fn owned_activation_survives_borrowed_snapshot_drop_but_replacement_policy_cannot_refresh_its_grant(
) {
    let fixture = Fixture::new();
    let read = fixture.read();
    let authority = {
        let actor = principal("alice");
        let scope = scope(
            &actor,
            Some("alice-order"),
            &RecoverySelection::OriginalCaller,
        );
        let snapshot = fixture.snapshot();
        let initial = fixture.decision(&snapshot, &actor, &scope, "acquire-command");
        NamespaceAuthority::seal(
            &fixture.policy,
            &initial,
            &read,
            NamespaceAdmission {
                activation: ActivationId("owned".into()),
                deadline: deadline(),
                recovery: &RecoverySelection::OriginalCaller,
                state_schema: &schema(),
            },
            fixture.namespaces.lifecycle().pin(&read).unwrap(),
        )
        .unwrap()
    };
    // The owned authority is movable to the fixed worker and retains metadata
    // leases only; the protected native engine still has its single fixture owner.
    let authority = std::thread::scope(|workers| workers.spawn(move || authority).join().unwrap());
    assert_eq!(Arc::strong_count(&fixture.database), 1);
    assert_eq!(fixture.namespaces.lifecycle().retained_owners(), 1);
    let actor = principal("alice");
    let scope = scope(
        &actor,
        Some("alice-order"),
        &RecoverySelection::OriginalCaller,
    );
    let snapshot = fixture.snapshot();
    let get = fixture.decision(&snapshot, &actor, &scope, "get");
    authority
        .with_operation(&fixture.policy, &get, &read, "get", || Ok(()))
        .unwrap();
    fixture.update(Some(&fixture.document), "same-rules-new-revision");
    let current = fixture.snapshot();
    let fresh_get = fixture.decision(&current, &actor, &scope, "get");
    assert!(authority
        .with_operation(&fixture.policy, &fresh_get, &read, "get", || Ok(()))
        .is_err());
    drop(authority);
    assert_eq!(fixture.namespaces.lifecycle().retained_owners(), 0);
}

#[test]
fn final_effect_guard_is_held_through_cancellation_cas_and_failure_does_not_consume_acceptance() {
    use latent_state::namespace::NamespaceError;
    use std::sync::{
        atomic::{AtomicBool, Ordering},
        MutexGuard,
    };
    struct EffectGuard<'a> {
        _held: MutexGuard<'a, ()>,
        cancellation: CommitCancellation,
        dropped: &'a AtomicBool,
    }
    impl Drop for EffectGuard<'_> {
        fn drop(&mut self) {
            assert!(!self.cancellation.request());
            self.dropped.store(true, Ordering::Release);
        }
    }
    let fixture = Fixture::new();
    let actor = principal("alice");
    let scope = scope(
        &actor,
        Some("alice-order"),
        &RecoverySelection::OriginalCaller,
    );
    let snapshot = fixture.snapshot();
    let initial = fixture.decision(&snapshot, &actor, &scope, "acquire-command");
    let commit = fixture.decision(&snapshot, &actor, &scope, "commit");
    let read = fixture.read();
    let authority = NamespaceAuthority::seal(
        &fixture.policy,
        &initial,
        &read,
        NamespaceAdmission {
            activation: ActivationId("effect-guard".into()),
            deadline: deadline(),
            recovery: &RecoverySelection::OriginalCaller,
            state_schema: &schema(),
        },
        fixture.namespaces.lifecycle().pin(&read).unwrap(),
    )
    .unwrap();
    let rejected = batch(&read, "effect-invalid");
    let acceptance = authority
        .prepare_commit_io(&fixture.policy, &commit, &read, &rejected)
        .unwrap();
    assert!(matches!(
        fixture.database.apply_fenced(rejected, || acceptance
            .accept_with(|| Err::<(), _>(NamespaceError::Unavailable))),
        Err(FencedStoreError::Fence(NamespaceError::Unavailable))
    ));
    absent(&fixture, "effect-invalid");
    authority
        .with_operation(&fixture.policy, &commit, &read, "commit", || Ok(()))
        .unwrap();
    let valid = batch(&read, "effect-valid");
    let acceptance = authority
        .prepare_commit_io(&fixture.policy, &commit, &read, &valid)
        .unwrap();
    let rules = std::sync::Mutex::new(());
    let dropped = AtomicBool::new(false);
    fixture
        .database
        .apply_fenced(valid, || {
            acceptance.accept_with(|| {
                Ok(EffectGuard {
                    _held: rules.try_lock().unwrap(),
                    cancellation: authority.cancellation(),
                    dropped: &dropped,
                })
            })?;
            assert!(dropped.load(Ordering::Acquire));
            assert!(rules.try_lock().is_ok());
            Ok::<_, NamespaceError>(())
        })
        .unwrap();
    assert!(!authority.cancellation().request());
}

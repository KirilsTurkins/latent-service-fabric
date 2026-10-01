use super::*;

fn limits() -> Limits {
    Limits {
        key_bytes: 32,
        value_bytes: 128,
        result_bytes: 64,
        scan_entries: 8,
        scan_bytes: 256,
        mutations: 8,
        intents: 8,
        envelope_bytes: 512,
        admitted_commands: 16,
        recovery_bytes: 64,
        support_operations: 8,
    }
}

fn model() -> TransactionModel {
    TransactionModel::new("tenant-a".into(), "ledger".into(), limits()).unwrap()
}

fn scope(caller: &str) -> Scope {
    Scope {
        tenant: "tenant-a".into(),
        namespace: "ledger".into(),
        incarnation: 1,
        recovery_scope: format!("caller:{caller}"),
        operation: "adjust".into(),
        entity: Some("account-1".into()),
    }
}

fn permissions() -> Permissions {
    Permissions {
        command: true,
        query: true,
        result_read: true,
        result_policy: 1,
    }
}

fn authority(model: &mut TransactionModel) -> Authority {
    model.grant(scope("alice"), permissions()).unwrap()
}

fn key(caller_key: &str) -> CommandKey {
    CommandKey {
        scope: scope("alice"),
        caller_key: caller_key.into(),
    }
}

fn body() -> CommandBody {
    CommandBody {
        bytes: b"adjust=1".to_vec(),
        expected_version: None,
    }
}

fn begin(
    model: &mut TransactionModel,
    authority: &Authority,
    caller_key: &str,
    activation: u64,
) -> CommandAttemptId {
    match model
        .admit(authority, key(caller_key), body(), activation, None)
        .unwrap()
    {
        Admission::Execute(attempt) => attempt,
        Admission::Existing(outcome) => panic!("expected fresh execution, got {outcome:?}"),
    }
}

fn eligible(
    model: &mut TransactionModel,
    attempt: CommandAttemptId,
    outcome: GuestOutcome,
    output: &[u8],
) {
    model
        .guest_return(attempt, outcome, output.to_vec())
        .unwrap();
    model.validate_outputs(attempt, true).unwrap();
    model.seal(attempt).unwrap();
}

fn commit(model: &mut TransactionModel, attempt: CommandAttemptId, output: &[u8]) -> CommitReceipt {
    eligible(model, attempt, GuestOutcome::Successful, output);
    model.begin_physical_commit(attempt).unwrap();
    model.physical_commit(attempt).unwrap()
}

#[test]
fn one_activation_has_one_tenant_namespace_and_entity_scope() {
    let mut model = model();
    let grant = authority(&mut model);
    let first = begin(&mut model, &grant, "one", 1);
    let mut other_entity = scope("alice");
    other_entity.entity = Some("account-2".into());
    let other = model.grant(other_entity.clone(), permissions()).unwrap();
    let second_key = CommandKey {
        scope: other_entity,
        caller_key: "two".into(),
    };
    assert_eq!(
        model.admit(&other, second_key, body(), 1, None),
        Err(ModelError::Invalid)
    );
    let mut foreign_tenant = scope("alice");
    foreign_tenant.tenant = "tenant-b".into();
    assert_eq!(
        model.grant(foreign_tenant, permissions()).unwrap_err(),
        ModelError::ScopeMismatch
    );
    let mut foreign_namespace = scope("alice");
    foreign_namespace.namespace = "other-ledger".into();
    assert_eq!(
        model.grant(foreign_namespace, permissions()).unwrap_err(),
        ModelError::ScopeMismatch
    );
    assert_eq!(model.get(first, b"balance").unwrap(), None);
    assert_eq!(model.command_count(), 1);
}

#[test]
fn snapshot_reads_and_read_your_writes_are_consistent_and_bounded() {
    let mut model = model();
    let grant = authority(&mut model);
    let first = begin(&mut model, &grant, "one", 1);
    model
        .put(first, b"account/a".to_vec(), b"one".to_vec())
        .unwrap();
    model
        .put(first, b"account/b".to_vec(), b"two".to_vec())
        .unwrap();
    assert_eq!(
        model.get(first, b"account/a").unwrap(),
        Some(b"one".to_vec())
    );
    assert_eq!(model.scan(first, b"account/", 8).unwrap().len(), 2);
    model.delete(first, b"account/a".to_vec()).unwrap();
    assert_eq!(model.get(first, b"account/a").unwrap(), None);
    assert_eq!(
        model.scan(first, b"account/", 8).unwrap(),
        vec![(b"account/b".to_vec(), b"two".to_vec())]
    );
    assert_eq!(model.scan(first, b"", 9), Err(ModelError::Limit));
    assert_eq!(
        model.put(first, vec![0; 33], vec![]),
        Err(ModelError::Limit)
    );
    assert_eq!(
        model.put(first, b"large".to_vec(), vec![0; 129]),
        Err(ModelError::Limit)
    );
    commit(&mut model, first, b"ok");
    let mut view = model.acquire_query(&grant).unwrap();
    assert_eq!(model.query_get(&mut view, b"account/a").unwrap(), None);
    assert_eq!(
        model.query_get(&mut view, b"account/b").unwrap(),
        Some(b"two".to_vec())
    );
}

#[test]
fn namespace_fence_detects_missing_reads_blind_writes_aba_and_scan_phantoms() {
    for observation in 0..4 {
        let mut model = model();
        let grant = authority(&mut model);
        let stale = begin(&mut model, &grant, "stale", 1);
        match observation {
            0 => assert_eq!(model.get(stale, b"missing").unwrap(), None),
            1 => model
                .put(stale, b"blind".to_vec(), b"stale".to_vec())
                .unwrap(),
            2 => assert_eq!(model.get(stale, b"aba").unwrap(), None),
            _ => assert!(model.scan(stale, b"prefix/", 8).unwrap().is_empty()),
        }
        let writer = begin(&mut model, &grant, "writer", 2);
        let changed_key = [b"missing".as_slice(), b"blind", b"aba", b"prefix/new"][observation];
        model
            .put(writer, changed_key.to_vec(), b"fresh".to_vec())
            .unwrap();
        commit(&mut model, writer, b"written");
        if observation == 2 {
            let delete = begin(&mut model, &grant, "delete", 3);
            model.delete(delete, b"aba".to_vec()).unwrap();
            commit(&mut model, delete, b"deleted");
            let recreate = begin(&mut model, &grant, "recreate", 4);
            model
                .put(recreate, b"aba".to_vec(), b"fresh".to_vec())
                .unwrap();
            commit(&mut model, recreate, b"recreated");
        }
        // Snapshot equality, an absent key or a bounded page alone never proves serializability.
        eligible(&mut model, stale, GuestOutcome::Successful, b"stale");
        assert_eq!(
            model.begin_physical_commit(stale),
            Err(ModelError::Conflict)
        );
        assert!(matches!(
            model.lookup(&grant, &key("stale")).unwrap().outcome,
            DurableOutcome::TechnicalAborted {
                owners_retired: false,
                ..
            }
        ));
        assert_eq!(
            model.admit(&grant, key("stale"), body(), 5, None).unwrap(),
            Admission::Existing(Box::new(
                model.lookup(&grant, &key("stale")).unwrap().outcome
            ))
        );
    }
}

#[test]
fn cancellation_and_commit_fence_have_explicit_winners() {
    for cancellation_step in 0..4 {
        let mut model = model();
        let grant = authority(&mut model);
        let attempt = begin(&mut model, &grant, "race", 1);
        model
            .put(attempt, b"balance".to_vec(), b"1".to_vec())
            .unwrap();
        model.stage_intent(attempt, b"event".to_vec()).unwrap();
        if cancellation_step == 0 {
            assert_eq!(
                model.cancel(attempt).unwrap(),
                Cancellation::AbortedBeforeCommit
            );
        } else {
            eligible(&mut model, attempt, GuestOutcome::Successful, b"result");
            if cancellation_step == 1 {
                assert_eq!(
                    model.cancel(attempt).unwrap(),
                    Cancellation::AbortedBeforeCommit
                );
            } else {
                model.begin_physical_commit(attempt).unwrap();
                if cancellation_step == 2 {
                    assert_eq!(
                        model.cancel(attempt).unwrap(),
                        Cancellation::CommitMayHaveOccurred
                    );
                }
                let receipt = model.physical_commit(attempt).unwrap();
                assert!(receipt.business_committed);
                assert_eq!(
                    model.cancel(attempt).unwrap(),
                    Cancellation::AlreadyTerminal
                );
            }
        }
        let result = model.lookup(&grant, &key("race")).unwrap();
        let mut view = model.acquire_query(&grant).unwrap();
        if cancellation_step < 2 {
            assert!(matches!(
                result.outcome,
                DurableOutcome::TechnicalAborted { .. }
            ));
            assert_eq!(model.query_get(&mut view, b"balance").unwrap(), None);
            assert_eq!(model.intent_count(), 0);
        } else {
            assert!(matches!(result.outcome, DurableOutcome::Committed(_)));
            assert_eq!(
                model.query_get(&mut view, b"balance").unwrap(),
                Some(b"1".to_vec())
            );
            assert_eq!(model.intent_count(), 1);
        }
        assert_eq!(model.cleanup_status(attempt).unwrap(), CleanupStatus::Owned);
    }
}

#[test]
fn durable_commit_lost_response_and_quarantine_keep_original_result() {
    let mut model = model();
    let grant = authority(&mut model);
    let attempt = begin(&mut model, &grant, "lost", 1);
    model
        .put(attempt, b"balance".to_vec(), b"1".to_vec())
        .unwrap();
    model.stage_intent(attempt, b"event".to_vec()).unwrap();
    let receipt = commit(&mut model, attempt, b"original-result");
    // No response publication occurs before crash; cleanup failure is independent.
    model.cleanup(attempt, CleanupStatus::Quarantined).unwrap();
    assert_eq!(
        model.lookup(&grant, &key("lost")).unwrap().outcome,
        DurableOutcome::Committed(receipt.clone())
    );
    model.reopen().unwrap();
    let recovered = model.lookup(&grant, &key("lost")).unwrap();
    assert_eq!(recovered.payload, Some(b"original-result".to_vec()));
    assert_eq!(recovered.outcome, DurableOutcome::Committed(receipt));
    assert!(matches!(
        model.admit(&grant, key("lost"), body(), 2, None).unwrap(),
        Admission::Existing(outcome) if matches!(*outcome, DurableOutcome::Committed(_))
    ));
    assert_eq!(model.intent_count(), 1);
}

#[test]
fn changed_body_and_precondition_cannot_replace_a_retained_command() {
    let mut model = model();
    let grant = authority(&mut model);
    let attempt = begin(&mut model, &grant, "same", 1);
    commit(&mut model, attempt, b"original");
    for changed in [
        CommandBody {
            bytes: b"adjust=2".to_vec(),
            expected_version: None,
        },
        CommandBody {
            bytes: body().bytes,
            expected_version: Some(model.version()),
        },
    ] {
        assert_eq!(
            model.admit(&grant, key("same"), changed, 2, None),
            Err(ModelError::ChangedBody)
        );
    }
    assert_eq!(
        model.lookup(&grant, &key("same")).unwrap().payload,
        Some(b"original".to_vec())
    );
}

#[test]
fn immediate_effect_is_denied_even_when_a_conflict_will_follow() {
    let mut model = model();
    let grant = authority(&mut model);
    let stale = begin(&mut model, &grant, "stale", 1);
    for class in [
        CapabilityClass::ImmediateApplicationEffect,
        CapabilityClass::UnsupportedSynchronousChild,
        CapabilityClass::Unclassified,
    ] {
        assert_eq!(
            model.capability(stale, class, true),
            Err(ModelError::ForbiddenCapability)
        );
    }
    let writer = begin(&mut model, &grant, "other", 2);
    commit(&mut model, writer, b"fresh");
    eligible(&mut model, stale, GuestOutcome::Successful, b"stale");
    assert_eq!(
        model.begin_physical_commit(stale),
        Err(ModelError::Conflict)
    );
    assert_eq!(model.intent_count(), 0);
}

#[test]
fn runtime_support_is_narrow_and_required_work_precedes_sealed_handoff() {
    let mut model = model();
    let grant = authority(&mut model);
    let attempt = begin(&mut model, &grant, "managed", 1);
    for class in [
        CapabilityClass::RuntimeClock,
        CapabilityClass::RuntimeEntropy,
        CapabilityClass::RuntimeLogging,
        CapabilityClass::RuntimeGc,
        CapabilityClass::RuntimeSuspension,
    ] {
        model.capability(attempt, class, true).unwrap();
    }
    assert_eq!(
        model.capability(attempt, CapabilityClass::ReviewedReadOnly, false),
        Err(ModelError::ForbiddenCapability)
    );
    model.accept_required_work(attempt).unwrap();
    model
        .guest_return(attempt, GuestOutcome::Successful, b"root-returned".to_vec())
        .unwrap();
    assert_eq!(model.seal(attempt), Err(ModelError::NotEligible));
    model.validate_outputs(attempt, true).unwrap();
    assert_eq!(model.seal(attempt), Err(ModelError::NotEligible));
    model
        .put(attempt, b"continuation".to_vec(), b"settled".to_vec())
        .unwrap();
    model.settle_required_work(attempt).unwrap();
    model.seal(attempt).unwrap();
    assert_eq!(
        model.stage_intent(attempt, b"late".to_vec()),
        Err(ModelError::StagingClosed)
    );
    assert_eq!(
        model.put(attempt, b"late".to_vec(), b"write".to_vec()),
        Err(ModelError::StagingClosed)
    );
    model.begin_physical_commit(attempt).unwrap();
    model.physical_commit(attempt).unwrap();
    model.cleanup(attempt, CleanupStatus::Retired).unwrap();
    assert_eq!(
        model.settle_required_work(attempt),
        Err(ModelError::StagingClosed)
    );
}

#[test]
fn invalid_output_trap_and_exhaustion_discard_business_plan() {
    for failure in 0..3 {
        let mut model = model();
        let grant = authority(&mut model);
        let attempt = begin(&mut model, &grant, "failure", 1);
        model
            .put(attempt, b"balance".to_vec(), b"1".to_vec())
            .unwrap();
        model.stage_intent(attempt, b"event".to_vec()).unwrap();
        match failure {
            0 => model
                .guest_return(attempt, GuestOutcome::TechnicalFailure, b"trap".to_vec())
                .unwrap(),
            1 => {
                model
                    .guest_return(attempt, GuestOutcome::Successful, b"invalid".to_vec())
                    .unwrap();
                assert_eq!(
                    model.validate_outputs(attempt, false),
                    Err(ModelError::Invalid)
                );
            }
            _ => {
                model
                    .guest_return(attempt, GuestOutcome::Successful, vec![0; 65])
                    .unwrap();
                model.validate_outputs(attempt, true).unwrap();
                assert_eq!(model.seal(attempt), Err(ModelError::Limit));
            }
        }
        assert!(matches!(
            model.lookup(&grant, &key("failure")).unwrap().outcome,
            DurableOutcome::TechnicalAborted { .. }
        ));
        assert_eq!(model.intent_count(), 0);
        let mut view = model.acquire_query(&grant).unwrap();
        assert_eq!(model.query_get(&mut view, b"balance").unwrap(), None);
    }
}

#[test]
fn same_tenant_other_user_and_revoked_business_policy_cannot_replay() {
    let mut model = model();
    let alice = authority(&mut model);
    let attempt = begin(&mut model, &alice, "secret", 1);
    commit(&mut model, attempt, b"alice-result");
    let bob = model.grant(scope("bob"), permissions()).unwrap();
    assert_eq!(
        model.lookup(&bob, &key("secret")),
        Err(ModelError::PermissionDenied)
    );
    let revoked = model
        .grant(
            scope("alice"),
            Permissions {
                result_read: false,
                ..permissions()
            },
        )
        .unwrap();
    assert_eq!(
        model.lookup(&revoked, &key("secret")),
        Err(ModelError::PermissionDenied)
    );
    assert_eq!(
        model.lookup(&alice, &key("secret")),
        Err(ModelError::PermissionDenied)
    );
    let changed_policy = model
        .grant(
            scope("alice"),
            Permissions {
                result_policy: 2,
                ..permissions()
            },
        )
        .unwrap();
    assert_eq!(
        model.lookup(&changed_policy, &key("secret")),
        Err(ModelError::PermissionDenied)
    );
}

#[test]
fn stable_caller_identity_survives_grant_rotation_and_shared_scope_needs_explicit_grant() {
    let mut model = model();
    let initial = authority(&mut model);
    let attempt = begin(&mut model, &initial, "stable", 1);
    commit(&mut model, attempt, b"original");
    // Authentication/session renewal grants the same stable caller scope, rather
    // than making a fresh command from a route/revision/session credential.
    let renewed = model.grant(scope("alice"), permissions()).unwrap();
    assert_eq!(
        model.lookup(&renewed, &key("stable")).unwrap().payload,
        Some(b"original".to_vec())
    );
    let mut shared_scope = scope("alice");
    shared_scope.recovery_scope = "service:billing".into();
    let shared_key = CommandKey {
        scope: shared_scope.clone(),
        caller_key: "shared".into(),
    };
    assert_eq!(
        model.admit(&renewed, shared_key.clone(), body(), 2, None),
        Err(ModelError::PermissionDenied)
    );
    let delegated = model.grant(shared_scope, permissions()).unwrap();
    let Admission::Execute(shared) = model
        .admit(&delegated, shared_key.clone(), body(), 2, None)
        .unwrap()
    else {
        panic!("explicit delegated grant expected");
    };
    commit(&mut model, shared, b"shared-result");
    assert_eq!(
        model.lookup(&renewed, &shared_key),
        Err(ModelError::PermissionDenied)
    );
    assert_eq!(
        model.lookup(&delegated, &shared_key).unwrap().payload,
        Some(b"shared-result".to_vec())
    );
}

#[test]
fn final_authority_fence_rejects_revocation_before_physical_commit() {
    let mut model = model();
    let grant = authority(&mut model);
    let attempt = begin(&mut model, &grant, "revoked", 1);
    model
        .put(attempt, b"balance".to_vec(), b"1".to_vec())
        .unwrap();
    eligible(&mut model, attempt, GuestOutcome::Successful, b"result");
    model
        .grant(
            scope("alice"),
            Permissions {
                command: false,
                ..permissions()
            },
        )
        .unwrap();
    assert_eq!(
        model.begin_physical_commit(attempt),
        Err(ModelError::PermissionDenied)
    );
    assert_eq!(
        model.cancel(attempt).unwrap(),
        Cancellation::AbortedBeforeCommit
    );
    assert_eq!(model.intent_count(), 0);
    assert_eq!(model.version().generation, 0);
}

#[test]
fn lost_business_rejection_survives_later_state_changes_and_duplicate_submission() {
    let mut model = model();
    let grant = authority(&mut model);
    let rejected = begin(&mut model, &grant, "rejected", 1);
    model
        .put(rejected, b"balance".to_vec(), b"should-discard".to_vec())
        .unwrap();
    model
        .stage_intent(rejected, b"should-discard".to_vec())
        .unwrap();
    eligible(
        &mut model,
        rejected,
        GuestOutcome::TerminalBusinessRejection,
        b"insufficient-funds",
    );
    model.begin_physical_commit(rejected).unwrap();
    let receipt = model.physical_commit(rejected).unwrap();
    assert!(!receipt.business_committed);
    assert!(receipt.effects.is_empty());
    let writer = begin(&mut model, &grant, "later", 2);
    model
        .put(writer, b"balance".to_vec(), b"100".to_vec())
        .unwrap();
    commit(&mut model, writer, b"credited");
    model.reopen().unwrap();
    let replay = model
        .admit(&grant, key("rejected"), body(), 3, None)
        .unwrap();
    assert_eq!(
        replay,
        Admission::Existing(Box::new(DurableOutcome::BusinessRejected(receipt)))
    );
    assert_eq!(
        model.lookup(&grant, &key("rejected")).unwrap().payload,
        Some(b"insufficient-funds".to_vec())
    );
    assert_eq!(model.intent_count(), 0);
}

#[test]
fn explicit_retry_requires_retired_owners_and_one_attempt_fence_winner() {
    let mut model = model();
    let grant = authority(&mut model);
    let old = begin(&mut model, &grant, "retry", 1);
    model
        .put(old, b"balance".to_vec(), b"old".to_vec())
        .unwrap();
    model.cancel(old).unwrap();
    assert_eq!(
        model.abort_fence(&grant, &key("retry")),
        Err(ModelError::AbortUnproven)
    );
    model.cleanup(old, CleanupStatus::Retired).unwrap();
    let fence = model.abort_fence(&grant, &key("retry")).unwrap();
    let retry = model.retry(&grant, &body(), &fence, 2).unwrap();
    assert_eq!(retry.generation(), old.generation() + 1);
    assert_eq!(
        model.retry(&grant, &body(), &fence, 3),
        Err(ModelError::AbortUnproven)
    );
    assert_eq!(
        model.put(old, b"stale".to_vec(), b"late".to_vec()),
        Err(ModelError::StagingClosed)
    );
    assert_eq!(model.physical_commit(old), Err(ModelError::StaleAttempt));
    model
        .put(retry, b"balance".to_vec(), b"retry".to_vec())
        .unwrap();
    commit(&mut model, retry, b"retried");
    assert_eq!(model.command_count(), 1);
}

#[test]
fn quarantine_unknown_and_uncertain_io_are_not_abort_proof() {
    let mut model = model();
    let grant = authority(&mut model);
    assert_eq!(
        model.lookup(&grant, &key("absent")).unwrap().outcome,
        DurableOutcome::Unknown
    );
    assert_eq!(
        model.abort_fence(&grant, &key("absent")),
        Err(ModelError::AbortUnproven)
    );
    let uncertain = begin(&mut model, &grant, "uncertain", 1);
    eligible(&mut model, uncertain, GuestOutcome::Successful, b"result");
    model.begin_physical_commit(uncertain).unwrap();
    model.uncertain_commit(uncertain).unwrap();
    assert_eq!(
        model.cancel(uncertain).unwrap(),
        Cancellation::CommitMayHaveOccurred
    );
    assert_eq!(
        model.abort_fence(&grant, &key("uncertain")),
        Err(ModelError::AbortUnproven)
    );
    assert_eq!(
        model.prove_uncommitted_after_reopen(&grant, &key("uncertain")),
        Err(ModelError::AbortUnproven)
    );
    let aborted = begin(&mut model, &grant, "quarantine", 2);
    model.cancel(aborted).unwrap();
    model.cleanup(aborted, CleanupStatus::Quarantined).unwrap();
    assert_eq!(
        model.abort_fence(&grant, &key("quarantine")),
        Err(ModelError::AbortUnproven)
    );
}

#[test]
fn ordinary_restart_requires_explicit_recovery_and_fences_stale_completion() {
    let mut model = model();
    let grant = authority(&mut model);
    let old = begin(&mut model, &grant, "restart", 1);
    model
        .put(old, b"balance".to_vec(), b"uncommitted".to_vec())
        .unwrap();
    let version = model.version();
    model.reopen().unwrap();
    assert_eq!(model.version(), version);
    assert_eq!(model.physical_commit(old), Err(ModelError::StaleAttempt));
    assert!(matches!(
        model.lookup(&grant, &key("restart")).unwrap().outcome,
        DurableOutcome::RecoveryRequired(_)
    ));
    assert_eq!(
        model.abort_fence(&grant, &key("restart")),
        Err(ModelError::AbortUnproven)
    );
    model
        .prove_uncommitted_after_reopen(&grant, &key("restart"))
        .unwrap();
    let fence = model.abort_fence(&grant, &key("restart")).unwrap();
    let retry = model.retry(&grant, &body(), &fence, 2).unwrap();
    assert_eq!(model.get(retry, b"balance").unwrap(), None);
    commit(&mut model, retry, b"explicitly-retried");
}

#[test]
fn fresh_query_after_acknowledged_commit_and_restart_needs_no_command_row() {
    let mut model = model();
    let grant = authority(&mut model);
    let old_view = model.acquire_query(&grant).unwrap();
    let attempt = begin(&mut model, &grant, "write", 1);
    model
        .put(attempt, b"balance".to_vec(), b"42".to_vec())
        .unwrap();
    let receipt = commit(&mut model, attempt, b"acknowledged");
    assert!(old_view.version().generation < receipt.version.generation);
    let count = model.command_count();
    for restart in [false, true] {
        if restart {
            model.reopen().unwrap();
        }
        let mut fresh = model.acquire_query(&grant).unwrap();
        assert_eq!(fresh.version().incarnation, receipt.version.incarnation);
        assert!(fresh.version().generation >= receipt.version.generation);
        assert_eq!(
            model.query_get(&mut fresh, b"balance").unwrap(),
            Some(b"42".to_vec())
        );
        assert_eq!(model.command_count(), count);
    }
}

#[test]
fn stale_edit_precondition_is_distinct_from_occ_and_is_not_silently_refreshed() {
    let mut model = model();
    let grant = authority(&mut model);
    let screen_version = model.acquire_query(&grant).unwrap().version();
    let writer = begin(&mut model, &grant, "writer", 1);
    commit(&mut model, writer, b"written");
    let edit = CommandBody {
        bytes: body().bytes,
        expected_version: Some(screen_version),
    };
    assert_eq!(
        model.admit(&grant, key("edit"), edit, 2, None),
        Err(ModelError::StaleEdit)
    );
    assert_eq!(
        model.lookup(&grant, &key("edit")).unwrap().outcome,
        DurableOutcome::Unknown
    );
    assert_eq!(model.command_count(), 1);
}

#[test]
fn older_history_restore_changes_incarnation_drops_grants_and_starts_paused() {
    let mut model = model();
    let grant = authority(&mut model);
    let historical = model.durable_image();
    let attempt = begin(&mut model, &grant, "newer", 1);
    model
        .stage_intent(attempt, b"may-have-been-sent".to_vec())
        .unwrap();
    commit(&mut model, attempt, b"acknowledged");
    model.reopen().unwrap();
    model.restore_older(historical, 2).unwrap();
    assert_eq!(model.version().incarnation, 2);
    assert_eq!(
        model.lookup(&grant, &key("newer")),
        Err(ModelError::ScopeMismatch)
    );
    let mut current_scope = scope("alice");
    current_scope.incarnation = 2;
    let current = model.grant(current_scope.clone(), permissions()).unwrap();
    let current_key = CommandKey {
        scope: current_scope,
        caller_key: "newer".into(),
    };
    assert_eq!(
        model.admit(&current, current_key, body(), 2, None),
        Err(ModelError::RestorePaused)
    );
    assert_eq!(model.intent_count(), 0); // external reality is not rewound by this historical image.
}

#[test]
fn optional_inbox_is_atomic_with_commit_or_rejection_and_acknowledged_afterward() {
    for rejection in [false, true] {
        let mut model = model();
        let grant = authority(&mut model);
        let input = ProcessedInputIdentity {
            binding: "events-v1".into(),
            message_id: "stable-source-id".into(),
        };
        let Admission::Execute(attempt) = model
            .admit(&grant, key("input"), body(), 1, Some(input.clone()))
            .unwrap()
        else {
            panic!("fresh input expected");
        };
        assert_eq!(
            model.acknowledge_input(&key("input")),
            Err(ModelError::AcknowledgementBeforeDurableDisposition)
        );
        model
            .put(attempt, b"balance".to_vec(), b"1".to_vec())
            .unwrap();
        model.stage_intent(attempt, b"event".to_vec()).unwrap();
        let outcome = if rejection {
            GuestOutcome::TerminalBusinessRejection
        } else {
            GuestOutcome::Successful
        };
        eligible(&mut model, attempt, outcome, b"disposition");
        model.begin_physical_commit(attempt).unwrap();
        let receipt = model.physical_commit(attempt).unwrap();
        model.acknowledge_input(&key("input")).unwrap();
        assert_eq!(receipt.business_committed, !rejection);
        assert_eq!(model.intent_count(), usize::from(!rejection));
        model.reopen().unwrap();
        assert_eq!(
            model.admit(&grant, key("redelivery"), body(), 2, Some(input)),
            Err(ModelError::DuplicateInput)
        );
        model.acknowledge_input(&key("input")).unwrap();
    }
}

#[test]
fn retained_old_intent_decodes_after_independent_state_schema_upgrade() {
    let mut model = model();
    let grant = authority(&mut model);
    let attempt = begin(&mut model, &grant, "old-format", 1);
    model.stage_intent(attempt, b"old-intent".to_vec()).unwrap();
    let receipt = commit(&mut model, attempt, b"old-result");
    let v1 = BTreeSet::from([1]);
    model.change_schema(2, &v1, &v1).unwrap();
    assert_eq!(
        model.intent_payload(receipt.effects[0]).unwrap(),
        b"old-intent"
    );
    assert_eq!(
        model.change_schema(3, &v1, &BTreeSet::from([2])),
        Err(ModelError::RetainedFormatRequired)
    );
    assert_eq!(
        model.change_schema(3, &BTreeSet::from([2]), &v1),
        Err(ModelError::RetainedFormatRequired)
    );
    assert_eq!(
        model.lookup(&grant, &key("old-format")).unwrap().outcome,
        DurableOutcome::Committed(receipt)
    );
}

#[test]
fn unresolved_effect_outlives_result_payload_and_protects_linked_identity() {
    let mut model = model();
    let grant = authority(&mut model);
    let attempt = begin(&mut model, &grant, "retained", 1);
    model
        .stage_intent(attempt, b"pending-payload".to_vec())
        .unwrap();
    let receipt = commit(&mut model, attempt, b"finite-result");
    assert_eq!(
        model.expire_result_payload(&key("retained"), RetentionTime::Discontinuous, 10),
        Err(ModelError::ClockDiscontinuity)
    );
    model
        .expire_result_payload(&key("retained"), RetentionTime::QualifiedElapsed(10), 10)
        .unwrap();
    assert_eq!(
        model.lookup(&grant, &key("retained")).unwrap().payload,
        None
    );
    assert_eq!(
        model.lookup(&grant, &key("retained")).unwrap().outcome,
        DurableOutcome::Committed(receipt.clone())
    );
    assert_eq!(
        model.intent_payload(receipt.effects[0]).unwrap(),
        b"pending-payload"
    );
    assert_eq!(
        model.collect_command_identity(&key("retained"), RetentionTime::QualifiedElapsed(100), 10),
        Err(ModelError::LinkedRetention)
    );
    assert!(matches!(
        model
            .admit(&grant, key("retained"), body(), 2, None)
            .unwrap(),
        Admission::Existing(outcome) if matches!(*outcome, DurableOutcome::Committed(_))
    ));
}

#[test]
fn finite_recovery_capacity_is_usable_when_business_admission_is_saturated() {
    let mut configured = limits();
    configured.admitted_commands = 1;
    let mut model = TransactionModel::new("tenant-a".into(), "ledger".into(), configured).unwrap();
    let grant = authority(&mut model);
    let attempt = begin(&mut model, &grant, "retained", 1);
    let receipt = commit(&mut model, attempt, b"recoverable");
    assert_eq!(
        model.admit(&grant, key("capacity"), body(), 2, None),
        Err(ModelError::Limit)
    );
    assert_eq!(
        model.lookup(&grant, &key("retained")).unwrap().outcome,
        DurableOutcome::Committed(receipt)
    );
    assert_eq!(
        model.lookup(&grant, &key("retained")).unwrap().payload,
        Some(b"recoverable".to_vec())
    );
}

#[test]
fn expired_unknown_history_never_authorizes_retry() {
    let mut model = model();
    let grant = authority(&mut model);
    let attempt = begin(&mut model, &grant, "expired", 1);
    commit(&mut model, attempt, b"finite");
    model
        .collect_command_identity(&key("expired"), RetentionTime::QualifiedElapsed(10), 10)
        .unwrap();
    assert_eq!(
        model.lookup(&grant, &key("expired")).unwrap().outcome,
        DurableOutcome::Unknown
    );
    assert_eq!(
        model.abort_fence(&grant, &key("expired")),
        Err(ModelError::AbortUnproven)
    );
}

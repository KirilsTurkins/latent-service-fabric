//! Actual engine receipts and current policy. Offline rows in this fixture are
//! test-controlled inputs; the real review/resume plans still gate readiness.
use super::*;
use latent_commit::atomic::{
    self, AdmissionDecision, AdmissionInput, CommandRecord, CommandTime, CompleteEnvelope,
    PreparedAdmission, PreparedDisposition, ReplayPolicy, ResultPolicy, SourceIdentity,
};
use latent_core::transaction_contract::{CommandFingerprint, CommandKey, Value};
use latent_state::{
    embedded::ExpectedRow,
    namespace::history::{history_key, HistoryStatus, NamespaceHistory},
    recovery::{
        resume::{NamespaceRecoveryView, NamespaceResumePlan, NamespaceResumeRequest},
        RecoveryGuard,
    },
    session::{
        version::{capture_view_identity, ViewIdentity},
        StateMode, StateScope,
    },
};

fn time(unix_millis: u64) -> CommandTime {
    CommandTime {
        unix_millis,
        continuity_proven: true,
    }
}

fn original(fixture: &Fixture) -> CommandRecord {
    let caller =
        CallerScope::derive(&principal("alice"), &RecoverySelection::OriginalCaller).unwrap();
    let value = Value {
        bytes: b"original".to_vec(),
        media_type: "application/octet-stream".into(),
        metadata: vec![],
    };
    let input = AdmissionInput {
        key: CommandKey {
            tenant: "a".into(),
            namespace: "orders".into(),
            incarnation: "1".into(),
            entity: Some("alice-order".into()),
            recovery_scope: caller.scope,
            operation: "update".into(),
            client_key: "original".into(),
        },
        fingerprint: CommandFingerprint {
            input_format: "fixture-values-v1".into(),
            input: value.clone(),
            expected_versions: vec![],
        },
        source: SourceIdentity {
            publication: fixture.publication.publication().to_string(),
            revision: "revision-1".into(),
            release_digest: fixture.publication.release().0.clone(),
            component_digest: fixture.publication.release().0.clone(),
            contract_digest: format!("sha256:{}", "2".repeat(64)),
            route_generation: 1,
            state_schema: schema(),
            input_format: "fixture-values-v1".into(),
            result_format: "fixture-values-v1".into(),
        },
        result_read_policy: "visibility-v1".into(),
        result_policy: ResultPolicy {
            replay: ReplayPolicy::Full,
            maximum_result_bytes: 4096,
            result_millis: 1000,
            identity_millis: 10000,
            maximum_attempts: 4,
        },
        inbox: None,
        owner_epoch: 1,
    };
    let view = fixture.database.snapshot().unwrap();
    let AdmissionDecision::New(plan) =
        PreparedAdmission::prepare(&view, input, time(100), |_, _| Ok(())).unwrap()
    else {
        panic!("fresh fixture")
    };
    drop(view);
    let claim = plan.publish(&fixture.database, || Ok(())).unwrap();
    let view = fixture.database.snapshot().unwrap();
    let envelope =
        CompleteEnvelope::success_without_intents(&view, claim, None, value, time(101)).unwrap();
    drop(view);
    let PreparedDisposition::Confirmed { command, .. } =
        envelope.publish(&fixture.database, |_| Ok(()))
    else {
        panic!("actual commit")
    };
    *command
}

fn retained_read(fixture: &Fixture, subject: &str) -> OwnedPolicyDecision {
    let actor = principal(subject);
    let entity = format!("{subject}-order");
    let target = scope(&actor, Some(&entity), &RecoverySelection::OriginalCaller);
    let snapshot = fixture.snapshot();
    let decision = fixture.decision(&snapshot, &actor, &target, "read-result");
    fixture.policy.retain_decision(&decision).unwrap()
}

fn seal_result(
    fixture: &Fixture,
    original: &CommandRecord,
    decision: OwnedPolicyDecision,
) -> Result<NamespaceAuthority, PlatformError> {
    let read = fixture.read();
    let view = fixture.database.snapshot().unwrap();
    let history = ReviewedResultHistory::capture(&view, &read, original).unwrap();
    NamespaceAuthority::seal_result_retained(
        &fixture.policy,
        decision,
        &read,
        NamespaceAdmission {
            activation: ActivationId("historical-result".into()),
            deadline: deadline(),
            recovery: &RecoverySelection::OriginalCaller,
            state_schema: &original.source().state_schema,
        },
        fixture.namespaces.lifecycle().pin(&read).unwrap(),
        history,
    )
}

fn write_rows(fixture: &Fixture, rows: Vec<(RowKey, Vec<u8>)>) {
    let view = fixture.database.snapshot().unwrap();
    let expectations = rows
        .iter()
        .map(|(key, _)| ExpectedRow {
            key: key.clone(),
            value: view.get(key).unwrap(),
        })
        .collect();
    drop(view);
    fixture
        .database
        .apply(AtomicBatch {
            expectations,
            mutations: rows
                .into_iter()
                .map(|(key, bytes)| RowMutation {
                    key,
                    value: Some(bytes),
                })
                .collect(),
        })
        .unwrap();
}

fn pause(fixture: &Fixture, changed_schema: bool) {
    let read = fixture.read();
    let mut record = read.record().clone();
    let mut history = NamespaceHistory::initial(&record);
    record.status = NamespaceStatus::Quiescing;
    record.version.generation += 1;
    history.epochs.recovery += 1;
    history.status = HistoryStatus::ReconciliationRequired;
    if changed_schema {
        record.state_schema = format!("sha256:{}", "8".repeat(64));
        history.state_schema.clone_from(&record.state_schema);
        history.epochs.schema += 1;
    }
    write_rows(
        fixture,
        vec![
            (read.expectation().key, record.encode().unwrap()),
            (
                history_key(&record.tenant, &record.id, 1).unwrap(),
                history.encode().unwrap(),
            ),
        ],
    );
}

fn review_and_resume(fixture: &Fixture) {
    let view = fixture.database.snapshot().unwrap();
    let guard = RecoveryGuard::capture(&view).unwrap().unwrap();
    let reviewed = guard
        .prepare_reviewed(&view, [4; 32], |_, actual, proof| {
            assert_eq!(actual.snapshot_digest(), [2; 32]);
            assert_eq!(proof, [4; 32]);
            fixture
                .policy
                .with_retained_decision(&retained_read(fixture, "alice"), &mut |_, _| Ok(()))
                .map_err(|_| StoreError::Unavailable)
        })
        .unwrap();
    drop(view);
    fixture.database.apply(reviewed).unwrap();
    let view = fixture.database.snapshot().unwrap();
    let observed = NamespaceRecoveryView::capture(
        &view,
        &TenantId("a".into()),
        &latent_core::StateNamespaceId("orders".into()),
    )
    .unwrap();
    let request = NamespaceResumeRequest {
        scope: observed.scope(),
        operation_id: "reviewed-resume".into(),
        operator_id: "operator".into(),
        expected_view: observed.view_token().unwrap(),
        review_digest: [5; 32],
    };
    let plan = NamespaceResumePlan::prepare(&view, &request, |_, actual, observed| {
        assert_eq!(actual.review_digest, [5; 32]);
        assert_eq!(
            observed.history.status,
            HistoryStatus::ReconciliationRequired
        );
        Ok(())
    })
    .unwrap();
    drop(view);
    fixture.database.apply(plan.into_batch()).unwrap();
}

#[test]
fn reviewed_restore_and_schema_result_read_preserves_original_receipt_and_denies_stale_queries() {
    for changed_schema in [false, true] {
        let fixture = Fixture::new();
        let original = original(&fixture);
        let token = original.committed_view_token().unwrap().to_vec();
        pause(&fixture, changed_schema);
        let staging = RecoveryGuard::staging([1; 32], [2; 32], [3; 32]).unwrap();
        fixture
            .database
            .apply(staging.prepare_staging().unwrap())
            .unwrap();
        fixture
            .database
            .apply(staging.prepare_completed().unwrap())
            .unwrap();
        assert!(ReviewedResultHistory::capture(
            &fixture.database.snapshot().unwrap(),
            &fixture.read(),
            &original
        )
        .is_err());
        review_and_resume(&fixture);
        let authority = seal_result(&fixture, &original, retained_read(&fixture, "alice")).unwrap();
        let read = fixture.read();
        let view = fixture.database.snapshot().unwrap();
        authority
            .require_result_history(&view, &read, &original)
            .unwrap();
        let actor = principal("alice");
        let target = scope_target(&actor);
        let snapshot = fixture.snapshot();
        let result_read = fixture.decision(&snapshot, &actor, &target, "read-result");
        let replayed = atomic::inspect(&view, original.key(), time(102), |_, record| {
            if let Some(record) = record {
                assert_eq!(record, &original);
            }
            authority
                .with_operation(&fixture.policy, &result_read, &read, "read-result", || {
                    Ok(())
                })
                .map_err(|_| atomic::AtomicError::PermissionDenied)
        })
        .unwrap();
        assert_eq!(replayed.0, original);
        assert_eq!(replayed.1.unwrap().committed_view_token(), token);
        assert_eq!(authority.original_result(), Some(&original));
        let scope = StateScope {
            tenant: TenantId("a".into()),
            namespace: latent_core::StateNamespaceId("orders".into()),
            incarnation: 1,
            state_schema: read.record().state_schema.clone(),
            entity: Some("alice-order".into()),
            mode: StateMode::Query,
        };
        assert!(capture_view_identity(&view, &scope)
            .unwrap()
            .require_minimum(&scope, &token)
            .is_err());
        let commit = fixture.decision(&snapshot, &actor, &target, "commit");
        assert!(authority
            .with_operation(&fixture.policy, &commit, &read, "commit", || Ok(()))
            .is_err());
    }
}

fn scope_target(
    actor: &latent_core::InvocationPrincipal,
) -> latent_policy::capability::StateResourceScope {
    scope(
        actor,
        Some("alice-order"),
        &RecoverySelection::OriginalCaller,
    )
}

#[test]
fn historical_result_read_refuses_foreign_caller_revocation_and_invocation_authority() {
    let fixture = Fixture::new();
    let original = original(&fixture);
    assert!(seal_result(&fixture, &original, retained_read(&fixture, "bob")).is_err());
    let actor = principal("alice");
    let target = scope_target(&actor);
    let snapshot = fixture.snapshot();
    let command = fixture.decision(&snapshot, &actor, &target, "acquire-command");
    assert!(seal_result(
        &fixture,
        &original,
        fixture.policy.retain_decision(&command).unwrap()
    )
    .is_err());
    let retained = retained_read(&fixture, "alice");
    let current = seal_result(&fixture, &original, retained_read(&fixture, "alice")).unwrap();
    let read = fixture.read();
    let result_read = fixture.decision(&snapshot, &actor, &target, "read-result");
    fixture.update(None, "revoke-historical-result");
    assert!(seal_result(&fixture, &original, retained).is_err());
    let mut released = false;
    assert!(current
        .with_operation(&fixture.policy, &result_read, &read, "read-result", || {
            released = true;
            Ok(())
        })
        .is_err());
    assert!(!released);
}

#[test]
fn historical_result_read_fences_changed_history_and_never_reconstructs_expired_body() {
    let fixture = Fixture::new();
    let original = original(&fixture);
    let authority = seal_result(&fixture, &original, retained_read(&fixture, "alice")).unwrap();
    let read = fixture.read();
    let mut history = NamespaceHistory::initial(read.record());
    history.epochs.recovery += 1;
    write_rows(
        &fixture,
        vec![(
            history_key(&read.record().tenant, &read.record().id, 1).unwrap(),
            history.encode().unwrap(),
        )],
    );
    let view = fixture.database.snapshot().unwrap();
    assert!(authority
        .require_result_history(&view, &fixture.read(), &original)
        .is_err());
    let current = seal_result(&fixture, &original, retained_read(&fixture, "alice")).unwrap();
    current
        .require_result_history(&view, &fixture.read(), &original)
        .unwrap();
    let (expired, result) =
        atomic::inspect(&view, original.key(), time(1100), |_, _| Ok(())).unwrap();
    assert_eq!(expired, original);
    assert!(result.is_none());
    assert_eq!(
        expired.committed_view_token(),
        original.committed_view_token()
    );
    assert_eq!(
        ViewIdentity::from_token(
            &StateScope {
                tenant: TenantId("a".into()),
                namespace: latent_core::StateNamespaceId("orders".into()),
                incarnation: 1,
                state_schema: schema(),
                entity: Some("alice-order".into()),
                mode: StateMode::Query,
            },
            original.committed_view_token().unwrap()
        )
        .unwrap()
        .epochs
        .recovery,
        1
    );
}

//! Real native claims and original registrations, without guest qualification.
use super::*;
use crate::journal::{LocalActivationJournal, LocalActivationJournalConfig};
use latent_core::{ActivationPhase, PlatformErrorCode, SystemActivationClock, TenantId};

fn journal_owner(
    envelope: &latent_activation::ActivationEnvelope,
    budget: &latent_core::ActivationBudget,
    config: LocalActivationJournalConfig,
) -> (LocalActivationJournal, crate::journal::JournalOwner) {
    let journal = LocalActivationJournal::new(config, Arc::new(SystemActivationClock)).unwrap();
    let mut owner = journal.begin(envelope).unwrap();
    owner
        .advance(ActivationPhase::Resolved, Metadata::new())
        .unwrap();
    owner
        .advance(ActivationPhase::Admitted, Metadata::new())
        .unwrap();
    owner.record_grant(budget);
    (journal, owner)
}

async fn retire(
    admission: Arc<NativeTransactionAdmission>,
    claim: latent_commit::atomic::AdmittedCommand,
    host: Arc<StateTransactionHost>,
) {
    host.finish_guest_access();
    host.retire().await.unwrap();
    drop(claim);
    host.retire_command_role().unwrap();
    drop((host, admission));
}

#[tokio::test]
async fn original_native_command_cancellation_requests_only_its_original_owner() {
    let fixture = Fixture::new().await;
    let (admission, envelope, budget) = fixture.invocation(false, "original-cancel");
    admission.admit(&envelope, &budget).await.unwrap();
    let original = admission.original_command_cancellation().unwrap().unwrap();
    let TransactionAdmissionResult::Command { claim, host } =
        admission.take_result().unwrap().unwrap()
    else {
        panic!("command absent")
    };
    let before = claim.record().encode().unwrap();
    let (journal, owner) =
        journal_owner(&envelope, &budget, LocalActivationJournalConfig::default());
    owner
        .bind_original_command_cancellation(
            original,
            fixture.original_cancellation_owner(&envelope),
        )
        .unwrap();
    assert!(!budget.descendant_is_cancelled());
    for reason in ["first original request", "second original request"] {
        assert_eq!(
            journal
                .cancel_original_command(
                    &envelope.target.tenant,
                    claim.record(),
                    fixture.protected_store().as_ref(),
                    reason
                )
                .unwrap(),
            OriginalCommandCancelDisposition::Requested
        );
    }
    assert!(budget.descendant_is_cancelled());
    assert_eq!(claim.record().outcome(), Outcome::Pending);
    let (record, result) = fixture.inspect(claim.record().key().clone()).await;
    assert_eq!(record.encode().unwrap(), before);
    assert!(result.is_none() && record.abort_proof().is_none());
    assert_eq!(fixture.rows(Family::State).await, 0);
    assert_eq!(fixture.rows(Family::Outbox).await, 0);
    retire(admission, claim, host).await;
    drop(owner);
    fixture.shutdown().await;
}

#[tokio::test]
async fn original_native_command_cancellation_binding_is_once_and_budget_bound() {
    let fixture = Fixture::new().await;
    let (admission, envelope, budget) = fixture.invocation(false, "once-cancel");
    admission.admit(&envelope, &budget).await.unwrap();
    let one = admission.original_command_cancellation().unwrap().unwrap();
    let two = admission.original_command_cancellation().unwrap().unwrap();
    let (_, _, foreign_budget) = fixture.invocation(true, "foreign-budget");
    let (foreign_journal, foreign_owner) = journal_owner(
        &envelope,
        &foreign_budget,
        LocalActivationJournalConfig::default(),
    );
    assert_eq!(
        foreign_owner
            .bind_original_command_cancellation(two, fixture.original_cancellation_owner(&envelope))
            .unwrap_err()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    assert!(!budget.descendant_is_cancelled() && !foreign_budget.descendant_is_cancelled());
    drop((foreign_owner, foreign_journal));
    let (journal, owner) =
        journal_owner(&envelope, &budget, LocalActivationJournalConfig::default());
    owner
        .bind_original_command_cancellation(one, fixture.original_cancellation_owner(&envelope))
        .unwrap();
    assert_eq!(
        owner
            .bind_original_command_cancellation(
                admission.original_command_cancellation().unwrap().unwrap(),
                fixture.original_cancellation_owner(&envelope)
            )
            .unwrap_err()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    let TransactionAdmissionResult::Command { claim, host } =
        admission.take_result().unwrap().unwrap()
    else {
        panic!("command absent")
    };
    assert_eq!(
        journal
            .cancel_original_command(
                &TenantId("foreign".into()),
                claim.record(),
                fixture.protected_store().as_ref(),
                "denied"
            )
            .unwrap_err()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    assert!(!budget.descendant_is_cancelled());
    retire(admission, claim, host).await;
    drop(owner);
    fixture.shutdown().await;
}

#[tokio::test]
async fn original_native_command_cancellation_respects_existing_record_cap() {
    let fixture = Fixture::new().await;
    let (admission, envelope, budget) = fixture.invocation(false, "bounded-cancel");
    admission.admit(&envelope, &budget).await.unwrap();
    let (probe, probe_owner) =
        journal_owner(&envelope, &budget, LocalActivationJournalConfig::default());
    let boundary = probe.command_association_boundary_for_test(&envelope.activation_id);
    drop((probe_owner, probe));
    let config = LocalActivationJournalConfig {
        maximum_record_bytes: boundary - 1,
        ..LocalActivationJournalConfig::default()
    };
    let (journal, owner) = journal_owner(&envelope, &budget, config);
    assert_eq!(
        owner
            .bind_original_command_cancellation(
                admission.original_command_cancellation().unwrap().unwrap(),
                fixture.original_cancellation_owner(&envelope)
            )
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    let TransactionAdmissionResult::Command { claim, host } =
        admission.take_result().unwrap().unwrap()
    else {
        panic!("command absent")
    };
    assert_eq!(
        journal
            .cancel_original_command(
                &envelope.target.tenant,
                claim.record(),
                fixture.protected_store().as_ref(),
                "not installed"
            )
            .unwrap(),
        OriginalCommandCancelDisposition::RecoveryRequired
    );
    assert!(!budget.descendant_is_cancelled());
    retire(admission, claim, host).await;
    drop(owner);
    fixture.shutdown().await;
}

#[tokio::test]
async fn original_native_query_and_released_guest_do_not_mint_command_cancellation() {
    let fixture = Fixture::new().await;
    let (query, envelope, budget) = fixture.invocation(true, "query-cancel");
    query.admit(&envelope, &budget).await.unwrap();
    assert!(query.original_command_cancellation().unwrap().is_none());
    let TransactionAdmissionResult::Query { host } = query.take_result().unwrap().unwrap() else {
        panic!("query absent")
    };
    host.finish_guest_access();
    host.retire().await.unwrap();
    drop((host, query));
    let (admission, envelope, budget) = fixture.invocation(false, "late-cancel-bind");
    admission.admit(&envelope, &budget).await.unwrap();
    let TransactionAdmissionResult::Command { claim, host } =
        admission.take_result().unwrap().unwrap()
    else {
        panic!("command absent")
    };
    host.acquire(Mode::Command).unwrap();
    assert_eq!(
        super::super::cancellation::OriginalCommandCancellation::from_claim(&claim, &host)
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    host.finish_guest_access();
    assert_eq!(
        super::super::cancellation::OriginalCommandCancellation::from_claim(&claim, &host)
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    retire(admission, claim, host).await;
    fixture.shutdown().await;
}

#[tokio::test]
async fn original_native_command_cancellation_rejects_foreign_physical_store_and_record() {
    let fixture = Fixture::new().await;
    let foreign = Fixture::new().await;
    let (admission, envelope, budget) = fixture.invocation(false, "same-key-cancel");
    admission.admit(&envelope, &budget).await.unwrap();
    let (journal, owner) =
        journal_owner(&envelope, &budget, LocalActivationJournalConfig::default());
    owner
        .bind_original_command_cancellation(
            admission.original_command_cancellation().unwrap().unwrap(),
            fixture.original_cancellation_owner(&envelope),
        )
        .unwrap();
    let TransactionAdmissionResult::Command { claim, host } =
        admission.take_result().unwrap().unwrap()
    else {
        panic!("command absent")
    };
    assert_eq!(
        journal
            .cancel_original_command(
                &envelope.target.tenant,
                claim.record(),
                foreign.protected_store().as_ref(),
                "foreign physical owner"
            )
            .unwrap(),
        OriginalCommandCancelDisposition::RecoveryRequired
    );
    let (other, other_envelope, other_budget) = fixture.invocation(false, "other-original-cancel");
    other.admit(&other_envelope, &other_budget).await.unwrap();
    let TransactionAdmissionResult::Command {
        claim: other_claim,
        host: other_host,
    } = other.take_result().unwrap().unwrap()
    else {
        panic!("other command absent")
    };
    assert_eq!(
        journal
            .cancel_original_command(
                &envelope.target.tenant,
                other_claim.record(),
                fixture.protected_store().as_ref(),
                "different original"
            )
            .unwrap(),
        OriginalCommandCancelDisposition::RecoveryRequired
    );
    assert!(!budget.descendant_is_cancelled() && !other_budget.descendant_is_cancelled());
    retire(other, other_claim, other_host).await;
    retire(admission, claim, host).await;
    drop(owner);
    fixture.shutdown().await;
    foreign.shutdown().await;
}

#[tokio::test]
async fn original_native_command_cancellation_rejects_ambiguous_associations_without_request() {
    let fixture = Fixture::new().await;
    let (admission, envelope, budget) = fixture.invocation(false, "ambiguous-original");
    admission.admit(&envelope, &budget).await.unwrap();
    let (journal, owner) =
        journal_owner(&envelope, &budget, LocalActivationJournalConfig::default());
    owner
        .bind_original_command_cancellation(
            admission.original_command_cancellation().unwrap().unwrap(),
            fixture.original_cancellation_owner(&envelope),
        )
        .unwrap();
    let (_, duplicate_envelope, duplicate_budget) =
        fixture.invocation(true, "duplicate-journal-only");
    let mut duplicate = journal.begin(&duplicate_envelope).unwrap();
    duplicate
        .advance(ActivationPhase::Resolved, Metadata::new())
        .unwrap();
    duplicate
        .advance(ActivationPhase::Admitted, Metadata::new())
        .unwrap();
    duplicate.record_grant(&duplicate_budget);
    // Defensive contradictory journal data cannot choose an arbitrary owner.
    // Production exposes no constructor or Clone for this opaque association.
    journal.duplicate_command_association_for_test(
        &envelope.activation_id,
        &duplicate_envelope.activation_id,
    );
    let TransactionAdmissionResult::Command { claim, host } =
        admission.take_result().unwrap().unwrap()
    else {
        panic!("command absent")
    };
    assert_eq!(
        journal
            .cancel_original_command(
                &envelope.target.tenant,
                claim.record(),
                fixture.protected_store().as_ref(),
                "ambiguous"
            )
            .unwrap_err()
            .code,
        PlatformErrorCode::Unavailable
    );
    assert!(!budget.descendant_is_cancelled() && !duplicate_budget.descendant_is_cancelled());
    assert_eq!(claim.record().outcome(), Outcome::Pending);
    retire(admission, claim, host).await;
    drop((owner, duplicate));
    fixture.shutdown().await;
}

#[tokio::test]
async fn original_native_command_cancellation_mint_requires_actual_host_scope_and_attempt() {
    let fixture = Fixture::new().await;
    let (admission, envelope, budget) = fixture.invocation(false, "scope-checked-cancel");
    admission.admit(&envelope, &budget).await.unwrap();
    let TransactionAdmissionResult::Command { claim, mut host } =
        admission.take_result().unwrap().unwrap()
    else {
        panic!("command absent")
    };
    let owned = Arc::get_mut(&mut host).expect("fixture owns the original host exclusively");
    for case in 0..6 {
        match case {
            0 => owned.scope.tenant = TenantId("foreign".into()),
            1 => owned.scope.namespace = latent_core::StateNamespaceId("foreign".into()),
            2 => owned.scope.incarnation = 2,
            3 => owned.scope.state_schema = format!("sha256:{}", "f".repeat(64)),
            4 => owned.scope.mode = latent_state::session::StateMode::Query,
            _ => owned.command.as_mut().unwrap().attempt_id = "01".into(),
        }
        assert_eq!(
            super::super::cancellation::OriginalCommandCancellation::from_claim(&claim, owned)
                .err()
                .unwrap()
                .code,
            PlatformErrorCode::PermissionDenied
        );
        owned.scope.tenant = envelope.target.tenant.clone();
        owned.scope.namespace =
            latent_core::StateNamespaceId(claim.record().key().namespace.clone());
        owned.scope.incarnation = claim.record().key().incarnation.parse().unwrap();
        owned.scope.state_schema = claim.record().source().state_schema.clone();
        owned.scope.mode = latent_state::session::StateMode::Command;
        owned.command.as_mut().unwrap().attempt_id = claim.record().attempt().to_string();
    }
    assert!(
        super::super::cancellation::OriginalCommandCancellation::from_claim(&claim, owned).is_ok()
    );
    assert!(!budget.descendant_is_cancelled());
    retire(admission, claim, host).await;
    fixture.shutdown().await;
}

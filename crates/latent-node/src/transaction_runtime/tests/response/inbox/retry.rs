//! Trusted retries use durable abort receipts, not delivery counts or NAKs.
use super::*;
use latent_activation::ActivationEnvelope;
use latent_core::{ActivationBudget, ActivationTerminalState, PlatformError, PlatformErrorCode};
use latent_manifest::TransactionOperationMode;

fn selection(original: &CommandRecord, request: &str) -> TransactionSelection {
    let missing_proof = Identity::parse_hex(&"0".repeat(64)).unwrap();
    TransactionSelection {
        namespace: original.key().namespace.clone(),
        incarnation: original.key().incarnation.parse().unwrap(),
        entity: original.key().entity.clone(),
        operation: original.key().operation.clone(),
        mode: TransactionOperationMode::StrictCommand,
        client_key: Some(original.key().client_key.clone()),
        expected_versions: Vec::new(),
        minimum_view_version: None,
        input_format: original.source().input_format.clone(),
        retry: Some(TransactionRetrySelection {
            request: latent_commit::atomic::RetryRequest {
                request_id: request.into(),
                expected_abort: original.abort_proof().unwrap_or(missing_proof),
            },
            command: original.id(),
            attempt: original.attempt(),
            transaction: original.transaction_id(),
        }),
    }
}

fn retry_invocation(
    fixture: &Fixture,
    scope: &InboxScope,
    identity: &InboxIdentity,
    selected: TransactionSelection,
) -> (
    Arc<NativeTransactionAdmission>,
    ActivationEnvelope,
    ActivationBudget,
) {
    let (unused, mut envelope, budget) =
        fixture.invocation(false, &identity.command_key().unwrap());
    drop(unused);
    envelope.principal.kind = latent_core::PrincipalKind::Trigger;
    let admission = NativeTransactionAdmission::new(
        fixture.owners.clone(),
        fixture.installation.clone(),
        selected,
    )
    .unwrap()
    .with_trusted_inbox_retry(identity.clone(), scope.clone())
    .unwrap();
    (Arc::new(admission), envelope, budget)
}

async fn aborted_input(
    entity: Option<&str>,
) -> (Fixture, InboxScope, InboxIdentity, CommandRecord) {
    let fixture = Box::pin(Fixture::with_scoped_trigger()).await;
    let (scope, identity) = source();
    install_source(&fixture, &scope).await;
    let (admission, envelope, budget) = invocation(&fixture, &scope, &identity, entity);
    let guest = admission.admit(&envelope, &budget).await.unwrap();
    guest.acquire(Mode::Command).unwrap();
    guest
        .put(b"counter".to_vec(), value(b"discarded"))
        .await
        .unwrap();
    guest.finish_guest_access();
    let consumption = budget
        .finalize_at(None, std::time::Instant::now())
        .consumption()
        .clone();
    admission
        .complete(
            ActivationOutcome::Failed {
                terminal_state: ActivationTerminalState::GuestTrap,
                error: PlatformError {
                    code: PlatformErrorCode::GuestTrap,
                    message: "original input trap".into(),
                    retryable: false,
                    details: Vec::new(),
                },
                consumption,
            },
            fixture.commit_control(&envelope, &budget),
        )
        .await;
    let response = admission.take_owned_completion().unwrap().unwrap();
    let TransactionCompletionResult::Command(CommandCompletionDisposition::Durable {
        command,
        cleanup_failure: None,
        ..
    }) = &response.result
    else {
        panic!("original input did not retire and publish a durable abort");
    };
    assert_eq!(command.outcome(), Outcome::Aborted);
    assert!(command.abort_proof().is_some());
    assert_eq!(command.inbox_identity(), Some(&identity));
    let original = command.clone();
    drop((response, guest, admission, envelope, budget));
    for family in [Family::State, Family::Outbox, Family::Inbox] {
        assert_eq!(fixture.rows(family).await, 0);
    }
    assert_eq!(fixture.owners.lanes.snapshot().keys, 0);
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    (fixture, scope, identity, original)
}

async fn replay_retry(
    fixture: &Fixture,
    scope: &InboxScope,
    identity: &InboxIdentity,
    original: &CommandRecord,
    committed: &CommandRecord,
    expired: bool,
) {
    if expired {
        fixture.set_result_time(original.result_expires(), true);
    }
    let (replay, envelope, budget) =
        retry_invocation(fixture, scope, identity, selection(original, "approved-retry"));
    assert_eq!(
        replay.admit(&envelope, &budget).await.err().unwrap().code,
        PlatformErrorCode::AlreadyExists
    );
    let _ = budget.finalize_at(None, std::time::Instant::now());
    replay
        .complete(
            success(b"not executed"),
            fixture.commit_control(&envelope, &budget),
        )
        .await;
    let response = replay.take_owned_completion().unwrap().unwrap();
    let TransactionCompletionResult::Existing {
        command,
        result: Ok(result),
        ..
    } = &response.result
    else {
        panic!("same retry did not recover its original disposition");
    };
    assert_eq!(command, committed);
    assert_eq!(result.is_none(), expired);
    if let Some(result) = result {
        assert_eq!(result.value().unwrap().bytes, b"retried once");
    }
    response.authority.with_current(&mut || {}).unwrap();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn explicit_scoped_retry_and_duplicate_receipt_execute_one_new_attempt() {
    let (fixture, scope, identity, original) = Box::pin(aborted_input(None)).await;
    let (retry, envelope, budget) = retry_invocation(
        &fixture,
        &scope,
        &identity,
        selection(&original, "approved-retry"),
    );
    let guest = retry.admit(&envelope, &budget).await.unwrap();
    guest.acquire(Mode::Command).unwrap();
    let (duplicate, input, allowance) = retry_invocation(
        &fixture,
        &scope,
        &identity,
        selection(&original, "approved-retry"),
    );
    assert_eq!(
        duplicate
            .admit(&input, &allowance)
            .await
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::AlreadyExists
    );
    let Some(TransactionAdmissionResult::Existing { command, .. }) =
        duplicate.take_result().unwrap()
    else {
        panic!("pending retry duplicate acquired another guest");
    };
    assert_eq!(command.attempt(), 2);
    assert_eq!(command.outcome(), Outcome::Pending);
    assert_eq!(command.source(), original.source());
    assert_eq!(fixture.rows(Family::Inbox).await, 0);
    drop((duplicate, input, allowance));
    guest
        .put(b"counter".to_vec(), value(b"once"))
        .await
        .unwrap();
    guest.finish_guest_access();
    let _ = budget.finalize_at(None, std::time::Instant::now());
    retry
        .complete(
            success(b"retried once"),
            fixture.commit_control(&envelope, &budget),
        )
        .await;
    let response = retry.take_owned_completion().unwrap().unwrap();
    let TransactionCompletionResult::Command(CommandCompletionDisposition::Durable {
        command, ..
    }) = &response.result
    else {
        panic!("explicit retry did not commit");
    };
    let committed = command.clone();
    assert_eq!(committed.attempt(), 2);
    assert_eq!(committed.source(), original.source());
    assert_eq!(committed.result_expires(), original.result_expires());
    assert_eq!(committed.identity_expires(), original.identity_expires());
    assert_eq!(committed.inbox_identity(), Some(&identity));
    drop((response, guest, retry, envelope, budget));
    for expired in [false, true] {
        replay_retry(&fixture, &scope, &identity, &original, &committed, expired).await;
    }
    for family in [Family::Command, Family::State, Family::Inbox] {
        assert_eq!(fixture.rows(family).await, 1);
    }
    assert_eq!(fixture.rows(Family::Outbox).await, 0);
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn scoped_retry_source_and_abort_substitution_cannot_publish_an_attempt() {
    for variant in 0..4 {
        Box::pin(refused_retry(variant)).await;
    }
}

async fn refused_retry(variant: u8) {
    let (fixture, scope, mut identity, original) = Box::pin(aborted_input(None)).await;
    let mut selected = selection(&original, "refused-retry");
    match variant {
        0 => replace_source(&fixture, scope.clone(), None).await,
        1 => replace_source(&fixture, scope.clone(), Some(b"damaged".to_vec())).await,
        2 => {
            selected.retry.as_mut().unwrap().request.expected_abort =
                Identity::parse_hex(&"0".repeat(64)).unwrap();
        }
        _ => {
            identity.payload_digest = Identity::parse_hex(&format!(
                "{:x}",
                latent_core::digest::HexDigest(Sha256::digest(b"different"))
            ))
            .unwrap();
        }
    }
    let (retry, mut envelope, budget) =
        retry_invocation(&fixture, &scope, &identity, selected);
    if variant == 3 {
        envelope.input = b"different".to_vec();
    }
    assert!(retry.admit(&envelope, &budget).await.is_err());
    assert!(retry.take_result().unwrap().is_none());
    drop((retry, envelope, budget));
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    if variant == 1 {
        assert_eq!(
            fixture.protected_store().failure(),
            Some(ProtectedStoreError::Store(StoreError::Corrupt))
        );
        fixture.shutdown_uncertain_writer().await;
    } else {
        let key = latent_commit::atomic::command_row_key(original.id());
        let bytes = fixture
            .protected_store()
            .with_store(StoreIoKind::Read, 32 * 1024, move |store| {
                store.snapshot()?.get(&key)
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap()
            .unwrap();
        assert_eq!(CommandRecord::decode(&bytes).unwrap(), original);
        for family in [Family::State, Family::Outbox, Family::Inbox] {
            assert_eq!(fixture.rows(family).await, 0);
        }
        fixture.shutdown().await;
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn inbox_retry_attachment_requires_explicit_selection_and_exact_scope() {
    let (fixture, scope, identity, original) = Box::pin(aborted_input(None)).await;
    for variant in 0..5 {
        let mut selected = selection(&original, "selected-retry");
        let mut changed = scope.clone();
        match variant {
            0 => selected.retry = None,
            1 => selected.client_key = Some("unrelated".into()),
            2 => changed.incarnation = 2,
            3 => changed.provider = "other".into(),
            _ => changed.processing_scope = "fork".into(),
        }
        let admission = NativeTransactionAdmission::new(
            fixture.owners.clone(),
            fixture.installation.clone(),
            selected,
        )
        .unwrap();
        assert!(admission
            .with_trusted_inbox_retry(identity.clone(), changed)
            .is_err());
    }
    let admission = NativeTransactionAdmission::new(
        fixture.owners.clone(),
        fixture.installation.clone(),
        selection(&original, "requires-explicit-attachment"),
    )
    .unwrap();
    assert!(admission.with_trusted_inbox(identity).is_err());
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn committed_inbox_delivery_does_not_supply_a_retry_abort_proof() {
    let (fixture, scope, identity, original) = Box::pin(committed_input(None)).await;
    let (retry, envelope, budget) = retry_invocation(
        &fixture,
        &scope,
        &identity,
        selection(&original, "not-an-abort"),
    );
    assert!(retry.admit(&envelope, &budget).await.is_err());
    assert!(retry.take_result().unwrap().is_none());
    for family in [Family::Command, Family::Result, Family::Inbox] {
        assert_eq!(fixture.rows(family).await, 1);
    }
    drop((retry, envelope, budget));
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn scoped_entity_retry_waiter_recovers_winner_without_another_guest() {
    let (fixture, scope, identity, original) = Box::pin(aborted_input(Some("hot"))).await;
    let (retry, envelope, budget) = retry_invocation(
        &fixture,
        &scope,
        &identity,
        selection(&original, "approved-retry"),
    );
    let guest = retry.admit(&envelope, &budget).await.unwrap();
    guest.acquire(Mode::Command).unwrap();
    let (duplicate, input, allowance) = retry_invocation(
        &fixture,
        &scope,
        &identity,
        selection(&original, "approved-retry"),
    );
    let mut waiting = duplicate.admit(&input, &allowance);
    super::entity::observe_wait(&fixture, &mut waiting, 1, 0).await;
    assert_eq!(fixture.owners.lanes.snapshot().active, 1);
    assert_eq!(fixture.rows(Family::Inbox).await, 0);
    guest.finish_guest_access();
    let _ = budget.finalize_at(None, std::time::Instant::now());
    retry
        .complete(
            success(b"retried once"),
            fixture.commit_control(&envelope, &budget),
        )
        .await;
    let response = retry.take_owned_completion().unwrap().unwrap();
    let TransactionCompletionResult::Command(CommandCompletionDisposition::Durable {
        command, ..
    }) = &response.result
    else {
        panic!("original entity retry did not commit");
    };
    let committed = command.clone();
    drop((response, guest, retry, envelope, budget));
    assert_eq!(
        tokio::time::timeout(std::time::Duration::from_secs(5), waiting)
            .await
            .unwrap()
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::AlreadyExists
    );
    let Some(TransactionAdmissionResult::Existing { command, .. }) =
        duplicate.take_result().unwrap()
    else {
        panic!("entity retry waiter did not retain the winner");
    };
    assert_eq!(command, committed);
    assert_eq!(command.attempt(), 2);
    assert_eq!(fixture.owners.lanes.snapshot().keys, 0);
    drop((duplicate, input, allowance));
    replay_retry(&fixture, &scope, &identity, &original, &committed, false).await;
    assert_eq!(fixture.rows(Family::Inbox).await, 1);
    assert_eq!(fixture.rows(Family::Command).await, 1);
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}

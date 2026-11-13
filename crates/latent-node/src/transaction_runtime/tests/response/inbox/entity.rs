//! Scoped inbox input uses the original finite entity lane and replay owners.
use super::*;
use latent_core::{BoxFuture, PlatformError, PlatformErrorCode};
use std::{future::poll_fn, task::Poll, time::Duration};

pub(super) async fn observe_wait(
    fixture: &Fixture,
    pending: &mut BoxFuture<'_, Result<Arc<dyn TransactionHost>, PlatformError>>,
    queued: usize,
    duplicates: usize,
) {
    tokio::time::timeout(
        Duration::from_secs(5),
        poll_fn(|cx| {
            match std::future::Future::poll(pending.as_mut(), cx) {
                Poll::Pending => {}
                Poll::Ready(Err(error)) => {
                    panic!("admission ended before queue arrival: {error:?}")
                }
                Poll::Ready(Ok(_)) => panic!("guest admitted while the original lane is occupied"),
            }
            if fixture.owners.lanes.snapshot().queued == queued
                && fixture.owners.entity_duplicate_waiter_count().unwrap() == duplicates
            {
                return Poll::Ready(());
            }
            cx.waker().wake_by_ref();
            Poll::Pending
        }),
    )
    .await
    .unwrap();
}

async fn replay_terminal(
    fixture: &Fixture,
    scope: &InboxScope,
    identity: &InboxIdentity,
    original: &CommandRecord,
    expired: bool,
) {
    if expired {
        fixture.set_result_time(original.result_expires(), true);
    }
    let (replay, envelope, budget) = invocation(fixture, scope, identity, Some("hot"));
    assert_eq!(
        replay.admit(&envelope, &budget).await.err().unwrap().code,
        PlatformErrorCode::AlreadyExists
    );
    let _ = budget.finalize_at(None, std::time::Instant::now());
    replay
        .complete(
            success(b"must not execute"),
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
        panic!("scoped entity duplicate lost the original durable disposition");
    };
    assert_eq!(command, original);
    assert_eq!(result.is_none(), expired);
    if let Some(result) = result {
        assert_eq!(result.value().unwrap().bytes, b"original");
    }
    response.authority.with_current(&mut || {}).unwrap();
    assert_eq!(fixture.owners.lanes.snapshot().keys, 0);
    for family in [Family::Command, Family::Result, Family::Inbox] {
        assert_eq!(fixture.rows(family).await, 1);
    }
    assert_eq!(fixture.rows(Family::Outbox).await, 0);
    drop((response, replay, envelope, budget));
    assert!(fixture.native.snapshot().unwrap().physically_retired());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn scoped_entity_pending_duplicates_and_terminal_replay_keep_one_guest() {
    for rejected in [false, true] {
        Box::pin(commit_once(rejected)).await;
    }
}

async fn commit_once(rejected: bool) {
    let fixture = Box::pin(Fixture::with_scoped_trigger()).await;
    let (scope, identity) = source();
    install_source(&fixture, &scope).await;
    let (first, envelope, budget) = invocation(&fixture, &scope, &identity, Some("hot"));
    let guest = first.admit(&envelope, &budget).await.unwrap();
    guest.acquire(Mode::Command).unwrap();
    guest
        .put(b"counter".to_vec(), value(b"once"))
        .await
        .unwrap();

    let (duplicate, input, allowance) = invocation(&fixture, &scope, &identity, Some("hot"));
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
        panic!("pending duplicate did not retain the original claim");
    };
    assert_eq!(command.outcome(), Outcome::Pending);
    assert_eq!(command.inbox_identity(), Some(&identity));
    assert_eq!(fixture.owners.lanes.snapshot().active, 1);
    assert_eq!(fixture.owners.lanes.snapshot().queued, 0);
    assert_eq!(fixture.rows(Family::Inbox).await, 0);
    drop((duplicate, input, allowance));

    conflicting_input(&fixture, &scope, &identity).await;

    guest.finish_guest_access();
    let _ = budget.finalize_at(None, std::time::Instant::now());
    let outcome = if rejected {
        ActivationOutcome::DeclaredError {
            error: DeclaredError {
                code: "rejected".into(),
                message: "business rejection".into(),
                payload: b"original".to_vec().into(),
                media_type: "application/octet-stream".into(),
                metadata: Metadata::new(),
            },
            consumption: BudgetConsumption::default(),
        }
    } else {
        success(b"original")
    };
    first
        .complete(outcome, fixture.commit_control(&envelope, &budget))
        .await;
    let response = first.take_owned_completion().unwrap().unwrap();
    let TransactionCompletionResult::Command(CommandCompletionDisposition::Durable {
        command, ..
    }) = &response.result
    else {
        panic!("original scoped entity input did not finish durably");
    };
    assert_eq!(
        command.outcome(),
        if rejected {
            Outcome::Rejected
        } else {
            Outcome::Committed
        }
    );
    assert_eq!(command.inbox_identity(), Some(&identity));
    assert_eq!(fixture.rows(Family::State).await, usize::from(!rejected));
    let original = command.clone();
    drop((guest, response, first, envelope, budget));
    for expired in [false, true] {
        replay_terminal(&fixture, &scope, &identity, &original, expired).await;
    }
    fixture.shutdown().await;
}

async fn conflicting_input(fixture: &Fixture, scope: &InboxScope, identity: &InboxIdentity) {
    let mut changed = identity.clone();
    changed.payload_digest = Identity::parse_hex(&format!(
        "{:x}",
        latent_core::digest::HexDigest(Sha256::digest(b"different"))
    ))
    .unwrap();
    assert_eq!(
        changed.command_key().unwrap(),
        identity.command_key().unwrap()
    );
    let (conflict, mut input, allowance) = invocation(fixture, scope, &changed, Some("hot"));
    input.input = b"different".to_vec();
    assert_eq!(
        conflict.admit(&input, &allowance).await.err().unwrap().code,
        PlatformErrorCode::StateConflict
    );
    assert!(conflict.take_result().unwrap().is_none());
    assert_eq!(fixture.owners.lanes.snapshot().active, 1);
    assert_eq!(fixture.owners.lanes.snapshot().queued, 0);
    drop((conflict, input, allowance));
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn missing_source_never_registers_an_entity_lane_or_command() {
    let fixture = Box::pin(Fixture::with_scoped_trigger()).await;
    let (scope, identity) = source();
    let (admission, envelope, budget) = invocation(&fixture, &scope, &identity, Some("hot"));
    assert_eq!(
        admission
            .admit(&envelope, &budget)
            .await
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::StateConflict
    );
    assert!(admission.take_result().unwrap().is_none());
    assert_eq!(fixture.owners.lanes.snapshot().keys, 0);
    for family in [
        Family::Command,
        Family::Result,
        Family::Inbox,
        Family::Outbox,
    ] {
        assert_eq!(fixture.rows(family).await, 0);
    }
    drop((admission, envelope, budget));
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn lost_or_corrupt_source_before_entity_replay_never_becomes_a_new_input() {
    for corrupt in [false, true] {
        let (fixture, scope, identity, _original) = Box::pin(committed_input(Some("hot"))).await;
        replace_source(
            &fixture,
            scope.clone(),
            corrupt.then(|| b"damaged".to_vec()),
        )
        .await;
        let (admission, envelope, budget) = invocation(&fixture, &scope, &identity, Some("hot"));
        let error = admission.admit(&envelope, &budget).await.err().unwrap();
        assert_eq!(
            error.code,
            if corrupt {
                PlatformErrorCode::Unavailable
            } else {
                PlatformErrorCode::StateConflict
            }
        );
        assert!(admission.take_result().unwrap().is_none());
        assert_eq!(fixture.owners.lanes.snapshot().keys, 0);
        if corrupt {
            assert_eq!(
                fixture.protected_store().failure(),
                Some(ProtectedStoreError::Store(StoreError::Corrupt))
            );
        } else {
            for family in [Family::Command, Family::Result, Family::Inbox] {
                assert_eq!(fixture.rows(family).await, 1);
            }
            assert!(fixture.protected_store().failure().is_none());
        }
        drop((admission, envelope, budget));
        assert!(fixture.native.snapshot().unwrap().physically_retired());
        if corrupt {
            fixture.shutdown_uncertain_writer().await;
        } else {
            fixture.shutdown().await;
        }
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn queued_scoped_entity_rechecks_source_before_publishing_a_new_claim() {
    let fixture = Box::pin(Fixture::with_scoped_trigger()).await;
    let (scope, identity) = source();
    install_source(&fixture, &scope).await;
    let (blocker, mut input, allowance) = fixture.entity_invocation("blocker", "hot");
    input.principal.kind = latent_core::PrincipalKind::Trigger;
    let guest = blocker.admit(&input, &allowance).await.unwrap();
    guest.acquire(Mode::Command).unwrap();
    let (waiting, envelope, budget) = invocation(&fixture, &scope, &identity, Some("hot"));
    let mut pending = waiting.admit(&envelope, &budget);
    observe_wait(&fixture, &mut pending, 1, 0).await;
    replace_source(&fixture, scope, None).await;
    guest.finish_guest_access();
    let _ = allowance.finalize_at(None, std::time::Instant::now());
    blocker
        .complete(
            success(b"blocker"),
            fixture.commit_control(&input, &allowance),
        )
        .await;
    let completion = blocker.take_owned_completion().unwrap().unwrap();
    assert!(matches!(
        completion.result,
        TransactionCompletionResult::Command(CommandCompletionDisposition::Durable { .. })
    ));
    drop((guest, completion, blocker, input, allowance));
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(5), pending)
            .await
            .unwrap()
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::StateConflict
    );
    assert!(waiting.take_result().unwrap().is_none());
    assert_eq!(fixture.owners.lanes.snapshot().keys, 0);
    assert_eq!(fixture.rows(Family::Command).await, 1);
    for family in [Family::State, Family::Inbox, Family::Outbox] {
        assert_eq!(fixture.rows(family).await, 0);
    }
    drop((waiting, envelope, budget));
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn scoped_preclaim_duplicates_share_one_queue_owner_without_takeover() {
    let fixture = Box::pin(Fixture::with_scoped_trigger()).await;
    let (scope, identity) = source();
    install_source(&fixture, &scope).await;
    let (blocker, mut input, allowance) = fixture.entity_invocation("blocker", "hot");
    input.principal.kind = latent_core::PrincipalKind::Trigger;
    let guest = blocker.admit(&input, &allowance).await.unwrap();
    guest.acquire(Mode::Command).unwrap();
    let (waiting, envelope, budget) = invocation(&fixture, &scope, &identity, Some("hot"));
    let mut pending = waiting.admit(&envelope, &budget);
    observe_wait(&fixture, &mut pending, 1, 0).await;
    let (duplicate, duplicate_input, duplicate_budget) =
        invocation(&fixture, &scope, &identity, Some("hot"));
    let mut duplicate_pending = duplicate.admit(&duplicate_input, &duplicate_budget);
    observe_wait(&fixture, &mut duplicate_pending, 1, 1).await;
    assert_eq!(fixture.native.snapshot().unwrap().ordinary.slots, 3);
    assert_eq!(fixture.rows(Family::Command).await, 1);
    assert_eq!(fixture.rows(Family::Inbox).await, 0);
    drop(pending);
    drop((waiting, envelope, budget));
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(5), duplicate_pending)
            .await
            .unwrap()
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::Unavailable
    );
    assert!(duplicate.take_result().unwrap().is_none());
    assert_eq!(fixture.owners.lanes.snapshot().queued, 0);
    assert_eq!(fixture.owners.entity_duplicate_waiter_count().unwrap(), 0);
    assert_eq!(fixture.owners.lanes.snapshot().active, 1);
    drop((duplicate, duplicate_input, duplicate_budget));
    assert_eq!(fixture.native.snapshot().unwrap().ordinary.slots, 1);
    guest.finish_guest_access();
    let _ = allowance.finalize_at(None, std::time::Instant::now());
    blocker
        .complete(
            success(b"blocker"),
            fixture.commit_control(&input, &allowance),
        )
        .await;
    let completion = blocker.take_owned_completion().unwrap().unwrap();
    assert!(matches!(
        completion.result,
        TransactionCompletionResult::Command(CommandCompletionDisposition::Durable { .. })
    ));
    drop((guest, completion, blocker, input, allowance));
    assert_eq!(fixture.rows(Family::Command).await, 1);
    assert_eq!(fixture.rows(Family::Inbox).await, 0);
    assert_eq!(fixture.owners.lanes.snapshot().keys, 0);
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}

//! Real OCC failure, opaque physical retirement, durable abort and explicit retry.
use super::*;
mod bounds;

fn retry(key: &str, fence: &t::AbortFence, request_id: &str) -> t::InvokeCommandRequest {
    let mut request = command(key, 1, false);
    request.retry_attempt = Some(t::RetryAttempt {
        request_id: request_id.into(),
        expected_abort: Some(fence.clone()),
    });
    request
}

async fn attempt(f: &Fixture, id: String, attempt: u64) -> latent_commit::atomic::CommandRecord {
    f.store
        .with_store(
            latent_state::store_io::StoreIoKind::Read,
            128 * 1024,
            move |store| {
                let view = store.snapshot()?;
                let id = latent_commit::atomic::Identity::parse_hex(&id).unwrap();
                let key = latent_commit::atomic::attempt_row_key(id, attempt);
                let bytes = view.get(&key)?.unwrap();
                latent_commit::atomic::validate_linked_row(&view, &key, &bytes)?;
                Ok(latent_commit::atomic::CommandRecord::decode(&bytes).unwrap())
            },
        )
        .unwrap()
        .await
        .unwrap()
        .unwrap()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_durable_conflict_abort_allows_one_explicit_retry_and_preserves_attempt_history(
) {
    let FirstAbort {
        fixture: mut f,
        original,
        fence,
        historical,
    } = first_abort().await;
    for change in ["command", "attempt", "transaction", "proof"] {
        let mut forged = fence.clone();
        match change {
            "command" => forged.command_id = "a".repeat(64),
            "attempt" => forged.attempt_id = "2".into(),
            "transaction" => forged.transaction_id = "a".repeat(64),
            "proof" => forged.owner_fence[0] ^= 1,
            _ => unreachable!(),
        }
        let denied = f
            .adapter()
            .invoke_command(context("alice").request(retry("conflicted", &forged, change)))
            .await;
        assert!(denied.is_err(), "{change}");
        assert_eq!(f.executions(), 2);
        assert_eq!(f.rows(Family::Attempt).await, 2);
        assert_eq!(f.rows(Family::Outbox).await, 1);
    }
    let current = f.deploy_compatible_revision().await;
    assert_ne!(
        current.revision.0,
        original.source.as_ref().unwrap().revision_id
    );
    let recovered = invoke(&f, "conflicted", 1, false).await;
    assert!(recovered.replayed);
    assert_eq!(
        recovered.command.as_ref().unwrap().proven_abort,
        Some(fence.clone())
    );
    assert_eq!(
        f.executions(),
        2,
        "aborted restart never implicitly runs the guest"
    );
    drop(recovered);
    let owner = concurrent_retry(&f, &fence).await;
    let committed = finished(owner).await;
    let body = success(&committed);
    assert_eq!(aggregate(&body.payload), 3);
    assert_eq!(committed.command.as_ref().unwrap().attempt_id, "2");
    assert_eq!(committed.command.as_ref().unwrap().source, original.source);
    assert_eq!(
        committed.command.as_ref().unwrap().fingerprint_sha256,
        original.fingerprint_sha256
    );
    let receipt = committed.command.as_ref().unwrap().commit.clone().unwrap();
    assert_eq!(receipt.effect_ids.len(), 1);
    assert_eq!(f.rows(Family::State).await, 1);
    assert_eq!(f.rows(Family::Outbox).await, 2);
    assert_eq!(f.rows(Family::Attempt).await, 3);
    assert_eq!(
        attempt(&f, original.command_id.clone(), 1).await,
        historical
    );
    drop(committed);
    let replay = f
        .adapter()
        .invoke_command(context("alice").request(retry("conflicted", &fence, "retry-original")))
        .await
        .unwrap()
        .into_inner();
    assert!(replay.replayed);
    assert_eq!(success(&replay), body);
    assert_eq!(
        replay.command.as_ref().unwrap().commit.as_ref(),
        Some(&receipt)
    );
    drop(replay);
    let stale = f
        .adapter()
        .invoke_command(context("alice").request(retry(
            "conflicted",
            &fence,
            "stale-prior-attempt",
        )))
        .await;
    assert!(stale.is_err());
    assert_eq!(f.executions(), 3);
    assert_eq!(f.backend.real.resource_snapshot().stores_created, 3);
    assert_eq!(f.rows(Family::Outbox).await, 2);
    policy::revoke(&f.policy);
    let denied = f
        .adapter()
        .invoke_command(context("alice").request(retry("conflicted", &fence, "retry-original")))
        .await
        .unwrap_err();
    assert_eq!(denied.code(), tonic::Code::PermissionDenied);
    assert_eq!(f.executions(), 3);
    assert_eq!(f.rows(Family::Outbox).await, 2);
    f.shutdown().await;
}

type Owner =
    tokio::task::JoinHandle<Result<tonic::Response<t::InvokeCommandResponse>, tonic::Status>>;

fn start(f: &Fixture, request: t::InvokeCommandRequest) -> Owner {
    let adapter = f.adapter();
    tokio::spawn(async move {
        adapter
            .invoke_command(context("alice").request(request))
            .await
    })
}
async fn entered(f: &Fixture) {
    tokio::time::timeout(Duration::from_secs(5), f.backend.imports.entered.notified())
        .await
        .unwrap();
}
async fn finished(owner: Owner) -> t::InvokeCommandResponse {
    tokio::time::timeout(Duration::from_secs(5), owner)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
        .into_inner()
}
async fn replay_retry(
    f: &Fixture,
    fence: &t::AbortFence,
    request_id: &str,
) -> t::InvokeCommandResponse {
    tokio::time::timeout(
        Duration::from_secs(10),
        f.adapter()
            .invoke_command(context("alice").request(retry("history", fence, request_id))),
    )
    .await
    .unwrap()
    .unwrap()
    .into_inner()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_retry_request_receipt_keeps_its_historical_attempt_while_later_work_runs() {
    let f = Fixture::with_concurrent_commands(true).await;
    let owner = start(&f, command("history", 1, false));
    entered(&f).await;
    let competing = invoke(&f, "first-competitor", 10, false).await;
    assert_eq!(aggregate(&success(&competing).payload), 10);
    drop(competing);
    f.backend.imports.release.notify_one();
    let aborted = finished(owner).await;
    let first = aborted
        .command
        .as_ref()
        .unwrap()
        .proven_abort
        .clone()
        .unwrap();
    assert_eq!(first.attempt_id, "1");
    assert_eq!(f.executions(), 2);
    drop(aborted);

    f.backend.imports.pause_read.store(true, Ordering::SeqCst);
    let owner = start(&f, retry("history", &first, "historical-request"));
    entered(&f).await;
    let competing = invoke(&f, "second-competitor", 20, false).await;
    assert_eq!(aggregate(&success(&competing).payload), 30);
    drop(competing);
    f.backend.imports.release.notify_one();
    let aborted = finished(owner).await;
    let second = aborted
        .command
        .as_ref()
        .unwrap()
        .proven_abort
        .clone()
        .unwrap();
    assert_eq!(second.attempt_id, "2");
    assert_ne!(first.transaction_id, second.transaction_id);
    assert_ne!(first.owner_fence, second.owner_fence);
    assert_eq!(f.executions(), 4);
    let historical = attempt(&f, first.command_id.clone(), 2).await;
    assert_eq!(
        historical.outcome(),
        latent_commit::atomic::Outcome::Aborted
    );
    drop(aborted);

    f.backend.imports.pause_read.store(true, Ordering::SeqCst);
    let owner = start(&f, retry("history", &second, "latest-request"));
    entered(&f).await;
    assert_eq!(f.executions(), 5);
    let prior = replay_retry(&f, &first, "historical-request").await;
    assert!(prior.replayed);
    assert_eq!(prior.command.as_ref().unwrap().attempt_id, "2");
    assert_eq!(
        prior.command.as_ref().unwrap().proven_abort,
        Some(second.clone())
    );
    assert!(prior.command.as_ref().unwrap().commit.is_none());
    assert_eq!(
        f.executions(),
        5,
        "a historical receipt cannot enter the paused later guest"
    );
    drop(prior);
    let stale = f
        .adapter()
        .invoke_command(context("alice").request(retry(
            "history",
            &first,
            "stale-completion-attempt",
        )))
        .await;
    assert!(stale.is_err());
    let current = replay_retry(&f, &second, "latest-request").await;
    assert!(current.replayed);
    assert_eq!(current.command.as_ref().unwrap().attempt_id, "3");
    assert_eq!(
        current.command.as_ref().unwrap().outcome,
        t::CommandOutcome::InProgress as i32
    );
    assert_eq!(f.executions(), 5);
    drop(current);
    f.backend.imports.release.notify_one();
    let committed = finished(owner).await;
    let body = success(&committed);
    assert_eq!(aggregate(&body.payload), 31);
    assert_eq!(committed.command.as_ref().unwrap().attempt_id, "3");
    let receipt = committed.command.as_ref().unwrap().commit.clone().unwrap();
    assert_eq!(receipt.effect_ids.len(), 1);
    drop(committed);
    historical_replays(&f, first, second, historical, body, receipt).await;
    f.shutdown().await;
}

struct FirstAbort {
    fixture: Fixture,
    original: t::CommandInspection,
    fence: t::AbortFence,
    historical: latent_commit::atomic::CommandRecord,
}
async fn first_abort() -> FirstAbort {
    let f = Fixture::with_concurrent_commands(true).await;
    let adapter = f.adapter();
    let owner = tokio::spawn(async move {
        adapter
            .invoke_command(context("alice").request(command("conflicted", 1, false)))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), f.backend.imports.entered.notified())
        .await
        .unwrap();
    assert_eq!(f.executions(), 1);
    let competing = invoke(&f, "competing", 2, false).await;
    assert_eq!(aggregate(&success(&competing).payload), 2);
    assert_eq!(f.executions(), 2);
    assert_eq!(f.rows(Family::Outbox).await, 1);
    drop(competing);
    f.backend.imports.release.notify_one();
    let aborted = tokio::time::timeout(Duration::from_secs(5), owner)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
        .into_inner();
    let original = aborted.command.as_ref().unwrap().clone();
    assert_eq!(original.outcome, t::CommandOutcome::Aborted as i32);
    assert!(original.metadata_durable && !original.application_state_committed);
    assert!(original.commit.is_none());
    let fence = original
        .proven_abort
        .clone()
        .expect("only an actual durable abort exposes a fence");
    assert_eq!(fence.owner_fence.len(), 32);
    assert_eq!(fence.command_id, original.command_id);
    assert_eq!(fence.attempt_id, "1");
    let historical = attempt(&f, original.command_id.clone(), 1).await;
    assert_eq!(
        historical.outcome(),
        latent_commit::atomic::Outcome::Aborted
    );
    assert_eq!(
        historical.abort_proof().unwrap().bytes().as_slice(),
        fence.owner_fence
    );
    assert_eq!(historical.transaction_id().hex(), fence.transaction_id);
    assert_eq!(f.rows(Family::State).await, 1);
    assert_eq!(f.rows(Family::Outbox).await, 1);
    assert_eq!(f.terminal_result_rows().await, 2);
    drop(aborted);
    let replay = invoke(&f, "conflicted", 1, false).await;
    assert!(replay.replayed);
    assert_eq!(
        replay.command.as_ref().unwrap().proven_abort,
        Some(fence.clone())
    );
    assert_eq!(
        f.executions(),
        2,
        "plain redelivery never retries the aborted mutator"
    );
    drop(replay);
    FirstAbort {
        fixture: f,
        original,
        fence,
        historical,
    }
}

async fn concurrent_retry(f: &Fixture, fence: &t::AbortFence) -> Owner {
    f.backend.imports.pause_read.store(true, Ordering::SeqCst);
    let adapter = f.adapter();
    let selected = retry("conflicted", fence, "retry-original");
    let owner = tokio::spawn(async move {
        adapter
            .invoke_command(context("alice").request(selected))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), f.backend.imports.entered.notified())
        .await
        .unwrap();
    assert_eq!(f.executions(), 3);
    let duplicate = f
        .adapter()
        .invoke_command(context("alice").request(retry("conflicted", fence, "retry-original")))
        .await
        .unwrap()
        .into_inner();
    assert!(duplicate.replayed);
    assert_eq!(duplicate.command.as_ref().unwrap().attempt_id, "2");
    assert_eq!(
        duplicate.command.as_ref().unwrap().outcome,
        t::CommandOutcome::InProgress as i32
    );
    drop(duplicate);
    let rival = f
        .adapter()
        .invoke_command(context("alice").request(retry("conflicted", fence, "retry-rival")))
        .await;
    assert!(rival.is_err());
    assert_eq!(f.executions(), 3);
    f.backend.imports.release.notify_one();
    owner
}

async fn historical_replays(
    f: &Fixture,
    first: t::AbortFence,
    second: t::AbortFence,
    historical: latent_commit::atomic::CommandRecord,
    body: i::Success,
    receipt: t::CommitReceipt,
) {
    let latest = replay_retry(f, &second, "latest-request").await;
    assert!(latest.replayed);
    assert_eq!(success(&latest), body);
    assert_eq!(
        latest.command.as_ref().unwrap().commit.as_ref(),
        Some(&receipt)
    );
    drop(latest);
    let prior = replay_retry(f, &first, "historical-request").await;
    assert!(prior.replayed);
    assert_eq!(prior.command.as_ref().unwrap().proven_abort, Some(second));
    assert_eq!(attempt(f, first.command_id, 2).await, historical);
    drop(prior);
    assert_eq!(f.executions(), 5);
    assert_eq!(f.backend.real.resource_snapshot().stores_created, 5);
    assert_eq!(f.rows(Family::State).await, 1);
    assert_eq!(f.rows(Family::Outbox).await, 3);
    assert_eq!(f.rows(Family::Attempt).await, 5);
    assert_eq!(f.terminal_result_rows().await, 5);
}

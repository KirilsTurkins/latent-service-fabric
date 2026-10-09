//! Retained aborts never acquire an implicit or out-of-window new generation.
use super::*;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_expired_abort_preserves_protective_identity_and_refuses_new_execution() {
    let FirstAbort {
        fixture: f,
        original,
        fence,
        historical,
    } = first_abort().await;
    assert!(historical.result_expires() < historical.identity_expires());
    f.clock
        .0
        .store(historical.result_expires(), Ordering::SeqCst);
    let denied = f
        .adapter()
        .invoke_command(context("alice").request(retry(
            "conflicted",
            &fence,
            "after-result-expiry",
        )))
        .await;
    assert!(denied.is_err());
    assert_eq!(f.executions(), 2);
    let replay = invoke(&f, "conflicted", 1, false).await;
    assert!(replay.replayed);
    let retained = replay.command.as_ref().unwrap();
    assert_eq!(retained.command_id, original.command_id);
    assert_eq!(retained.attempt_id, "1");
    assert_eq!(retained.outcome, t::CommandOutcome::Aborted as i32);
    assert_eq!(retained.proven_abort, Some(fence));
    assert!(!retained.retention.as_ref().unwrap().payload_available);
    assert!(retained.commit.is_none() && !retained.application_state_committed);
    drop(replay);
    assert_eq!(
        attempt(&f, original.command_id.clone(), 1).await,
        historical
    );
    f.clock
        .0
        .store(historical.identity_expires() + 1, Ordering::SeqCst);
    let denied = f
        .adapter()
        .invoke_command(context("alice").request(command("conflicted", 1, false)))
        .await
        .unwrap_err();
    assert_eq!(denied.code(), tonic::Code::PermissionDenied);
    assert_eq!(f.executions(), 2);
    assert_eq!(f.backend.real.resource_snapshot().stores_created, 2);
    assert_eq!(f.rows(Family::Command).await, 2);
    assert_eq!(f.rows(Family::Attempt).await, 2);
    assert_eq!(f.terminal_result_rows().await, 2);
    assert_eq!(f.rows(Family::State).await, 1);
    assert_eq!(f.rows(Family::Outbox).await, 1);
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_maximum_retry_attempts_preserve_all_aborts_and_refuse_a_fourth_generation() {
    let FirstAbort {
        fixture: f,
        original,
        mut fence,
        historical,
    } = first_abort().await;
    for (generation, delta, total) in [(2_u64, 20_u32, 22_u64), (3, 30, 52)] {
        f.backend.imports.pause_read.store(true, Ordering::SeqCst);
        let owner = start(
            &f,
            retry("conflicted", &fence, &format!("bounded-{generation}")),
        );
        entered(&f).await;
        let competing = invoke(&f, &format!("competitor-{generation}"), delta, false).await;
        assert_eq!(aggregate(&success(&competing).payload), total);
        drop(competing);
        f.backend.imports.release.notify_one();
        let aborted = finished(owner).await;
        let record = aborted.command.as_ref().unwrap();
        assert_eq!(record.outcome, t::CommandOutcome::Aborted as i32);
        assert!(record.metadata_durable && !record.application_state_committed);
        assert!(record.commit.is_none());
        let next = record.proven_abort.clone().unwrap();
        assert_eq!(next.attempt_id, generation.to_string());
        assert_ne!(next.transaction_id, fence.transaction_id);
        assert_ne!(next.owner_fence, fence.owner_fence);
        fence = next;
        drop(aborted);
        assert_eq!(f.executions(), generation * 2);
        assert_eq!(
            attempt(&f, original.command_id.clone(), 1).await,
            historical
        );
    }
    let denied = f
        .adapter()
        .invoke_command(context("alice").request(retry(
            "conflicted",
            &fence,
            "forbidden-fourth-generation",
        )))
        .await;
    assert!(denied.is_err());
    let replay = invoke(&f, "conflicted", 1, false).await;
    assert!(replay.replayed);
    assert_eq!(replay.command.as_ref().unwrap().attempt_id, "3");
    assert_eq!(replay.command.as_ref().unwrap().proven_abort, Some(fence));
    drop(replay);
    assert_eq!(f.executions(), 6);
    assert_eq!(f.backend.real.resource_snapshot().stores_created, 6);
    assert_eq!(f.rows(Family::State).await, 1);
    assert_eq!(f.rows(Family::Outbox).await, 3);
    assert_eq!(f.rows(Family::Attempt).await, 6);
    assert_eq!(f.terminal_result_rows().await, 6);
    f.shutdown().await;
}

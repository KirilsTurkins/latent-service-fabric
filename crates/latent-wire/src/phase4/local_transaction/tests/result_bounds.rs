use super::*;
use latent_capabilities::namespace::RecoverySelection;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_zero_and_oversized_retained_result_leave_no_state_or_effect_commit() {
    for maximum in [0, 64] {
        let f = Fixture::with_result_limit(
            false,
            Default::default(),
            RecoverySelection::OriginalCaller,
            &["alice"],
            maximum,
        )
        .await;
        let failed = invoke(&f, "bounded-result", 1, false).await;
        let command = failed.command.as_ref().unwrap();
        assert_eq!(command.outcome, t::CommandOutcome::RecoveryRequired as i32);
        assert!(!command.application_state_committed);
        assert!(!command.metadata_durable);
        assert!(command.commit.is_none());
        assert!(command.retained_result.is_none());
        assert_eq!(f.executions(), 1);
        assert_eq!(f.backend.real.resource_snapshot().stores_created, 1);
        assert_eq!(f.rows(Family::State).await, 0);
        assert_eq!(f.rows(Family::Outbox).await, 0);
        assert_eq!(f.terminal_result_rows().await, 0);
        assert_eq!(f.rows(Family::Command).await, 1);
        assert_eq!(f.rows(Family::Attempt).await, 1);
        drop(failed);
        let replay = invoke(&f, "bounded-result", 1, false).await;
        assert!(replay.replayed);
        assert_eq!(
            replay.command.as_ref().unwrap().outcome,
            t::CommandOutcome::InProgress as i32
        );
        assert_eq!(
            f.executions(),
            1,
            "an oversized result is never inferred to be a retryable abort"
        );
        assert_eq!(f.rows(Family::Outbox).await, 0);
        drop(replay);
        f.shutdown().await;
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_maximum_supported_result_ceiling_keeps_exact_replay_and_one_commit() {
    let f = Fixture::with_result_limit(
        false,
        Default::default(),
        RecoverySelection::OriginalCaller,
        &["alice"],
        latent_core::transaction_contract::VALUE_BYTES,
    )
    .await;
    let original = invoke(&f, "maximum-result", 1, false).await;
    let body = success(&original);
    assert!(body.payload.len() > 64);
    assert!(body.payload.len() <= latent_core::transaction_contract::VALUE_BYTES);
    let receipt = original.command.as_ref().unwrap().commit.clone().unwrap();
    drop(original);
    let replay = invoke(&f, "maximum-result", 1, false).await;
    assert!(replay.replayed);
    assert_eq!(success(&replay), body);
    assert_eq!(
        replay.command.as_ref().unwrap().commit.as_ref(),
        Some(&receipt)
    );
    assert_eq!(f.executions(), 1);
    assert_eq!(f.rows(Family::Command).await, 1);
    assert_eq!(f.terminal_result_rows().await, 1);
    assert_eq!(f.rows(Family::Outbox).await, 1);
    drop(replay);
    f.shutdown().await;
}

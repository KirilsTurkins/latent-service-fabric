use super::*;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_pending_restart_never_implicitly_reexecutes_the_interrupted_command() {
    let mut f = Fixture::new(true).await;
    let adapter = f.adapter();
    let mut request = command("interrupted", 1, false);
    request.invocation.as_mut().unwrap().activation_id = Some("pending-owner".into());
    let owner = tokio::spawn(async move {
        adapter
            .invoke_command(context("alice").request(request))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), f.backend.imports.entered.notified())
        .await
        .unwrap();
    assert_eq!(f.executions(), 1);
    assert_eq!(
        f.manager
            .cancel_for(
                &latent_core::TenantId(publication::TENANT.into()),
                &latent_core::ActivationId("pending-owner".into()),
                "cancel original command"
            )
            .unwrap(),
        latent_core::CancelDisposition::Accepted
    );
    f.backend.imports.release.notify_one();
    let denied = tokio::time::timeout(Duration::from_secs(5), owner)
        .await
        .unwrap()
        .unwrap()
        .unwrap_err();
    // Explicit cancellation revokes the original response authority as well
    // as commitment. Status recovery below uses a fresh authenticated caller.
    assert_eq!(denied.code(), tonic::Code::PermissionDenied);
    let pending = invoke(&f, "interrupted", 1, false).await;
    assert_eq!(
        pending.command.as_ref().unwrap().outcome,
        t::CommandOutcome::InProgress as i32
    );
    assert!(pending.replayed);
    drop(pending);
    assert_eq!(f.rows(Family::State).await, 0);
    assert_eq!(f.rows(Family::Outbox).await, 0);
    assert_eq!(f.terminal_result_rows().await, 0);
    assert_eq!(f.pending_result_rows().await, 1);
    f.restart().await;
    let replay = invoke(&f, "interrupted", 1, false).await;
    assert!(replay.replayed);
    assert_eq!(
        replay.command.as_ref().unwrap().outcome,
        t::CommandOutcome::InProgress as i32
    );
    assert_eq!(f.executions(), 1);
    assert_eq!(f.rows(Family::State).await, 0);
    assert_eq!(f.rows(Family::Outbox).await, 0);
    drop(replay);
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_compatible_rollout_preserves_the_first_accepted_source_and_receipt() {
    let mut f = Fixture::new(false).await;
    let original = invoke(&f, "rollout", 1, false).await;
    let inspection = original.command.clone().unwrap();
    let body = success(&original);
    drop(original);
    let current = f.deploy_compatible_revision().await;
    let original_source = inspection.source.as_ref().unwrap();
    assert_ne!(current.revision.0, original_source.revision_id);
    assert!(current.route_generation.0 > original_source.route_generation);
    let replay = invoke(&f, "rollout", 1, false).await;
    assert!(replay.replayed);
    assert_eq!(replay.command.as_ref().unwrap().source, inspection.source);
    assert_eq!(replay.command.as_ref().unwrap().commit, inspection.commit);
    assert_eq!(success(&replay), body);
    assert_eq!(f.executions(), 1);
    assert_eq!(f.rows(Family::Outbox).await, 1);
    drop(replay);
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_retention_capacity_rejects_new_work_and_preserves_guaranteed_replay() {
    let f = Fixture::with_quota(
        false,
        latent_state::namespace::NamespaceQuota {
            result_rows: 1,
            effect_rows: 1,
            ..Default::default()
        },
    )
    .await;
    let original = invoke(&f, "retained", 1, false).await;
    let body = success(&original);
    drop(original);
    let denied = f
        .adapter()
        .invoke_command(context("alice").request(command("pressure", 2, false)))
        .await
        .unwrap_err();
    assert_eq!(denied.code(), tonic::Code::ResourceExhausted);
    assert_eq!(
        f.executions(),
        1,
        "pressure rejected before another guest can acquire a command"
    );
    let replay = invoke(&f, "retained", 1, false).await;
    assert_eq!(success(&replay), body);
    assert!(replay.replayed);
    assert_eq!(f.rows(Family::Command).await, 1);
    assert_eq!(f.terminal_result_rows().await, 1);
    assert_eq!(f.rows(Family::Outbox).await, 1);
    drop(replay);
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_committed_replay_survives_owner_restart_without_state_or_effect_duplication()
{
    let mut f = Fixture::new(false).await;
    let original = invoke(&f, "restart", 3, false).await;
    let receipt = original.command.as_ref().unwrap().commit.clone().unwrap();
    let body = success(&original);
    drop(original);
    f.restart().await;
    let replay = invoke(&f, "restart", 3, false).await;
    assert!(replay.replayed);
    assert_eq!(success(&replay), body);
    assert_eq!(
        replay.command.as_ref().unwrap().commit.as_ref(),
        Some(&receipt)
    );
    assert_eq!(f.executions(), 1);
    assert_eq!(f.rows(Family::State).await, 1);
    assert_eq!(f.rows(Family::Outbox).await, 1);
    assert_eq!(f.rows(Family::Attempt).await, 1);
    drop(replay);
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_result_expiry_with_pending_effect_preserves_identity_and_never_executes_again(
) {
    let f = Fixture::new(false).await;
    let original = invoke(&f, "expiry", 1, false).await;
    let command_id = original.command.as_ref().unwrap().command_id.clone();
    let effects = success(&original).effect_ids;
    assert_eq!(effects.len(), 1);
    drop(original);
    f.clock.0.store(11_001, Ordering::SeqCst);
    let replay = invoke(&f, "expiry", 1, false).await;
    assert!(replay.replayed);
    assert_eq!(replay.command.as_ref().unwrap().command_id, command_id);
    assert!(
        !replay
            .command
            .as_ref()
            .unwrap()
            .retention
            .as_ref()
            .unwrap()
            .payload_available
    );
    assert_eq!(
        replay
            .command
            .as_ref()
            .unwrap()
            .commit
            .as_ref()
            .unwrap()
            .effect_ids,
        effects
    );
    assert!(matches!(
        replay.invocation.as_ref().unwrap().result,
        Some(i::invoke_response::Result::PlatformFailure(_))
    ));
    assert_eq!(f.executions(), 1);
    assert_eq!(f.rows(Family::Outbox).await, 1);
    drop(replay);
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_zero_max_and_oversized_command_keys_are_bounded_before_execution() {
    let f = Fixture::new(false).await;
    for key in [
        String::new(),
        "x".repeat(latent_core::transaction_contract::IDENTITY_BYTES + 1),
    ] {
        assert!(f
            .adapter()
            .invoke_command(context("alice").request(command(&key, 1, false)))
            .await
            .is_err());
    }
    assert_eq!(f.executions(), 0);
    assert_eq!(f.rows(Family::Command).await, 0);
    let key = "x".repeat(latent_core::transaction_contract::IDENTITY_BYTES);
    let original = invoke(&f, &key, 1, false).await;
    let receipt = original.command.as_ref().unwrap().commit.clone().unwrap();
    drop(original);
    let replay = invoke(&f, &key, 1, false).await;
    assert!(replay.replayed);
    assert_eq!(
        replay.command.as_ref().unwrap().commit.as_ref(),
        Some(&receipt)
    );
    assert_eq!(f.executions(), 1);
    assert_eq!(f.rows(Family::Outbox).await, 1);
    drop(replay);
    f.shutdown().await;
}

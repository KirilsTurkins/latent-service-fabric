use super::*;
use latent_state::namespace::{NamespaceQuota, NamespaceTransition};

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_namespace_recreation_uses_new_incarnation_and_denies_stale_selector() {
    let f = Fixture::new(false).await;
    let quiesced = f
        .namespace_transition(NamespaceTransition::Quiesce)
        .await
        .unwrap();
    let retired = f
        .namespace_transition(NamespaceTransition::Retire)
        .await
        .unwrap();
    let destroyed = f
        .namespace_transition(NamespaceTransition::Destroy)
        .await
        .unwrap();
    let recreated = f
        .namespace_transition(NamespaceTransition::Recreate {
            state_schema: destroyed.state_schema.clone(),
            quota: NamespaceQuota::default(),
        })
        .await
        .unwrap();
    assert_eq!(quiesced.version.incarnation, 1);
    assert_eq!(retired.version.incarnation, 1);
    assert_eq!(recreated.version.incarnation, 2);
    assert!(recreated.version.generation > destroyed.version.generation);
    f.authorize_incarnation(2);
    assert_eq!(
        f.adapter()
            .invoke_command(context("alice").request(command("recreated", 1, false)))
            .await
            .unwrap_err()
            .code(),
        tonic::Code::PermissionDenied
    );
    assert_eq!(f.executions(), 0);
    let mut current = command("recreated", 1, false);
    current
        .command
        .as_mut()
        .unwrap()
        .namespace
        .as_mut()
        .unwrap()
        .incarnation = "2".into();
    let original = f
        .adapter()
        .invoke_command(context("alice").request(current.clone()))
        .await
        .unwrap()
        .into_inner();
    let body = success(&original);
    let identity = original.command.as_ref().unwrap().command_id.clone();
    drop(original);
    let replay = f
        .adapter()
        .invoke_command(context("alice").request(current))
        .await
        .unwrap()
        .into_inner();
    assert!(replay.replayed);
    assert_eq!(success(&replay), body);
    assert_eq!(replay.command.as_ref().unwrap().command_id, identity);
    assert_eq!(
        replay
            .command
            .as_ref()
            .unwrap()
            .key
            .as_ref()
            .unwrap()
            .namespace
            .as_ref()
            .unwrap()
            .incarnation,
        "2"
    );
    drop(replay);
    assert_eq!(f.executions(), 1);
    assert_eq!(f.rows(Family::State).await, 1);
    assert_eq!(f.rows(Family::Outbox).await, 1);
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_unresolved_effect_and_retained_result_block_namespace_destruction_and_recreation(
) {
    let f = Fixture::new(false).await;
    let original = invoke(&f, "protected", 1, false).await;
    let receipt = original.command.as_ref().unwrap().commit.clone().unwrap();
    drop(original);
    f.namespace_transition(NamespaceTransition::Quiesce)
        .await
        .unwrap();
    f.namespace_transition(NamespaceTransition::Retire)
        .await
        .unwrap();
    let denied = f
        .namespace_transition(NamespaceTransition::Destroy)
        .await
        .unwrap_err();
    assert_eq!(denied.code, PlatformErrorCode::StateConflict);
    assert_eq!(f.executions(), 1);
    assert_eq!(f.rows(Family::Command).await, 1);
    assert_eq!(f.terminal_result_rows().await, 1);
    assert_eq!(f.rows(Family::Outbox).await, 1);
    assert_eq!(receipt.effect_ids.len(), 1);
    assert!(f
        .adapter()
        .invoke_command(context("alice").request(command("protected", 1, false)))
        .await
        .is_err());
    assert_eq!(f.executions(), 1);
    f.shutdown().await;
}

//! Existing installed runtime and compiled guest, with the original live owner.
use super::*;

fn request(f: &Fixture, key: &str) -> t::CancelCommandRequest {
    let mut original = f.lookup_request(key);
    original.attempt_id = Some("1".into());
    t::CancelCommandRequest {
        command: Some(original),
        reason: "original managed request".into(),
    }
}

type CommandTask =
    tokio::task::JoinHandle<Result<tonic::Response<t::InvokeCommandResponse>, tonic::Status>>;

async fn staged_command(f: &Fixture, key: &'static str) -> CommandTask {
    f.backend
        .imports
        .pause_after_stage
        .store(true, Ordering::SeqCst);
    let adapter = f.adapter();
    let owner = tokio::spawn(async move {
        adapter
            .invoke_command(context("alice").request(command(key, 1, false)))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), f.backend.imports.staged.notified())
        .await
        .unwrap();
    owner
}

fn live_activation(f: &Fixture, expected_command: Option<&str>) -> latent_core::ActivationId {
    let roots = f
        .manager
        .journal()
        .inspect_roots(
            &latent_core::TenantId(publication::TENANT.into()),
            &latent_core::ServiceId(publication::SERVICE.into()),
            None,
            8,
            None,
        )
        .unwrap();
    assert_eq!(roots.nodes.len(), 1);
    if let Some(expected) = expected_command {
        assert_eq!(
            roots.nodes[0]
                .transaction_staging
                .as_ref()
                .unwrap()
                .command_id,
            expected
        );
    }
    roots.nodes[0].activation_id.clone()
}

fn terminal(
    f: &Fixture,
    id: &latent_core::ActivationId,
) -> Option<latent_core::ActivationTerminalState> {
    f.manager
        .status(&latent_core::TenantId(publication::TENANT.into()), id)
        .unwrap()
        .unwrap()
        .terminal_state
}

fn assert_pending(command: &t::CommandInspection) {
    assert_eq!(command.outcome, t::CommandOutcome::RecoveryRequired as i32);
    assert!(!command.metadata_durable && !command.application_state_committed);
    assert!(
        command.commit.is_none()
            && command.proven_abort.is_none()
            && command.retained_result.is_none()
    );
}

async fn finish_guest(f: &Fixture, owner: CommandTask) {
    f.backend.imports.continue_after_stage.notify_one();
    let returned = tokio::time::timeout(Duration::from_secs(5), owner)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(returned.unwrap_err().code(), tonic::Code::PermissionDenied);
    assert_eq!(f.manager.cancellation_snapshot().active_registrations, 0);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_installed_cancellation_reaches_only_original_live_command() {
    let f = Fixture::new(false).await;
    f.install_cancellation_management().await;
    let command_owner = staged_command(&f, "original-cancel").await;
    let original = f
        .recovery_backend()
        .await
        .execute_state(context("alice"), f.lookup_request("original-cancel").into())
        .await
        .unwrap()
        .into_parts();
    let contract::Response::LookupCommand(before) = &original.0 else {
        panic!("protected original absent")
    };
    let before = before.command.as_ref().unwrap().clone();
    assert_pending(&before);
    let original_activation = live_activation(&f, Some(&before.command_id));
    drop(original);
    assert_eq!(f.executions(), 1);
    assert_eq!(f.manager.cancellation_snapshot().active_registrations, 1);
    let requested = f
        .adapter()
        .cancel_command(context("alice").request(request(&f, "original-cancel")))
        .await;
    // Preserve cleanup even if the baseline lacks the installed route.
    if requested.is_err() {
        f.backend.imports.continue_after_stage.notify_one();
        let returned = tokio::time::timeout(Duration::from_secs(5), command_owner)
            .await
            .unwrap()
            .unwrap();
        drop(returned);
        f.shutdown().await;
        panic!("installed cancellation failed to request original live owner");
    }
    let requested = requested.unwrap().into_inner();
    assert_eq!(
        requested.disposition,
        t::CommandCancelDisposition::Requested as i32
    );
    let associated = requested.command.as_ref().unwrap();
    assert_eq!(associated.command_id, before.command_id);
    assert_eq!(associated.attempt_id, before.attempt_id);
    assert_eq!(associated.source, before.source);
    assert_pending(associated);
    let denied = f
        .adapter()
        .cancel_command(context("bob").request(request(&f, "original-cancel")))
        .await
        .unwrap_err();
    assert_eq!(denied.code(), tonic::Code::PermissionDenied);
    let mut wrong = request(&f, "original-cancel");
    wrong.command.as_mut().unwrap().attempt_id = Some("01".into());
    let wrong = f
        .adapter()
        .cancel_command(context("alice").request(wrong))
        .await
        .unwrap_err();
    assert_eq!(wrong.code(), tonic::Code::InvalidArgument);
    assert_eq!(f.rows(Family::State).await, 0);
    assert_eq!(f.rows(Family::Outbox).await, 0);
    finish_guest(&f, command_owner).await;
    assert_eq!(
        terminal(&f, &original_activation),
        Some(latent_core::ActivationTerminalState::Cancelled)
    );
    assert_eq!(f.rows(Family::State).await, 0);
    assert_eq!(f.rows(Family::Outbox).await, 0);
    assert_eq!(f.manager.cancellation_snapshot().active_registrations, 0);
    drop(requested);
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_cancellation_denial_and_retired_pending_owner_remain_unknown() {
    use latent_policy::capability::{MutationRequest, RecordKind};
    let f = Fixture::new(false).await;
    f.install_cancellation_management().await;
    let command_owner = staged_command(&f, "denied-cancel").await;
    let original_activation = live_activation(&f, None);
    let current = f
        .policy
        .get(
            publication::TENANT,
            RecordKind::Policy,
            "state",
            64 * 1024,
            Instant::now() + Duration::from_secs(5),
        )
        .unwrap();
    let document = current
        .value()
        .as_ref()
        .unwrap()
        .document
        .as_ref()
        .unwrap()
        .clone();
    drop(current);
    policy::revoke(&f.policy);
    let denied = f
        .adapter()
        .cancel_command(context("alice").request(request(&f, "denied-cancel")))
        .await
        .unwrap_err();
    assert_eq!(denied.code(), tonic::Code::PermissionDenied);
    assert_eq!(f.manager.cancellation_snapshot().active_registrations, 1);
    finish_guest(&f, command_owner).await;
    assert_ne!(
        terminal(&f, &original_activation),
        Some(latent_core::ActivationTerminalState::Cancelled)
    );
    assert_eq!(f.manager.cancellation_snapshot().active_registrations, 0);
    let current = f
        .policy
        .get(
            publication::TENANT,
            RecordKind::Policy,
            "state",
            64 * 1024,
            Instant::now() + Duration::from_secs(5),
        )
        .unwrap();
    let revision = current.value().as_ref().unwrap().revision;
    drop(current);
    f.policy
        .mutate(
            MutationRequest {
                tenant: publication::TENANT,
                actor: "compiled-guest-test-operator",
                kind: RecordKind::Policy,
                id: "state",
                operation_id: "fresh-cancel-read-policy",
                expected_revision: revision,
                document: Some(document.as_bytes()),
            },
            Instant::now() + Duration::from_secs(5),
            |_| Ok(()),
        )
        .unwrap();
    let unknown = f
        .adapter()
        .cancel_command(context("alice").request(request(&f, "denied-cancel")))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(
        unknown.disposition,
        t::CommandCancelDisposition::RecoveryRequired as i32
    );
    assert_pending(unknown.command.as_ref().unwrap());
    assert_eq!(f.executions(), 1);
    assert_eq!(f.rows(Family::State).await, 0);
    assert_eq!(f.rows(Family::Outbox).await, 0);
    assert_eq!(f.pending_result_rows().await, 1);
    assert_eq!(f.terminal_result_rows().await, 0);
    drop(unknown);
    f.shutdown().await;
}

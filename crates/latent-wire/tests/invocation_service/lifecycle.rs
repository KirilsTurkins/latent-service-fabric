use std::sync::atomic::Ordering;

use latent_core::{ActivationClock, ActivationTerminalState};
use latent_wire::invocation::{proto, InvocationService};
use tonic::Code;

use super::support::{authenticated, cancel, finish, pending, request, scoped, status, Harness};

#[tokio::test]
async fn pending_id_supports_scoped_status_and_all_cancellation_dispositions() {
    let harness = Harness::standard();
    let adapter = harness.adapter();
    harness.artifacts.gate.close();
    let mut invocation = Box::pin(adapter.invoke(authenticated(request("pending"))));
    pending(invocation.as_mut()).await;
    assert_eq!(status(&adapter, "pending").await.phase, "queued");
    for administrator in [false, true] {
        let foreign_status = finish(adapter.get_activation(scoped(
            proto::GetActivationRequest {
                activation_id: "pending".to_owned(),
            },
            "tenant-b",
            administrator,
        )))
        .await
        .expect_err("foreign status hidden");
        assert_eq!(foreign_status.code(), Code::NotFound);
        let foreign_cancel = finish(adapter.cancel(scoped(
            proto::CancelRequest {
                activation_id: "pending".to_owned(),
                reason: "foreign".to_owned(),
            },
            "tenant-b",
            administrator,
        )))
        .await
        .expect("foreign cancellation hidden")
        .into_inner();
        assert_eq!(
            foreign_cancel.disposition,
            proto::CancelDisposition::NotFound as i32
        );
    }
    assert_eq!(
        finish(adapter.invoke(authenticated(request("pending"))))
            .await
            .expect_err("duplicate owner")
            .code(),
        Code::AlreadyExists,
    );
    assert_eq!(
        cancel(&adapter, "pending").await.disposition,
        proto::CancelDisposition::Accepted as i32
    );
    let response = finish(invocation)
        .await
        .expect("accepted cancellation receipt")
        .into_inner();
    let Some(proto::invoke_response::Result::PlatformFailure(failure)) = response.result else {
        panic!("cancellation is a platform outcome");
    };
    assert_eq!(failure.code, "cancelled");
    let terminal = status(&adapter, "pending").await;
    assert_eq!(terminal.terminal_state.as_deref(), Some("cancelled"));
    assert!(terminal.final_consumption.is_some());
    let late = cancel(&adapter, "pending").await;
    assert_eq!(
        late.disposition,
        proto::CancelDisposition::AlreadyTerminal as i32
    );
    assert_eq!(late.terminal_state.as_deref(), Some("cancelled"));
    assert_eq!(
        cancel(&adapter, "unknown").await.disposition,
        proto::CancelDisposition::NotFound as i32
    );
    harness.artifacts.gate.open();
    finish(adapter.invoke(authenticated(request("reclaimed-cell"))))
        .await
        .expect("cell reused");
    harness.assert_idle();
}

#[tokio::test]
async fn dropping_one_running_rpc_finalizes_only_its_own_activation() {
    let harness = Harness::new(2, 8);
    let adapter = harness.adapter();
    harness.backend.gate.close();
    let mut abandoned = Box::pin(adapter.invoke(authenticated(request("abandoned"))));
    let mut survivor = Box::pin(adapter.invoke(authenticated(request("survivor"))));
    pending(abandoned.as_mut()).await;
    pending(survivor.as_mut()).await;
    assert_eq!(status(&adapter, "abandoned").await.phase, "running");
    assert_eq!(status(&adapter, "survivor").await.phase, "running");
    drop(abandoned);
    assert_eq!(
        status(&adapter, "abandoned")
            .await
            .terminal_state
            .as_deref(),
        Some("cancelled")
    );
    assert_eq!(status(&adapter, "survivor").await.terminal_state, None);
    assert_eq!(
        harness.manager.cancellation_snapshot().active_registrations,
        1
    );
    harness.backend.gate.open();
    let response = finish(survivor)
        .await
        .expect("unrelated call survives")
        .into_inner();
    assert!(matches!(
        response.result,
        Some(proto::invoke_response::Result::Success(_))
    ));
    assert_eq!(harness.backend.entered.load(Ordering::Relaxed), 2);
    assert_eq!(
        status(&adapter, "abandoned")
            .await
            .terminal_state
            .as_deref(),
        Some("cancelled")
    );
    finish(adapter.invoke(authenticated(request("healthy-cell"))))
        .await
        .expect("surviving capacity reusable");
    harness.assert_idle();
}

#[tokio::test]
async fn retained_duplicate_rejection_then_eviction_allows_a_new_id_owner() {
    let harness = Harness::new(1, 1);
    let adapter = harness.adapter();
    finish(adapter.invoke(authenticated(request("reusable-id"))))
        .await
        .expect("first owner");
    assert_eq!(
        finish(adapter.invoke(authenticated(request("reusable-id"))))
            .await
            .expect_err("retained duplicate")
            .code(),
        Code::AlreadyExists,
    );
    finish(adapter.invoke(authenticated(request("eviction"))))
        .await
        .expect("second terminal");
    assert_eq!(
        finish(
            adapter.get_activation(authenticated(proto::GetActivationRequest {
                activation_id: "reusable-id".to_owned(),
            }))
        )
        .await
        .expect_err("bounded retention evicted old identity")
        .code(),
        Code::NotFound,
    );
    finish(adapter.invoke(authenticated(request("reusable-id"))))
        .await
        .expect("new owner after eviction");
    assert_eq!(
        status(&adapter, "reusable-id")
            .await
            .terminal_state
            .as_deref(),
        Some("completed")
    );
    assert_eq!(harness.backend.entered.load(Ordering::Relaxed), 3);
    assert_eq!(harness.manager.journal().snapshot().terminal, 1);
    harness.assert_idle();
}

#[tokio::test]
async fn expired_deadline_rejects_before_identity_and_live_timeout_stops_owned_work() {
    let harness = Harness::standard();
    let adapter = harness.adapter();
    let mut expired = request("expired");
    expired.deadline_unix_millis = Some(harness.clock.sample().unix_millis().saturating_sub(1));
    assert_eq!(
        finish(adapter.invoke(authenticated(expired)))
            .await
            .expect_err("expired request")
            .code(),
        Code::DeadlineExceeded
    );
    assert_eq!(harness.manager.journal().snapshot().begun, 0);
    harness.backend.gate.close();
    let mut input = authenticated(request("live-timeout"));
    input
        .metadata_mut()
        .insert("grpc-timeout", "200m".parse().expect("timeout header"));
    let mut invocation = Box::pin(adapter.invoke(input));
    pending(invocation.as_mut()).await;
    assert_eq!(status(&adapter, "live-timeout").await.phase, "running");
    let result = finish(invocation).await;
    match result {
        Err(error) => assert_eq!(error.code(), Code::DeadlineExceeded),
        Ok(response) => {
            let Some(proto::invoke_response::Result::PlatformFailure(error)) =
                response.into_inner().result
            else {
                panic!("deadline must be a platform failure");
            };
            assert_eq!(error.code, "deadline-exceeded");
        }
    }
    let terminal = status(&adapter, "live-timeout").await;
    assert_eq!(
        terminal.terminal_state.as_deref(),
        Some("deadline_exceeded")
    );
    assert_eq!(
        harness.status("live-timeout").terminal_state,
        Some(ActivationTerminalState::DeadlineExceeded)
    );
    assert!(terminal.final_consumption.is_some());
    harness.assert_idle();
}

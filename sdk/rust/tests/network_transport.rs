#![cfg(feature = "transport")]

mod network_support;

#[path = "network_cases/lifecycle.rs"]
mod lifecycle;

use latent_core::{ActivationId, TenantId};
use latent_sdk::{
    network::{management::*, FailureKind},
    CancelResponse, InvocationOutcome, LatentClient,
};
use network_support::{request, wait_until, Peer};
use std::{sync::atomic::Ordering, time::Duration};
use tokio::time::Instant;

#[tokio::test]
async fn channel_is_reused_outcomes_stay_distinct_and_shutdown_reaps_real_owners() {
    let peer = Peer::start().await;
    let client = peer.client();
    assert_eq!(client.usage().sockets, 0);
    for (index, mode) in ["success", "declared", "platform"].into_iter().enumerate() {
        let outcome = client
            .invoke(request(&format!("call-{index}"), mode))
            .await
            .unwrap();
        match outcome {
            InvocationOutcome::Succeeded(value) => assert_eq!(value.payload, b"success"),
            InvocationOutcome::DeclaredError(value) => {
                assert_eq!(value.error.code, "domain-failure");
            }
            InvocationOutcome::PlatformFailure(value) => assert_eq!(
                value.error.code,
                latent_core::PlatformErrorCode::PermissionDenied
            ),
        }
    }
    assert_eq!(peer.state.accepted.load(Ordering::Acquire), 1);
    assert_eq!(client.usage().sockets, 1);
    client
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap();
    let usage = client.usage();
    assert_eq!(
        (
            usage.active_calls,
            usage.reserved_message_bytes,
            usage.executor_tasks,
            usage.sockets
        ),
        (0, 0, 0, 0)
    );
    wait_until(|| peer.state.open.load(Ordering::Acquire) == 0).await;
    peer.stop().await;
}

#[tokio::test]
async fn dropped_wait_does_not_send_cancel_and_known_identity_recovers_status() {
    let peer = Peer::start().await;
    let client = peer.client();
    let active = client.clone();
    let call = tokio::spawn(async move { active.invoke(request("lost-reply", "hold")).await });
    wait_until(|| peer.state.invocations.load(Ordering::Acquire) == 1).await;
    call.abort();
    assert!(call.await.unwrap_err().is_cancelled());
    assert_eq!(peer.state.cancellations.load(Ordering::Acquire), 0);
    let identity = ActivationId("lost-reply".into());
    let status = client.get_activation(&identity).await.unwrap();
    assert!(status.terminal_state.is_none());
    assert_eq!(
        client
            .cancel(&identity, "explicit caller request")
            .await
            .unwrap(),
        CancelResponse::Accepted
    );
    let status = client.get_activation(&identity).await.unwrap();
    assert_eq!(
        status.terminal_state,
        Some(latent_core::ActivationTerminalState::Cancelled)
    );
    assert_eq!(peer.state.invocations.load(Ordering::Acquire), 1);
    assert_eq!(peer.state.cancellations.load(Ordering::Acquire), 1);
    client
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap();
    peer.stop().await;
}

#[tokio::test]
async fn absolute_deadline_and_capacity_do_not_create_hidden_retries_or_extra_channels() {
    let peer = Peer::start().await;
    let mut config = peer.config();
    config.limits.maximum_calls = 1;
    let client = latent_sdk::network::RpcClient::new(config).unwrap();
    let active = client.clone();
    // Keep real socket setup inside its readiness watchdog. Only advance the
    // deadline clock after the peer has observed the one accepted invocation.
    let deadline = Instant::now() + Duration::from_secs(30);
    let call = tokio::spawn(async move {
        active
            .invoke_until(request("bounded", "hold"), deadline)
            .await
    });
    wait_until(|| peer.state.invocations.load(Ordering::Acquire) == 1).await;
    let failure = client
        .invoke_until(
            request("excess", "success"),
            Instant::now() + Duration::from_secs(1),
        )
        .await
        .unwrap_err();
    assert_eq!(failure.kind, FailureKind::Capacity);
    assert!(!failure.dispatched);
    assert!(client.usage().reserved_message_bytes > 0);
    assert!(!call.is_finished());
    tokio::time::pause();
    tokio::time::advance(deadline - Instant::now()).await;
    let failure = tokio::time::timeout_at(deadline + Duration::from_millis(1), call)
        .await
        .expect("the original absolute deadline must end the call")
        .unwrap()
        .unwrap_err();
    tokio::time::resume();
    assert_eq!(failure.kind, FailureKind::Deadline);
    assert!(failure.dispatched);
    assert!(!failure.outcome_known);
    assert_eq!(failure.recovery.activation_id.as_deref(), Some("bounded"));
    assert_eq!(peer.state.invocations.load(Ordering::Acquire), 1);
    assert_eq!(peer.state.accepted.load(Ordering::Acquire), 1);
    client
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap();
    peer.stop().await;
}

#[tokio::test]
async fn tenant_denial_and_response_corruption_are_not_guest_failures() {
    let peer = Peer::start().await;
    let mut config = peer.config();
    config.tenant = TenantId("foreign".into());
    let denied = latent_sdk::network::RpcClient::new(config).unwrap();
    let mut call = request("foreign", "success");
    call.target.tenant = TenantId("foreign".into());
    let failure = denied
        .invoke_until(call, Instant::now() + Duration::from_secs(1))
        .await
        .unwrap_err();
    assert_eq!(failure.kind, FailureKind::Rejected);
    assert_eq!(failure.grpc_code, Some(7));
    let client = peer.client();
    let failure = client
        .invoke_until(
            request("wrong-id", "wrong-id"),
            Instant::now() + Duration::from_secs(1),
        )
        .await
        .unwrap_err();
    assert_eq!(failure.kind, FailureKind::InvalidResponse);
    assert!(!failure.outcome_known);
    denied
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap();
    client
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap();
    peer.stop().await;
}

#[tokio::test]
async fn mutation_loss_retains_recovery_audit_and_exact_explicit_replay() {
    let peer = Peer::start().await;
    let client = peer.client();
    let request = network_support::policy("lost-operation");
    let failure = client
        .apply_policy_until(request.clone(), Instant::now() + Duration::from_millis(100))
        .await
        .unwrap_err();
    assert_eq!(failure.kind, FailureKind::Deadline);
    assert!(!failure.outcome_known);
    assert_eq!(
        failure.recovery.operation_id.as_deref(),
        Some("lost-operation")
    );
    let known = client
        .get_policy_operation_until(
            GetPolicyOperationRequest {
                operation_id: "lost-operation".into(),
            },
            Instant::now() + Duration::from_secs(1),
        )
        .await
        .unwrap();
    assert_eq!(known.value.receipt.as_ref().unwrap().generation, 2);
    let replay = client
        .apply_policy_until(request, Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
    assert_eq!(replay.value.receipt, known.value.receipt);
    assert_eq!(
        replay.audit.as_ref().unwrap().attempt_sequence,
        Some(u64::MAX)
    );
    assert_eq!(peer.state.mutations.load(Ordering::Acquire), 1);
    let unknown = client
        .get_policy_operation_until(
            GetPolicyOperationRequest {
                operation_id: "unknown".into(),
            },
            Instant::now() + Duration::from_secs(1),
        )
        .await
        .unwrap();
    assert!(unknown.value.receipt.is_none());
    client
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap();
    peer.stop().await;
}

#[tokio::test]
async fn pages_provider_inspection_presence_and_reply_sizes_are_bounded() {
    let peer = Peer::start().await;
    let client = peer.client();
    client
        .apply_policy_until(
            network_support::policy("create"),
            Instant::now() + Duration::from_secs(1),
        )
        .await
        .unwrap();
    let list = client
        .list_policies_until(
            ListPoliciesRequest {
                record_kind: 1,
                page: Some(PageRequest {
                    page_size: 1,
                    page_token: None,
                }),
            },
            Instant::now() + Duration::from_secs(1),
        )
        .await
        .unwrap();
    assert_eq!(list.value.policies.len(), 1);
    let list = client
        .list_capabilities_until(
            ListCapabilitiesRequest {
                deployment_id: "deployment".into(),
                page: Some(PageRequest {
                    page_size: 1,
                    page_token: None,
                }),
                ..Default::default()
            },
            Instant::now() + Duration::from_secs(1),
        )
        .await
        .unwrap();
    assert_eq!(
        list.value.capabilities[0]
            .inspection
            .as_ref()
            .unwrap()
            .provider_configuration_epoch,
        u64::MAX
    );
    assert!(client
        .list_policies_until(
            ListPoliciesRequest {
                record_kind: 1,
                page: Some(PageRequest {
                    page_size: 0,
                    page_token: None
                })
            },
            Instant::now() + Duration::from_secs(1)
        )
        .await
        .is_err());
    let mut config = peer.config();
    config.limits.maximum_response_bytes = 128;
    let small = latent_sdk::network::RpcClient::new(config).unwrap();
    let failure = small
        .invoke_until(
            request("large", "oversize"),
            Instant::now() + Duration::from_secs(1),
        )
        .await
        .unwrap_err();
    assert!(failure.dispatched);
    assert!(!failure.outcome_known);
    small
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap();
    client
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap();
    peer.stop().await;
}

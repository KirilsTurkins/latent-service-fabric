#![cfg(feature = "transport")]

mod network_support;

#[path = "network_cases/lifecycle.rs"]
mod lifecycle;

use latent_core::TenantId;
use latent_sdk::management::*;
use network_support::{request, wait_until, Peer};
use std::{sync::atomic::Ordering, time::Duration};
use tokio::time::Instant;

fn options_until(deadline: Instant) -> CallOptions {
    CallOptions {
        timeout_millis: Some(
            u64::try_from(
                deadline
                    .saturating_duration_since(Instant::now())
                    .as_millis(),
            )
            .unwrap(),
        ),
    }
}

async fn expire_call<T>(call: tokio::task::JoinHandle<T>, deadline: Instant) -> T {
    assert!(!call.is_finished());
    tokio::time::pause();
    tokio::time::advance(deadline - Instant::now()).await;
    let result = tokio::time::timeout_at(deadline + Duration::from_millis(1), call)
        .await
        .expect("the original absolute deadline must end the call")
        .unwrap();
    tokio::time::resume();
    result
}

#[tokio::test]
async fn channel_is_reused_outcomes_stay_distinct_and_shutdown_reaps_real_owners() {
    let peer = Peer::start().await;
    let client = peer.client();
    assert_eq!(client.usage().sockets, 0);
    for (index, mode) in ["success", "declared", "platform"].into_iter().enumerate() {
        let outcome = client
            .invoke(
                request(&format!("call-{index}"), mode),
                CallOptions::default(),
            )
            .await
            .unwrap();
        match mode {
            "success" => assert_eq!(outcome.value.success.unwrap().payload, b"success"),
            "declared" => assert_eq!(outcome.value.declared_error.unwrap().code, "domain-failure"),
            "platform" => assert_eq!(
                outcome.value.platform_failure.unwrap().code,
                "permission-denied"
            ),
            _ => unreachable!(),
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
    let call = tokio::spawn(async move {
        active
            .invoke(request("lost-reply", "hold"), CallOptions::default())
            .await
    });
    wait_until(|| peer.state.invocations.load(Ordering::Acquire) == 1).await;
    call.abort();
    assert!(call.await.unwrap_err().is_cancelled());
    assert_eq!(peer.state.cancellations.load(Ordering::Acquire), 0);
    let identity = "lost-reply".to_owned();
    let status = client
        .get_activation(
            GetActivationRequest {
                activation_id: identity.clone(),
            },
            CallOptions::default(),
        )
        .await
        .unwrap();
    assert!(status.value.terminal_state.is_none());
    assert_eq!(
        client
            .cancel(
                CancelRequest {
                    activation_id: identity.clone(),
                    reason: "explicit caller request".into()
                },
                CallOptions::default()
            )
            .await
            .unwrap()
            .value
            .disposition,
        CancelDisposition::ACCEPTED
    );
    let status = client
        .get_activation(
            GetActivationRequest {
                activation_id: identity.clone(),
            },
            CallOptions::default(),
        )
        .await
        .unwrap();
    assert_eq!(status.value.terminal_state, Some("cancelled".into()));
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
            .invoke(request("bounded", "hold"), options_until(deadline))
            .await
    });
    wait_until(|| peer.state.invocations.load(Ordering::Acquire) == 1).await;
    let failure = client
        .invoke(
            request("excess", "success"),
            options_until(Instant::now() + Duration::from_secs(1)),
        )
        .await
        .unwrap_err();
    assert_eq!(failure.category, FailureCategory::LIMIT);
    assert!(!failure.dispatched);
    assert!(client.usage().reserved_message_bytes > 0);
    let failure = expire_call(call, deadline).await.unwrap_err();
    assert_eq!(failure.category, FailureCategory::DEADLINE);
    assert!(failure.dispatched);
    assert_eq!(failure.outcome, OutcomeKnowledge::UNKNOWN);
    assert_eq!(failure.identity.activation_id.as_deref(), Some("bounded"));
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
    call.target.as_mut().unwrap().tenant = "foreign".into();
    let failure = denied
        .invoke(call, options_until(Instant::now() + Duration::from_secs(1)))
        .await
        .unwrap_err();
    assert_eq!(failure.category, FailureCategory::RPC);
    assert_eq!(failure.grpc_status, Some(7));
    let client = peer.client();
    let failure = client
        .invoke(
            request("wrong-id", "wrong-id"),
            options_until(Instant::now() + Duration::from_secs(1)),
        )
        .await
        .unwrap_err();
    assert_eq!(failure.category, FailureCategory::DECODE);
    assert_eq!(failure.outcome, OutcomeKnowledge::UNKNOWN);
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
    let request: ApplyPolicyRequest = network_support::policy("lost-operation").into();
    let active = client.clone();
    let submitted = request.clone();
    let deadline = Instant::now() + Duration::from_secs(30);
    let call = tokio::spawn(async move {
        active
            .apply_policy(submitted, options_until(deadline))
            .await
    });
    wait_until(|| peer.state.mutations.load(Ordering::Acquire) == 1).await;
    let failure = expire_call(call, deadline).await.unwrap_err();
    assert_eq!(failure.category, FailureCategory::DEADLINE);
    assert_eq!(failure.outcome, OutcomeKnowledge::UNKNOWN);
    assert_eq!(
        failure.identity.operation_id.as_deref(),
        Some("lost-operation")
    );
    let known = client
        .get_policy_operation(
            GetPolicyOperationRequest {
                operation_id: "lost-operation".into(),
            },
            options_until(Instant::now() + Duration::from_secs(1)),
        )
        .await
        .unwrap();
    assert_eq!(known.value.receipt.as_ref().unwrap().generation, 2);
    let replay = client
        .apply_policy(
            request,
            options_until(Instant::now() + Duration::from_secs(1)),
        )
        .await
        .unwrap();
    assert_eq!(replay.value.receipt, known.value.receipt);
    assert_eq!(
        replay.metadata.audit_ack.as_ref().unwrap().attempt_sequence,
        Some(u64::MAX)
    );
    assert_eq!(peer.state.mutations.load(Ordering::Acquire), 1);
    let unknown = client
        .get_policy_operation(
            GetPolicyOperationRequest {
                operation_id: "unknown".into(),
            },
            options_until(Instant::now() + Duration::from_secs(1)),
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
        .apply_policy(
            network_support::policy("create").into(),
            options_until(Instant::now() + Duration::from_secs(1)),
        )
        .await
        .unwrap();
    let list = client
        .list_policies(
            ListPoliciesRequest {
                record_kind: CapabilityPolicyRecordKind::POLICY,
                page: Some(PageRequest {
                    page_size: 1,
                    page_token: None,
                }),
            },
            options_until(Instant::now() + Duration::from_secs(1)),
        )
        .await
        .unwrap();
    assert_eq!(list.value.policies.len(), 1);
    let list = client
        .list_capabilities(
            ListCapabilitiesRequest {
                deployment_id: "deployment".into(),
                page: Some(PageRequest {
                    page_size: 1,
                    page_token: None,
                }),
                ..Default::default()
            },
            options_until(Instant::now() + Duration::from_secs(1)),
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
        .list_policies(
            ListPoliciesRequest {
                record_kind: CapabilityPolicyRecordKind::POLICY,
                page: Some(PageRequest {
                    page_size: 0,
                    page_token: None
                })
            },
            options_until(Instant::now() + Duration::from_secs(1))
        )
        .await
        .is_err());
    let mut config = peer.config();
    config.limits.maximum_response_bytes = 128;
    let small = latent_sdk::network::RpcClient::new(config).unwrap();
    let failure = small
        .invoke(
            request("large", "oversize"),
            options_until(Instant::now() + Duration::from_secs(1)),
        )
        .await
        .unwrap_err();
    assert!(failure.dispatched);
    assert_eq!(failure.outcome, OutcomeKnowledge::UNKNOWN);
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

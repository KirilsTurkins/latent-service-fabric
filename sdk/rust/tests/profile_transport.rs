#![cfg(feature = "transport")]

mod network_support;

#[path = "../src/network/profile/test_peer.rs"]
mod test_peer;

use latent_sdk::{management::*, network::RpcClient};
use network_support::{wait_until, Peer};
use std::{sync::atomic::Ordering, time::Duration};
use test_peer::ScriptedPeer;
use tokio::time::Instant;

fn options() -> CallOptions {
    CallOptions {
        timeout_millis: Some(1000),
    }
}

fn invoke(identity: Option<&str>, payload: &[u8]) -> InvokeRequest {
    InvokeRequest {
        activation_id: identity.map(Into::into),
        target: Some(InvocationTarget {
            tenant: "tests".into(),
            service: "example".into(),
            contract: "example:api@1.0.0".into(),
            function: "run".into(),
            route: None,
        }),
        priority: u32::MAX,
        payload: payload.into(),
        media_type: "application/octet-stream".into(),
        budget: None,
        ..Default::default()
    }
}

fn policy(operation: &str) -> ApplyPolicyRequest {
    network_support::policy(operation).into()
}

async fn shutdown(client: &RpcClient) {
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
}

#[tokio::test]
#[allow(clippy::too_many_lines)]
async fn all_eight_facade_operations_share_one_channel_and_owned_responses() {
    let peer = Peer::start().await;
    let client = peer.client();
    let profile: &dyn ClientProfile = &client;
    assert_eq!(client.usage().sockets, 0);
    let invoked = profile
        .invoke(invoke(Some("profile"), b"success"), options())
        .await
        .unwrap();
    assert_eq!(
        invoked.metadata.identity.activation_id.as_deref(),
        Some("profile")
    );
    assert_eq!(invoked.value.route_generation, u64::MAX);
    assert!(invoked.metadata.audit_ack.is_none());
    assert!(invoked.metadata.audit_status.is_none());
    assert!(invoked.metadata.audit_attempt_sequence.is_none());
    let status = profile
        .get_activation(
            GetActivationRequest {
                activation_id: "profile".into(),
            },
            options(),
        )
        .await
        .unwrap();
    assert_eq!(status.value.phase, "running");
    assert!(status.value.terminal_state.is_none());
    let cancelled = profile
        .cancel(
            CancelRequest {
                activation_id: "profile".into(),
                reason: "explicit".into(),
            },
            options(),
        )
        .await
        .unwrap();
    assert_eq!(cancelled.value.disposition, CancelDisposition::ACCEPTED);
    let applied = profile
        .apply_policy(policy("profile-operation"), options())
        .await
        .unwrap();
    assert_eq!(
        applied.metadata.audit_ack.unwrap().attempt_sequence,
        Some(u64::MAX)
    );
    let read = profile
        .get_policy(
            GetPolicyRequest {
                id: "policy".into(),
                record_kind: CapabilityPolicyRecordKind::POLICY,
            },
            options(),
        )
        .await
        .unwrap();
    assert!(read.value.policy.is_some());
    assert!(read.metadata.audit_ack.is_none());
    let page = profile
        .list_policies(
            ListPoliciesRequest {
                record_kind: CapabilityPolicyRecordKind::POLICY,
                page: Some(PageRequest {
                    page_size: 1,
                    page_token: None,
                }),
            },
            options(),
        )
        .await
        .unwrap();
    assert_eq!(page.value.policies.len(), 1);
    let capabilities = profile
        .list_capabilities(
            ListCapabilitiesRequest {
                deployment_id: "selected".into(),
                ..Default::default()
            },
            options(),
        )
        .await
        .unwrap();
    assert_eq!(
        capabilities.value.capabilities[0]
            .inspection
            .as_ref()
            .unwrap()
            .provider_configuration_epoch,
        u64::MAX
    );
    let recovered = profile
        .get_policy_operation(
            GetPolicyOperationRequest {
                operation_id: "profile-operation".into(),
            },
            options(),
        )
        .await
        .unwrap();
    assert_eq!(recovered.value.receipt, applied.value.receipt);
    let legacy =
        latent_sdk::LatentClient::invoke(&client, network_support::request("legacy", "success"))
            .await
            .unwrap();
    assert!(matches!(
        legacy,
        latent_sdk::InvocationOutcome::Succeeded(_)
    ));
    assert_eq!(peer.state.accepted.load(Ordering::Acquire), 1);
    shutdown(&client).await;
    assert_eq!(invoked.value.success.unwrap().payload, b"success");
    peer.stop().await;
}

#[tokio::test]
async fn optional_capability_pages_and_policy_page_bounds_are_distinct() {
    let peer = Peer::start().await;
    let client = peer.client();
    for page in [
        None,
        Some(PageRequest::default()),
        Some(PageRequest {
            page_size: 128,
            page_token: None,
        }),
    ] {
        client
            .list_capabilities(
                ListCapabilitiesRequest {
                    deployment_id: "selected".into(),
                    page,
                    ..Default::default()
                },
                options(),
            )
            .await
            .unwrap();
    }
    for page in [
        None,
        Some(PageRequest::default()),
        Some(PageRequest {
            page_size: 33,
            page_token: None,
        }),
        Some(PageRequest {
            page_size: 1,
            page_token: Some(String::new()),
        }),
        Some(PageRequest {
            page_size: 1,
            page_token: Some("x".repeat(118)),
        }),
    ] {
        let failure = client
            .list_policies(
                ListPoliciesRequest {
                    page,
                    ..Default::default()
                },
                options(),
            )
            .await
            .unwrap_err();
        assert_eq!(failure.category, FailureCategory::INVALID_REQUEST);
        assert!(!failure.dispatched);
    }
    let failure = client
        .list_capabilities(
            ListCapabilitiesRequest {
                deployment_id: "selected".into(),
                provider: Some(String::new()),
                ..Default::default()
            },
            options(),
        )
        .await
        .unwrap_err();
    assert_eq!(failure.category, FailureCategory::INVALID_REQUEST);
    shutdown(&client).await;
    peer.stop().await;
}

#[tokio::test]
async fn one_deadline_starts_at_facade_call_and_preserves_pre_dispatch_identity() {
    let peer = Peer::start().await;
    let client = peer.client();
    let future = client.apply_policy(
        policy("never-sent"),
        CallOptions {
            timeout_millis: Some(1),
        },
    );
    tokio::time::sleep(Duration::from_millis(10)).await;
    let failure = future.await.unwrap_err();
    assert_eq!(failure.category, FailureCategory::DEADLINE);
    assert_eq!(failure.outcome, OutcomeKnowledge::NOT_DISPATCHED);
    assert_eq!(failure.identity.operation_id.as_deref(), Some("never-sent"));
    for timeout in [0, u64::MAX] {
        let failure = client
            .apply_policy(
                policy("bounded-clock"),
                CallOptions {
                    timeout_millis: Some(timeout),
                },
            )
            .await
            .unwrap_err();
        assert!(!failure.dispatched);
        assert_eq!(
            failure.category,
            if timeout == 0 {
                FailureCategory::DEADLINE
            } else {
                FailureCategory::INVALID_REQUEST
            }
        );
    }
    assert_eq!(peer.state.accepted.load(Ordering::Acquire), 0);
    let mut absent = policy("missing-precondition");
    absent.expected_generation = None;
    let failure = client.apply_policy(absent, options()).await.unwrap_err();
    assert_eq!(
        failure.identity.operation_id.as_deref(),
        Some("missing-precondition")
    );
    assert_eq!(failure.category, FailureCategory::INVALID_REQUEST);
    shutdown(&client).await;
    peer.stop().await;
}

#[tokio::test]
async fn dropped_profile_wait_releases_local_owner_without_server_cancel() {
    let peer = Peer::start().await;
    let mut config = peer.config();
    config.limits.maximum_calls = 1;
    let client = RpcClient::new(config).unwrap();
    let active = client.clone();
    let call = tokio::spawn(async move {
        active
            .invoke(
                invoke(Some("held-profile"), b"hold"),
                CallOptions {
                    timeout_millis: Some(2000),
                },
            )
            .await
    });
    wait_until(|| peer.state.invocations.load(Ordering::Acquire) == 1).await;
    let failure = client
        .invoke(invoke(Some("excess-profile"), b"success"), options())
        .await
        .unwrap_err();
    assert_eq!(failure.category, FailureCategory::LIMIT);
    assert!(!failure.dispatched);
    assert_eq!(
        failure.identity.activation_id.as_deref(),
        Some("excess-profile")
    );
    call.abort();
    assert!(call.await.unwrap_err().is_cancelled());
    wait_until(|| client.usage().active_calls == 0).await;
    assert_eq!(peer.state.cancellations.load(Ordering::Acquire), 0);
    let status = client
        .get_activation(
            GetActivationRequest {
                activation_id: "held-profile".into(),
            },
            options(),
        )
        .await
        .unwrap();
    assert!(status.value.terminal_state.is_none());
    client
        .cancel(
            CancelRequest {
                activation_id: "held-profile".into(),
                reason: "explicit".into(),
            },
            options(),
        )
        .await
        .unwrap();
    assert_eq!(peer.state.accepted.load(Ordering::Acquire), 1);
    shutdown(&client).await;
    peer.stop().await;
}

#[tokio::test]
async fn uncertain_mutation_recovers_original_receipt_without_automatic_replay() {
    let peer = Peer::start().await;
    let client = peer.client();
    client
        .list_capabilities(
            ListCapabilitiesRequest {
                deployment_id: "selected".into(),
                ..Default::default()
            },
            options(),
        )
        .await
        .unwrap();
    let request = policy("lost-operation");
    let failure = client
        .apply_policy(
            request.clone(),
            CallOptions {
                timeout_millis: Some(100),
            },
        )
        .await
        .unwrap_err();
    assert_eq!(failure.category, FailureCategory::DEADLINE);
    assert_eq!(failure.outcome, OutcomeKnowledge::UNKNOWN);
    assert!(failure.dispatched);
    assert_eq!(
        failure.identity.operation_id.as_deref(),
        Some("lost-operation")
    );
    let recovered = client
        .get_policy_operation(
            GetPolicyOperationRequest {
                operation_id: "lost-operation".into(),
            },
            options(),
        )
        .await
        .unwrap();
    assert_eq!(recovered.metadata.outcome, OutcomeKnowledge::OBSERVED);
    assert!(recovered.metadata.audit_ack.is_none());
    let replay = client.apply_policy(request, options()).await.unwrap();
    assert_eq!(replay.value.receipt, recovered.value.receipt);
    assert_eq!(peer.state.mutations.load(Ordering::Acquire), 1);
    let missing = client
        .get_policy_operation(
            GetPolicyOperationRequest {
                operation_id: "not-retained".into(),
            },
            options(),
        )
        .await
        .unwrap();
    assert_eq!(missing.metadata.outcome, OutcomeKnowledge::UNKNOWN);
    assert!(missing.value.receipt.is_none());
    shutdown(&client).await;
    peer.stop().await;
}

#[tokio::test]
async fn protobuf_receipts_unknown_enums_and_assigned_identity_remain_lossless() {
    let peer = ScriptedPeer::start().await;
    let client = peer.client();
    let response = client
        .invoke(invoke(None, b"owned"), options())
        .await
        .unwrap();
    assert_eq!(
        response.metadata.identity.activation_id.as_deref(),
        Some("assigned-profile")
    );
    assert_eq!(response.value.consumption.unwrap().cpu_fuel, u64::MAX);
    assert!(response.value.publication_id.is_some());
    assert_eq!(
        response
            .value
            .success
            .unwrap()
            .committed_state_version
            .as_deref(),
        Some("")
    );
    let cancelled = client
        .cancel(
            CancelRequest {
                activation_id: "assigned-profile".into(),
                ..Default::default()
            },
            options(),
        )
        .await
        .unwrap();
    assert_eq!(cancelled.value.disposition.0, i32::MIN);
    assert_eq!(
        cancelled.value.terminal_state.as_deref(),
        Some("future-state")
    );
    let status = client
        .get_activation(
            GetActivationRequest {
                activation_id: "assigned-profile".into(),
            },
            options(),
        )
        .await
        .unwrap();
    assert_eq!(status.value.terminal_at_unix_millis, Some(0));
    assert_eq!(status.value.last_updated_unix_millis, u64::MAX);
    let mut request = policy("future-kind");
    request.expected_generation = Some(u64::MAX);
    request.policy.as_mut().unwrap().record_kind = CapabilityPolicyRecordKind(i32::MIN);
    let applied = client.apply_policy(request, options()).await.unwrap();
    assert_eq!(applied.value.receipt.unwrap().record_kind.0, i32::MIN);
    assert_eq!(applied.value.policy.unwrap().generation, u64::MAX);
    assert!(applied.metadata.audit_ack.is_none());
    shutdown(&client).await;
    peer.stop().await;
}

#[tokio::test]
async fn unsupported_wire_text_fails_explicitly_without_losing_recovery_identity() {
    let peer = ScriptedPeer::start().await;
    let client = peer.client();
    let failure = client
        .invoke(invoke(None, b"unknown-platform"), options())
        .await
        .unwrap_err();
    assert_eq!(failure.category, FailureCategory::DECODE);
    assert_eq!(
        failure.identity.activation_id.as_deref(),
        Some("assigned-profile")
    );
    assert_eq!(
        failure.unsupported_wire_value.unwrap().value,
        "future-platform-code"
    );
    assert_eq!(failure.outcome, OutcomeKnowledge::UNKNOWN);
    let failure = client
        .get_activation(
            GetActivationRequest {
                activation_id: "unknown-phase".into(),
            },
            options(),
        )
        .await
        .unwrap_err();
    assert_eq!(
        failure.unsupported_wire_value.unwrap().value,
        "future-phase"
    );
    assert_eq!(
        failure.identity.activation_id.as_deref(),
        Some("unknown-phase")
    );
    shutdown(&client).await;
    peer.stop().await;
}

#[tokio::test]
async fn typed_rpc_errors_cursor_rejection_and_not_found_remain_separate() {
    let peer = ScriptedPeer::start().await;
    let client = peer.client();
    let failure = client
        .get_policy(
            GetPolicyRequest {
                id: "denied".into(),
                record_kind: CapabilityPolicyRecordKind::POLICY,
            },
            options(),
        )
        .await
        .unwrap_err();
    assert_eq!(failure.category, FailureCategory::RPC);
    assert_eq!(failure.grpc_status, Some(7));
    assert!(!failure.message.contains("must not become"));
    assert_eq!(
        failure.platform_error.unwrap().detail_items[0].fields["outcome"],
        "unknown"
    );
    let failure = client
        .list_policies(
            ListPoliciesRequest {
                page: Some(PageRequest {
                    page_size: 1,
                    page_token: None,
                }),
                ..Default::default()
            },
            options(),
        )
        .await
        .unwrap_err();
    assert_eq!(failure.category, FailureCategory::DECODE);
    let failure = client
        .get_policy_operation(
            GetPolicyOperationRequest {
                operation_id: "not-retained".into(),
            },
            options(),
        )
        .await
        .unwrap_err();
    assert_eq!(failure.grpc_status, Some(5));
    assert_eq!(failure.outcome, OutcomeKnowledge::UNKNOWN);
    assert_eq!(
        failure.identity.operation_id.as_deref(),
        Some("not-retained")
    );
    shutdown(&client).await;
    peer.stop().await;
}

#[tokio::test]
async fn audit_uncertainty_and_header_decode_failure_do_not_erase_validated_receipts() {
    let peer = ScriptedPeer::start().await;
    let client = peer.client();
    let response = client
        .apply_policy(policy("uncertain-audit"), options())
        .await
        .unwrap();
    assert_eq!(response.metadata.outcome, OutcomeKnowledge::OBSERVED);
    assert_eq!(
        response.metadata.audit_status.as_deref(),
        Some("outcome-unknown")
    );
    assert_eq!(
        response.metadata.audit_ack.unwrap().attempt_sequence,
        Some(u64::MAX)
    );
    let failure = client
        .apply_policy(policy("bad-audit"), options())
        .await
        .unwrap_err();
    assert_eq!(failure.category, FailureCategory::DECODE);
    assert_eq!(failure.outcome, OutcomeKnowledge::OBSERVED);
    assert_eq!(failure.identity.operation_id.as_deref(), Some("bad-audit"));
    shutdown(&client).await;
    peer.stop().await;
}

#[tokio::test]
async fn future_audit_status_and_attempt_remain_raw_without_invented_durability() {
    let peer = ScriptedPeer::start().await;
    let client = peer.client();
    let response = client
        .apply_policy(policy("future-audit"), options())
        .await
        .unwrap();
    assert_eq!(
        response.metadata.audit_status.as_deref(),
        Some("future-durable-v2")
    );
    assert!(response.metadata.audit_ack.is_none());
    assert_eq!(response.metadata.audit_attempt_sequence, Some(u64::MAX));
    assert_eq!(response.metadata.outcome, OutcomeKnowledge::OBSERVED);
    assert_eq!(response.value.receipt.unwrap().generation, u64::MAX);
    shutdown(&client).await;
    peer.stop().await;
}

#[tokio::test]
async fn future_audit_status_on_rpc_failure_retains_independent_attempt() {
    let peer = ScriptedPeer::start().await;
    let client = peer.client();
    let failure = client
        .get_policy(
            GetPolicyRequest {
                id: "future-audit-error".into(),
                record_kind: CapabilityPolicyRecordKind::POLICY,
            },
            options(),
        )
        .await
        .unwrap_err();
    assert_eq!(failure.category, FailureCategory::RPC);
    assert_eq!(failure.grpc_status, Some(7));
    assert!(failure.audit_ack.is_none());
    assert_eq!(failure.audit_status.as_deref(), Some("future-state"));
    assert_eq!(failure.audit_attempt_sequence, Some(u64::MAX));
    assert!(failure.platform_error.is_some());
    shutdown(&client).await;
    peer.stop().await;
}

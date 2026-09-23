use super::{options_until, request, wait_until, Peer};
use latent_sdk::management::*;
use latent_sdk::network::RpcClient;
use std::{sync::atomic::Ordering, time::Duration};
use tokio::time::Instant;

#[tokio::test]
async fn closing_a_clone_interrupts_waiters_reaps_transport_and_denies_new_work() {
    let peer = Peer::start().await;
    let client = peer.client();
    let mut calls = vec![];
    for index in 0..4 {
        let active = client.clone();
        calls.push(tokio::spawn(async move {
            active
                .invoke(
                    request(&format!("pending-{index}"), "hold"),
                    options_until(Instant::now() + Duration::from_secs(10)),
                )
                .await
        }));
    }
    wait_until(|| peer.state.invocations.load(Ordering::Acquire) == 4).await;
    assert_eq!(peer.state.accepted.load(Ordering::Acquire), 1);
    client
        .clone()
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap();
    for call in calls {
        let error = call.await.unwrap().unwrap_err();
        assert_eq!(error.category, FailureCategory::LOCAL_CANCELLED);
        assert!(error.dispatched);
        assert_eq!(error.outcome, OutcomeKnowledge::UNKNOWN);
    }
    let usage = client.usage();
    assert!(usage.closed);
    assert_eq!(
        (
            usage.active_calls,
            usage.executor_tasks,
            usage.sockets,
            usage.reserved_message_bytes
        ),
        (0, 0, 0, 0)
    );
    assert_eq!(peer.state.cancellations.load(Ordering::Acquire), 0);
    let error = client
        .invoke(
            request("after-close", "success"),
            options_until(Instant::now() + Duration::from_secs(1)),
        )
        .await
        .unwrap_err();
    assert_eq!(error.category, FailureCategory::LOCAL_CANCELLED);
    assert!(!error.dispatched);
    wait_until(|| peer.state.open.load(Ordering::Acquire) == 0).await;
    peer.stop().await;
}

#[tokio::test]
async fn local_limits_and_expired_absolute_deadline_never_open_a_socket() {
    let peer = Peer::start().await;
    let mut config = peer.config();
    config.limits.maximum_reserved_bytes = 1;
    let limited = RpcClient::new(config).unwrap();
    let error = limited
        .invoke(
            request("byte-cap", "success"),
            options_until(Instant::now() + Duration::from_secs(1)),
        )
        .await
        .unwrap_err();
    assert_eq!(error.category, FailureCategory::LIMIT);
    assert_eq!(error.identity.activation_id.as_deref(), Some("byte-cap"));
    assert!(!error.dispatched);
    assert_eq!(limited.usage().active_calls, 0);
    let client = peer.client();
    let error = client
        .invoke(request("expired", "success"), options_until(Instant::now()))
        .await
        .unwrap_err();
    assert_eq!(error.category, FailureCategory::DEADLINE);
    assert!(!error.dispatched);
    let mut oversized = request("input-cap", "success");
    oversized.payload = vec![0; client.limits().maximum_request_bytes + 1];
    let error = client
        .invoke(
            oversized,
            options_until(Instant::now() + Duration::from_secs(1)),
        )
        .await
        .unwrap_err();
    assert_eq!(error.category, FailureCategory::LIMIT);
    assert_eq!(error.identity.activation_id.as_deref(), Some("input-cap"));
    assert!(!error.dispatched);
    assert_eq!(peer.state.accepted.load(Ordering::Acquire), 0);
    limited
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
    client
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
    peer.stop().await;
}

#[tokio::test]
async fn optional_identity_presence_and_zero_wall_deadline_are_not_normalized() {
    let peer = Peer::start().await;
    let client = peer.client();
    let mut absent = request("unused", "success");
    absent.activation_id = None;
    let response = client.invoke(absent, CallOptions::default()).await.unwrap();
    assert_eq!(response.value.activation_id, "assigned");
    assert!(response.value.success.is_some());
    let error = client
        .invoke(
            request("", "success"),
            options_until(Instant::now() + Duration::from_secs(1)),
        )
        .await
        .unwrap_err();
    assert_eq!(error.category, FailureCategory::INVALID_REQUEST);
    assert_eq!(error.grpc_status, None);
    assert!(!error.dispatched);
    assert_eq!(error.identity.activation_id.as_deref(), Some(""));
    let mut expired = request("wall-expired", "success");
    expired.deadline_unix_millis = Some(0);
    let error = client
        .invoke(
            expired,
            options_until(Instant::now() + Duration::from_secs(1)),
        )
        .await
        .unwrap_err();
    assert_eq!(error.category, FailureCategory::DEADLINE);
    assert!(!error.dispatched);
    assert_eq!(peer.state.invocations.load(Ordering::Acquire), 1);
    client
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap();
    peer.stop().await;
}

#[tokio::test]
async fn refused_initial_connection_is_not_implicitly_retried() {
    let peer = Peer::start().await;
    let config = peer.config();
    let address = peer.address;
    peer.stop().await;
    let client = RpcClient::new(config).unwrap();
    let error = client
        .invoke(
            request("refused", "success"),
            options_until(Instant::now() + Duration::from_secs(1)),
        )
        .await
        .unwrap_err();
    assert_eq!(error.category, FailureCategory::TRANSPORT);
    assert!(!error.dispatched);
    let listener = tokio::net::TcpListener::bind(address).await.unwrap();
    let error = client
        .invoke(
            request("not-retried", "success"),
            options_until(Instant::now() + Duration::from_secs(1)),
        )
        .await
        .unwrap_err();
    assert_eq!(error.category, FailureCategory::TRANSPORT);
    assert!(!error.dispatched);
    assert!(
        tokio::time::timeout(Duration::from_millis(50), listener.accept())
            .await
            .is_err()
    );
    client
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap();
    assert_eq!(client.usage().sockets, 0);
}

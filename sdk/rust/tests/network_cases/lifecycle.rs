use super::{request, wait_until, FailureKind, LatentClient, Peer};
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
                .invoke_until(
                    request(&format!("pending-{index}"), "hold"),
                    Instant::now() + Duration::from_secs(10),
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
        assert_eq!(error.kind, FailureKind::Closed);
        assert!(error.dispatched);
        assert!(!error.outcome_known);
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
        .invoke_until(
            request("after-close", "success"),
            Instant::now() + Duration::from_secs(1),
        )
        .await
        .unwrap_err();
    assert_eq!(error.kind, FailureKind::Closed);
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
        .invoke_until(
            request("byte-cap", "success"),
            Instant::now() + Duration::from_secs(1),
        )
        .await
        .unwrap_err();
    assert_eq!(error.kind, FailureKind::Capacity);
    assert_eq!(error.recovery.activation_id.as_deref(), Some("byte-cap"));
    assert!(!error.dispatched);
    assert_eq!(limited.usage().active_calls, 0);
    let client = peer.client();
    let error = client
        .invoke_until(request("expired", "success"), Instant::now())
        .await
        .unwrap_err();
    assert_eq!(error.kind, FailureKind::Deadline);
    assert!(!error.dispatched);
    let mut oversized = request("input-cap", "success");
    oversized.payload = vec![0; client.limits().maximum_request_bytes + 1];
    let error = client
        .invoke_until(oversized, Instant::now() + Duration::from_secs(1))
        .await
        .unwrap_err();
    assert_eq!(error.kind, FailureKind::InvalidRequest);
    assert_eq!(error.recovery.activation_id.as_deref(), Some("input-cap"));
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
    let response = client.invoke(absent).await.unwrap();
    assert!(
        matches!(response, latent_sdk::InvocationOutcome::Succeeded(value) if value.activation_id.0 == "assigned")
    );
    let error = client
        .invoke_until(
            request("", "success"),
            Instant::now() + Duration::from_secs(1),
        )
        .await
        .unwrap_err();
    assert_eq!(error.kind, FailureKind::Rejected);
    assert_eq!(error.grpc_code, Some(3));
    assert_eq!(error.recovery.activation_id.as_deref(), Some(""));
    let mut expired = request("wall-expired", "success");
    expired.options.deadline_unix_millis = Some(0);
    let error = client
        .invoke_until(expired, Instant::now() + Duration::from_secs(1))
        .await
        .unwrap_err();
    assert_eq!(error.kind, FailureKind::Deadline);
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
        .invoke_until(
            request("refused", "success"),
            Instant::now() + Duration::from_secs(1),
        )
        .await
        .unwrap_err();
    assert_eq!(error.kind, FailureKind::Connection);
    assert!(!error.dispatched);
    let listener = tokio::net::TcpListener::bind(address).await.unwrap();
    let error = client
        .invoke_until(
            request("not-retried", "success"),
            Instant::now() + Duration::from_secs(1),
        )
        .await
        .unwrap_err();
    assert_eq!(error.kind, FailureKind::Connection);
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

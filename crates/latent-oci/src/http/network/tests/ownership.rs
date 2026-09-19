use super::{
    peer::{wait_until, Peer},
    policy, pull, HttpOciRegistry, RegistryActions,
};
use latent_core::PlatformErrorCode;
use std::{sync::atomic::Ordering, time::Duration};
use tokio::time::Instant;

#[tokio::test]
async fn cancelling_owned_token_acquisition_retires_socket_before_follower_recovery() {
    let peer = Peer::new().await;
    peer.state.hold.store(true, Ordering::Release);
    let config = peer.config(RegistryActions::Pull);
    let origin = config.origin.clone();
    let client = HttpOciRegistry::new_with_network(config, policy(&peer)).unwrap();
    let active = client.clone();
    let first_origin = origin.clone();
    let leader = tokio::spawn(async move { pull(&active, &first_origin).await });
    peer.wait_tokens(1).await;
    let active = client.clone();
    let follower = tokio::spawn(async move { pull(&active, &origin).await });
    wait_until(|| client.usage().bearer.unwrap().waiting_acquisitions == 1).await;
    leader.abort();
    assert!(leader.await.unwrap_err().is_cancelled());
    wait_until(|| peer.state.disconnected.load(Ordering::Acquire) == 1).await;
    peer.wait_tokens(2).await;
    assert_eq!(client.usage().in_flight, 1);
    assert_eq!(client.usage().network.unwrap().connections, 1);
    peer.state.release.add_permits(1);
    assert_eq!(follower.await.unwrap().unwrap(), b"abc");
    assert_eq!(client.usage().network.unwrap().connections, 0);
    assert_eq!(client.usage().network.unwrap().reserved_connection_bytes, 0);
    assert_eq!(client.usage().bearer.unwrap().active_acquisitions, 0);
}

#[tokio::test]
async fn stalled_tls_cancellation_and_deadline_close_the_actual_socket() {
    use crate::RegistryCredentials;
    use tokio::{io::AsyncReadExt, net::TcpListener, sync::oneshot, time::timeout};

    for cancel in [true, false] {
        let peer = Peer::new().await;
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let (started, ready) = oneshot::channel();
        let server = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut buffer = [0; 4096];
            assert!(socket.read(&mut buffer).await.unwrap() > 0);
            started.send(()).unwrap();
            while let Ok(count) = socket.read(&mut buffer).await {
                if count == 0 {
                    break;
                }
            }
        });
        let mut config = peer.config(RegistryActions::Pull);
        config.origin = format!("https://{address}");
        config.limits.operation_timeout = Duration::from_millis(250);
        if let RegistryCredentials::BearerChallenge { realm, .. } = &mut config.credentials {
            *realm = format!("{}/token", config.origin);
        }
        let origin = config.origin.clone();
        let mut network = policy(&peer);
        network.destinations[0].origin.clone_from(&origin);
        let client = HttpOciRegistry::new_with_network(config, network).unwrap();
        let active = client.clone();
        let call = tokio::spawn(async move { pull(&active, &origin).await });
        timeout(Duration::from_secs(2), ready)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(client.usage().network.unwrap().connections, 1);
        if cancel {
            call.abort();
            assert!(call.await.unwrap_err().is_cancelled());
        } else {
            assert_eq!(
                call.await.unwrap().unwrap_err().code,
                PlatformErrorCode::DeadlineExceeded
            );
        }
        timeout(Duration::from_secs(2), server)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(client.usage().in_flight, 0);
        assert_eq!(client.usage().network.unwrap().reserved_connection_bytes, 0);
    }
}

#[tokio::test]
async fn body_deadline_closes_the_physical_connection_before_refund() {
    let peer = Peer::new().await;
    peer.state.hold_body.store(true, Ordering::Release);
    let mut config = peer.config(RegistryActions::Pull);
    config.limits.operation_timeout = Duration::from_millis(250);
    let origin = config.origin.clone();
    let client = HttpOciRegistry::new_with_network(config, policy(&peer)).unwrap();
    assert_eq!(
        pull(&client, &origin).await.unwrap_err().code,
        PlatformErrorCode::DeadlineExceeded
    );
    wait_until(|| peer.state.disconnected.load(Ordering::Acquire) == 1).await;
    let usage = client.usage();
    assert_eq!(usage.in_flight, 0);
    assert_eq!(usage.network.unwrap().connections, 0);
    assert_eq!(usage.network.unwrap().reserved_connection_bytes, 0);
}

#[tokio::test]
async fn shutdown_deadline_keeps_the_retained_connection_visible_until_body_retirement() {
    let peer = Peer::new().await;
    peer.state.hold_body.store(true, Ordering::Release);
    let config = peer.config(RegistryActions::Pull);
    let origin = config.origin.clone();
    let client = HttpOciRegistry::new_with_network(config, policy(&peer)).unwrap();
    let active = client.clone();
    let call = tokio::spawn(async move { pull(&active, &origin).await });
    wait_until(|| peer.state.reads.load(Ordering::Acquire) == 2).await;
    assert_eq!(
        client
            .shutdown(Instant::now() + Duration::from_millis(20))
            .await
            .unwrap_err()
            .code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert_eq!(client.usage().network.unwrap().connections, 1);
    assert_eq!(client.usage().in_flight, 1);
    peer.state.body_release.add_permits(1);
    assert_eq!(call.await.unwrap().unwrap(), b"abc");
    client
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
    assert_eq!(client.usage().network.unwrap().connections, 0);
}

#[tokio::test]
async fn response_metadata_is_bounded_and_failure_retires_its_socket() {
    let peer = Peer::new().await;
    *peer.state.response_headers.lock().unwrap() = format!("X-Oversize: {}\r\n", "x".repeat(17000));
    let config = peer.config(RegistryActions::Pull);
    let origin = config.origin.clone();
    let client = HttpOciRegistry::new_with_network(config, policy(&peer)).unwrap();
    assert_eq!(
        pull(&client, &origin).await.unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(client.usage().network.unwrap().connections, 0);
}

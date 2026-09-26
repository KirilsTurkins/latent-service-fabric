use super::{
    peer::{wait_until, Peer},
    policy, HttpOciRegistry, RegistryActions,
};
use bytes::Bytes;
use latent_core::PlatformErrorCode;
use reqwest::Method;
use std::{sync::atomic::Ordering, time::Duration};
use tokio::time::Instant;

#[tokio::test]
async fn cancellation_before_upload_location_keeps_socket_bytes_and_cleanup_owned() {
    let peer = Peer::new().await;
    peer.state.upload_mode.store(true, Ordering::Release);
    let mut config = peer.config(RegistryActions::PullPush);
    config.limits.max_in_flight = 1;
    let client = HttpOciRegistry::new_with_network(config, policy(&peer)).unwrap();
    let operation = client.transport.begin(17).unwrap();
    let worker = client.uploads.clone();
    let call = tokio::spawn(async move { worker.start(operation).await });
    wait_until(|| peer.state.writes.load(Ordering::Acquire) == 1).await;
    call.abort();
    assert!(call.await.is_err());
    assert_eq!(client.usage().retained_bytes, 17);
    assert_eq!(client.usage().network.unwrap().connections, 1);
    peer.state.write_release.add_permits(1);
    wait_until(|| peer.state.writes.load(Ordering::Acquire) == 2).await;
    assert!(client.transport.begin(1).is_err());
    assert_eq!(client.usage().retained_bytes, 17);
    assert_eq!(
        client
            .shutdown(Instant::now() + Duration::from_millis(20))
            .await
            .unwrap_err()
            .code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert_eq!(client.usage().network.unwrap().connections, 1);
    peer.state.delete_release.add_permits(1);
    client
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
    assert_eq!(client.usage().retained_bytes, 0);
    assert_eq!(client.usage().network.unwrap().connections, 0);
    assert_eq!(peer.state.writes.load(Ordering::Acquire), 2);
}

#[tokio::test]
async fn cancelled_upload_put_closes_its_socket_but_keeps_the_cleanup_reservation() {
    let peer = Peer::new().await;
    peer.state.upload_mode.store(true, Ordering::Release);
    peer.state.write_release.add_permits(1);
    let client =
        HttpOciRegistry::new_with_network(peer.config(RegistryActions::PullPush), policy(&peer))
            .unwrap();
    let session = client
        .uploads
        .start(client.transport.begin(17).unwrap())
        .await
        .unwrap();
    let transport = client.transport.clone();
    let call = tokio::spawn(async move {
        let result = transport
            .send(
                Method::PUT,
                session.location().clone(),
                Some(Bytes::from_static(b"abc")),
                None,
                session.deadline(),
            )
            .await;
        drop(session);
        result
    });
    wait_until(|| peer.state.writes.load(Ordering::Acquire) == 2).await;
    call.abort();
    assert!(call.await.is_err());
    wait_until(|| peer.state.writes.load(Ordering::Acquire) == 3).await;
    wait_until(|| peer.state.disconnected.load(Ordering::Acquire) == 1).await;
    assert_eq!(client.usage().retained_bytes, 17);
    assert_eq!(client.usage().network.unwrap().connections, 1);
    peer.state.delete_release.add_permits(1);
    client
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
    assert_eq!(client.usage().retained_bytes, 0);
    assert_eq!(client.usage().network.unwrap().connections, 0);
}

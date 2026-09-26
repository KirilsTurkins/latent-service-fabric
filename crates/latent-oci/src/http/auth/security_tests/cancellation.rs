use super::{
    peer::{wait_until, Peer},
    pull, HttpOciRegistry, RegistryActions,
};
use latent_core::PlatformErrorCode;
use std::{sync::atomic::Ordering, time::Duration};
use tokio::time::Instant;

#[tokio::test]
async fn cancelling_the_acquisition_leader_closes_its_socket_and_allows_follower_recovery() {
    let peer = Peer::new().await;
    peer.state.hold.store(true, Ordering::Release);
    let client = HttpOciRegistry::new(peer.config(RegistryActions::Pull)).unwrap();
    let address = peer.address;
    let first_client = client.clone();
    let leader = tokio::spawn(async move { pull(&first_client, address).await });
    peer.wait_tokens(1).await;
    let follower_client = client.clone();
    let follower = tokio::spawn(async move { pull(&follower_client, address).await });
    wait_until(|| client.usage().bearer.unwrap().waiting_acquisitions == 1).await;
    leader.abort();
    assert!(leader.await.unwrap_err().is_cancelled());
    wait_until(|| peer.state.disconnected.load(Ordering::Acquire) == 1).await;
    peer.wait_tokens(2).await;
    assert_eq!(client.usage().in_flight, 1);
    peer.state.release.add_permits(1);
    assert_eq!(follower.await.unwrap().unwrap(), b"abc");
    assert_eq!(client.usage().in_flight, 0);
    assert_eq!(client.usage().bearer.unwrap().active_acquisitions, 0);
}

#[tokio::test]
async fn shutdown_timeout_does_not_report_live_acquisition_as_reclaimed() {
    let peer = Peer::new().await;
    peer.state.hold.store(true, Ordering::Release);
    let client = HttpOciRegistry::new(peer.config(RegistryActions::Pull)).unwrap();
    let active_client = client.clone();
    let address = peer.address;
    let active = tokio::spawn(async move { pull(&active_client, address).await });
    peer.wait_tokens(1).await;
    let error = client
        .shutdown(Instant::now() + Duration::from_millis(20))
        .await
        .unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::DeadlineExceeded);
    assert_eq!(client.usage().in_flight, 1);
    assert_eq!(client.usage().bearer.unwrap().active_acquisitions, 1);
    assert_eq!(
        client.usage().bearer.unwrap().reserved_acquisition_bytes,
        65536
    );
    assert!(pull(&client, address).await.is_err());
    active.abort();
    assert!(active.await.unwrap_err().is_cancelled());
    wait_until(|| peer.state.disconnected.load(Ordering::Acquire) == 1).await;
    client
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap();
    assert_eq!(client.usage().in_flight, 0);
    assert_eq!(client.usage().bearer.unwrap().reserved_acquisition_bytes, 0);
}

#[tokio::test]
async fn original_transfer_deadline_covers_authentication_and_drops_pending_work() {
    let peer = Peer::new().await;
    peer.state.hold.store(true, Ordering::Release);
    let mut config = peer.config(RegistryActions::Pull);
    config.limits.operation_timeout = Duration::from_millis(600);
    let client = HttpOciRegistry::new(config).unwrap();
    let error = pull(&client, peer.address).await.unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::DeadlineExceeded);
    assert_eq!(peer.state.tokens.load(Ordering::Acquire), 1);
    wait_until(|| peer.state.disconnected.load(Ordering::Acquire) == 1).await;
    assert_eq!(client.usage().in_flight, 0);
    assert_eq!(client.usage().bearer.unwrap().active_acquisitions, 0);
    assert_eq!(client.usage().bearer.unwrap().waiting_acquisitions, 0);
    assert_eq!(client.usage().bearer.unwrap().retained_token_bytes, 0);
    assert_eq!(peer.state.reads.load(Ordering::Acquire), 1);
}

#[tokio::test]
async fn malicious_registry_challenges_never_receive_token_credentials() {
    let peer = Peer::new().await;
    *peer.state.challenge.lock().unwrap() = Some("Bearer realm=\"https://unapproved.invalid/token\",service=\"registry.test\",scope=\"repository:tenant/package:pull\"".into());
    let client = HttpOciRegistry::new(peer.config(RegistryActions::Pull)).unwrap();
    assert_eq!(
        pull(&client, peer.address).await.unwrap_err().code,
        PlatformErrorCode::Unauthenticated
    );
    assert_eq!(peer.state.tokens.load(Ordering::Acquire), 0);
    assert_eq!(client.usage().in_flight, 0);
}

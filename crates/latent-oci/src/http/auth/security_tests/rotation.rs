use super::{
    peer::{identity, wait_until, Peer},
    pull, HttpOciRegistry, RegistryActions, Transport,
};
use crate::http::auth::ConfiguredBearer;
use latent_core::PlatformErrorCode;
use reqwest::Method;
use std::{
    sync::{atomic::Ordering, Arc},
    time::Duration,
};
use tokio::time::Instant;

#[tokio::test]
async fn rotation_invalidates_later_use_but_does_not_refund_pinned_responses() {
    let peer = Peer::new().await;
    let transport = Transport::new(peer.config(RegistryActions::Pull)).unwrap();
    let operation = transport.begin(32).unwrap();
    let url = transport.endpoint.url("blobs/test").unwrap();
    let first = transport
        .send(Method::GET, url.clone(), None, None, operation.deadline)
        .await
        .unwrap();
    let first_bytes = transport.usage().bearer.unwrap().retained_token_bytes;
    transport
        .rotate_bearer_credentials(identity(2), "public-test-user", "rotated-password")
        .unwrap();
    assert_eq!(transport.usage().bearer.unwrap().cached_tokens, 0);
    assert_eq!(
        transport.usage().bearer.unwrap().retained_token_bytes,
        first_bytes
    );
    let second = transport
        .send(Method::GET, url, None, None, operation.deadline)
        .await
        .unwrap();
    assert!(transport.usage().bearer.unwrap().retained_token_bytes > first_bytes);
    drop(first);
    assert_eq!(
        transport.usage().bearer.unwrap().retained_token_bytes,
        first_bytes
    );
    drop(second);
    drop(operation);
    transport
        .close_and_wait(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
    assert_eq!(transport.usage().bearer.unwrap().retained_token_bytes, 0);
}

#[tokio::test]
async fn rotation_during_acquisition_rejects_stale_install_and_unblocks_current_epoch() {
    let peer = Peer::new().await;
    peer.state.hold.store(true, Ordering::Release);
    let client = HttpOciRegistry::new(peer.config(RegistryActions::Pull)).unwrap();
    let address = peer.address;
    let first_client = client.clone();
    let first = tokio::spawn(async move { pull(&first_client, address).await });
    peer.wait_tokens(1).await;
    client
        .rotate_bearer_credentials(identity(2), "public-test-user", "rotated-password")
        .unwrap();
    let second_client = client.clone();
    let second = tokio::spawn(async move { pull(&second_client, address).await });
    wait_until(|| client.usage().bearer.unwrap().waiting_acquisitions == 1).await;
    peer.state.release.add_permits(1);
    assert_eq!(
        first.await.unwrap().unwrap_err().code,
        PlatformErrorCode::Unauthenticated
    );
    peer.wait_tokens(2).await;
    peer.state.release.add_permits(1);
    assert_eq!(second.await.unwrap().unwrap(), b"abc");
    assert_eq!(client.usage().bearer.unwrap().credential_epoch, 2);
    assert_eq!(client.usage().bearer.unwrap().cached_tokens, 1);
}

#[tokio::test]
async fn rotation_cannot_change_principal_tenant_or_roll_back_an_epoch() {
    let peer = Peer::new().await;
    let bearer = Arc::new(
        ConfiguredBearer::new(&peer.config(RegistryActions::Pull))
            .unwrap()
            .unwrap(),
    );
    let mut other_tenant = identity(2);
    other_tenant.tenant.0 = "other".into();
    let mut other_principal = identity(2);
    other_principal.principal = "other".into();
    for value in [identity(0), identity(1), other_tenant, other_principal] {
        assert!(bearer
            .rotate(value, "public-test-user", "password")
            .is_err());
    }
    bearer
        .rotate(identity(u64::MAX), "public-test-user", "password")
        .unwrap();
    assert!(bearer
        .rotate(identity(u64::MAX), "public-test-user", "password")
        .is_err());
    bearer.close().unwrap();
    assert!(bearer
        .rotate(identity(2), "public-test-user", "password")
        .is_err());
}

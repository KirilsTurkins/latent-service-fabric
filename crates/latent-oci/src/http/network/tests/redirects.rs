use super::{destination, peer::Peer, policy, pull, HttpOciRegistry, RegistryActions};
use crate::http::Transport;
use bytes::Bytes;
use latent_core::PlatformErrorCode;
use reqwest::Method;
use std::sync::atomic::Ordering;

#[tokio::test]
async fn approved_content_redirects_strip_credentials_and_retain_digest_validation() {
    let registry = Peer::new().await;
    let storage = Peer::new().await;
    storage.state.storage.store(true, Ordering::Release);
    *registry.state.redirect.lock().unwrap() = Some(format!(
        "https://{}/objects/blob?opaque=secret",
        storage.address
    ));
    let mut network = policy(&registry);
    network.destinations.push(destination(&storage, true));
    let mut config = registry.config(RegistryActions::Pull);
    config.additional_root_certificates.extend(
        storage
            .config(RegistryActions::Pull)
            .additional_root_certificates,
    );
    let origin = config.origin.clone();
    let client = HttpOciRegistry::new_with_network(config, network).unwrap();
    assert_eq!(pull(&client, &origin).await.unwrap(), b"abc");
    assert_eq!(storage.state.reads.load(Ordering::Acquire), 1);
    assert_eq!(storage.state.tokens.load(Ordering::Acquire), 0);
    assert_eq!(client.usage().network.unwrap().connections, 0);
    *storage.state.response_body.lock().unwrap() = b"abd".to_vec();
    assert_eq!(
        pull(&client, &origin).await.unwrap_err().code,
        PlatformErrorCode::CorruptArtifact
    );
    *storage.state.response_body.lock().unwrap() = b"abc".to_vec();
    *storage.state.redirect.lock().unwrap() = Some(format!(
        "https://{}/objects/blob?opaque=secret",
        storage.address
    ));
    let error = pull(&client, &origin).await.unwrap_err();
    assert!(!format!("{error:?}").contains("opaque"));
    assert_eq!(storage.state.reads.load(Ordering::Acquire), 3);
}

#[tokio::test]
async fn foreign_origins_paths_userinfo_downgrades_and_token_targets_are_denied() {
    let registry = Peer::new().await;
    let storage = Peer::new().await;
    storage.state.storage.store(true, Ordering::Release);
    let mut network = policy(&registry);
    network.destinations.push(destination(&storage, true));
    let config = registry.config(RegistryActions::Pull);
    let origin = config.origin.clone();
    let client = HttpOciRegistry::new_with_network(config, network).unwrap();
    for target in [
        "https://unapproved.invalid/objects/blob".to_owned(),
        format!("http://{}/objects/blob", storage.address),
        format!("https://{}@{}/objects/blob", "credential", storage.address),
        format!("https://@{}/objects/blob", storage.address),
        format!("https://{}/foreign/blob", storage.address),
        format!("https://{}/objects/%2e%2e/objects/blob", storage.address),
        format!("https://{}/v2/other/blobs/blob", storage.address),
        format!("https://{}/token", registry.address),
    ] {
        *registry.state.redirect.lock().unwrap() = Some(target);
        assert!(pull(&client, &origin).await.is_err());
    }
    assert_eq!(storage.state.reads.load(Ordering::Acquire), 0);
    assert_eq!(client.usage().network.unwrap().connections, 0);
}

#[tokio::test]
async fn token_redirects_and_mutation_redirects_never_replay_or_forward_credentials() {
    let peer = Peer::new().await;
    let storage = Peer::new().await;
    storage.state.storage.store(true, Ordering::Release);
    peer.state.token_status.store(302, Ordering::Release);
    *peer.state.token_redirect.lock().unwrap() =
        Some(format!("https://{}/objects/token", storage.address));
    let mut network = policy(&peer);
    network.destinations.push(destination(&storage, true));
    let config = peer.config(RegistryActions::PullPush);
    let origin = config.origin.clone();
    let client = HttpOciRegistry::new_with_network(config, network).unwrap();
    assert_eq!(
        pull(&client, &origin).await.unwrap_err().code,
        PlatformErrorCode::InvalidArgument
    );
    assert_eq!(storage.state.reads.load(Ordering::Acquire), 0);
    peer.state.token_status.store(200, Ordering::Release);
    *peer.state.token_redirect.lock().unwrap() = None;
    peer.state.write_status.store(307, Ordering::Release);
    let transport =
        Transport::new_with_network(peer.config(RegistryActions::PullPush), Some(policy(&peer)))
            .unwrap();
    for method in [Method::POST, Method::PUT, Method::PATCH, Method::DELETE] {
        let operation = transport.begin(3).unwrap();
        assert!(transport
            .send(
                method,
                transport.endpoint.url("blobs/uploads/session").unwrap(),
                Some(Bytes::from_static(b"abc")),
                None,
                operation.deadline
            )
            .await
            .is_err());
    }
    assert_eq!(peer.state.writes.load(Ordering::Acquire), 4);
    assert_eq!(storage.state.reads.load(Ordering::Acquire), 0);
}

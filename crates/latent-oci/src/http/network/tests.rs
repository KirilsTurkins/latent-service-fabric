mod dns;
mod ownership;
#[cfg(target_os = "linux")]
mod resource;
use crate::http::auth::security_tests::peer;
mod redirects;
mod upload;

use super::{
    RegistryAddressPolicy, RegistryDestination, RegistryNetworkPolicy, RegistryResolution,
};
use crate::{
    HttpOciRegistry, OciDescriptor, OciReference, OciRegistry, RegistryActions, RegistryConfig,
    RegistryCredentials,
};
use latent_core::PlatformErrorCode;
use peer::Peer;
use std::{collections::BTreeMap, sync::atomic::Ordering, time::Duration};
use tokio::time::Instant;

fn destination(peer: &Peer, storage: bool) -> RegistryDestination {
    RegistryDestination {
        origin: format!("https://{}", peer.address),
        addresses: RegistryAddressPolicy {
            networks: vec![peer.address.ip().into()],
            special_addresses: vec![peer.address.ip()],
        },
        resolution: RegistryResolution::Static {
            addresses: vec![peer.address.ip()],
        },
        content_prefixes: if storage {
            vec!["/objects/".into()]
        } else {
            vec![]
        },
    }
}

fn policy(peer: &Peer) -> RegistryNetworkPolicy {
    RegistryNetworkPolicy {
        destinations: vec![destination(peer, false)],
        maximum_redirects: 3,
    }
}

async fn pull(client: &HttpOciRegistry, origin: &str) -> crate::http::Result<Vec<u8>> {
    client
        .pull_blob(
            &OciReference {
                registry: origin.trim_start_matches("https://").into(),
                repository: "tenant/package".into(),
                reference: "latest".into(),
            },
            &OciDescriptor {
                media_type: "application/octet-stream".into(),
                artifact_type: None,
                digest: latent_artifacts::package::artifact_blob_digest(b"abc").to_string(),
                size_bytes: 3,
                annotations: BTreeMap::new(),
            },
            3,
        )
        .await
}

#[tokio::test]
async fn explicit_network_profile_uses_owned_tls_and_preserves_bearer_cache() {
    let peer = Peer::new().await;
    let config = peer.config(RegistryActions::Pull);
    let origin = config.origin.clone();
    let client = HttpOciRegistry::new_with_network(config, policy(&peer)).unwrap();
    assert_eq!(pull(&client, &origin).await.unwrap(), b"abc");
    peer.wait_tokens(1).await;
    assert_eq!(pull(&client, &origin).await.unwrap(), b"abc");
    assert_eq!(peer.state.tokens.load(Ordering::Acquire), 1);
    assert_eq!(client.usage().network.unwrap().connections, 0);
    client
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
    let usage = client.usage().network.unwrap();
    assert!(usage.closed);
    assert_eq!(usage.reserved_connection_bytes, 0);
}

#[tokio::test]
async fn literal_address_policy_and_tls_names_cannot_be_bypassed() {
    let peer = Peer::new().await;
    let mut denied = policy(&peer);
    denied.destinations[0].addresses.special_addresses.clear();
    assert!(HttpOciRegistry::new_with_network(peer.config(RegistryActions::Pull), denied).is_err());
    assert_eq!(peer.state.reads.load(Ordering::Acquire), 0);
    let (config, mut network) = named(&peer, "wrong-name.test");
    network.destinations[0].resolution = RegistryResolution::Static {
        addresses: vec![peer.address.ip()],
    };
    let origin = config.origin.clone();
    let client = HttpOciRegistry::new_with_network(config, network).unwrap();
    assert_eq!(
        pull(&client, &origin).await.unwrap_err().code,
        PlatformErrorCode::Unavailable
    );
    assert_eq!(peer.state.tokens.load(Ordering::Acquire), 0);
    assert_eq!(peer.state.reads.load(Ordering::Acquire), 0);
    assert_eq!(client.usage().network.unwrap().connections, 0);
}

fn named(peer: &Peer, host: &str) -> (RegistryConfig, RegistryNetworkPolicy) {
    let mut config = peer.config(RegistryActions::Pull);
    config.origin = format!("https://{host}:{}", peer.address.port());
    if let RegistryCredentials::BearerChallenge { realm, .. } = &mut config.credentials {
        *realm = format!("{}/token", config.origin);
    }
    *peer.state.challenge.lock().unwrap() = Some(format!(
        "Bearer realm=\"{}/token\",service=\"registry.test\",scope=\"repository:tenant/package:pull\"", config.origin));
    let mut network = policy(peer);
    network.destinations[0].origin.clone_from(&config.origin);
    (config, network)
}

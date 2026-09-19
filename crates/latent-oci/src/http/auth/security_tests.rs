mod cancellation;
pub(in crate::http) mod peer;
mod rotation;
mod token_rules;

use super::super::{HttpOciRegistry, RegistryActions, Transport};
use crate::{OciDescriptor, OciReference, OciRegistry};
use bytes::Bytes;
use latent_core::PlatformErrorCode;
use peer::{wait_until, Peer};
use reqwest::Method;
use std::{collections::BTreeMap, sync::atomic::Ordering, time::Duration};
use tokio::time::Instant;

async fn pull(
    client: &HttpOciRegistry,
    peer: std::net::SocketAddr,
) -> crate::http::Result<Vec<u8>> {
    let reference = OciReference {
        registry: peer.to_string(),
        repository: "tenant/package".into(),
        reference: "latest".into(),
    };
    let descriptor = OciDescriptor {
        media_type: "application/octet-stream".into(),
        artifact_type: None,
        digest: latent_artifacts::package::artifact_blob_digest(b"abc").to_string(),
        size_bytes: 3,
        annotations: BTreeMap::new(),
    };
    client.pull_blob(&reference, &descriptor, 3).await
}

#[tokio::test]
async fn equivalent_tls_reads_share_one_token_and_shutdown_reclaims_it() {
    let peer = Peer::new().await;
    peer.state.hold.store(true, Ordering::Release);
    let client = HttpOciRegistry::new(peer.config(RegistryActions::Pull)).unwrap();
    let mut tasks = Vec::new();
    for _ in 0..6 {
        let client = client.clone();
        let address = peer.address;
        tasks.push(tokio::spawn(async move { pull(&client, address).await }));
    }
    peer.wait_tokens(1).await;
    wait_until(|| client.usage().bearer.unwrap().waiting_acquisitions == 5).await;
    let usage = client.usage().bearer.unwrap();
    assert_eq!(usage.active_acquisitions, 1);
    assert_eq!(usage.reserved_acquisition_bytes, 65536);
    peer.state.release.add_permits(1);
    for task in tasks {
        assert_eq!(task.await.unwrap().unwrap(), b"abc");
    }
    assert_eq!(pull(&client, peer.address).await.unwrap(), b"abc");
    assert_eq!(peer.state.tokens.load(Ordering::Acquire), 1);
    assert_eq!(client.usage().bearer.unwrap().cached_tokens, 1);
    client
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap();
    let usage = client.usage().bearer.unwrap();
    assert_eq!(usage.retained_token_bytes, 0);
    assert_eq!(usage.active_acquisitions, 0);
    assert!(usage.closed);
}

#[tokio::test]
async fn writes_authenticate_before_first_send_and_never_replay_uncertain_results() {
    for method in [Method::POST, Method::PUT, Method::PATCH, Method::DELETE] {
        for status in [0, 401, 201] {
            let peer = Peer::new().await;
            peer.state.write_status.store(status, Ordering::Release);
            let transport = Transport::new(peer.config(RegistryActions::PullPush)).unwrap();
            let operation = transport.begin(32).unwrap();
            let result = transport
                .send(
                    method.clone(),
                    transport.endpoint.url("blobs/uploads/test").unwrap(),
                    Some(Bytes::from_static(b"abc")),
                    Some("application/octet-stream"),
                    operation.deadline,
                )
                .await;
            if status == 0 {
                assert!(result.is_err());
            } else {
                assert_eq!(
                    result.unwrap().status().as_u16(),
                    u16::try_from(status).unwrap()
                );
            }
            assert_eq!(peer.state.writes.load(Ordering::Acquire), 1);
            assert_eq!(peer.state.tokens.load(Ordering::Acquire), 1);
            assert_eq!(peer.state.reads.load(Ordering::Acquire), 0);
            assert_eq!(
                transport.usage().bearer.unwrap().cached_tokens,
                usize::from(status != 401)
            );
            if status == 401 {
                peer.state.write_status.store(201, Ordering::Release);
                let next = transport.begin(32).unwrap();
                assert_eq!(
                    transport
                        .send(
                            method.clone(),
                            transport.endpoint.url("blobs/uploads/next").unwrap(),
                            Some(Bytes::from_static(b"abc")),
                            None,
                            next.deadline,
                        )
                        .await
                        .unwrap()
                        .status(),
                    reqwest::StatusCode::CREATED
                );
                assert_eq!(peer.state.writes.load(Ordering::Acquire), 2);
                assert_eq!(peer.state.tokens.load(Ordering::Acquire), 2);
            }
        }
    }
}

#[tokio::test]
async fn pull_only_credentials_reject_writes_before_any_network_work() {
    let peer = Peer::new().await;
    let transport = Transport::new(peer.config(RegistryActions::Pull)).unwrap();
    let operation = transport.begin(32).unwrap();
    let error = transport
        .send(
            Method::PUT,
            transport.endpoint.url("manifests/latest").unwrap(),
            Some(Bytes::from_static(b"abc")),
            None,
            operation.deadline,
        )
        .await
        .unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::PermissionDenied);
    assert_eq!(peer.state.tokens.load(Ordering::Acquire), 0);
    assert_eq!(peer.state.writes.load(Ordering::Acquire), 0);
}

#[tokio::test]
async fn failed_acquisitions_are_coalesced_without_a_retry_loop() {
    let peer = Peer::new().await;
    *peer.state.token_body.lock().unwrap() =
        Some(b"{\"token\":\"private-rejected-value\",\"expires_in\":0}".to_vec());
    let client = HttpOciRegistry::new(peer.config(RegistryActions::Pull)).unwrap();
    for _ in 0..8 {
        let error = pull(&client, peer.address).await.unwrap_err();
        assert_eq!(error.code, PlatformErrorCode::Unauthenticated);
        assert!(!format!("{error:?}").contains("private-rejected-value"));
    }
    assert_eq!(peer.state.tokens.load(Ordering::Acquire), 1);
    assert_eq!(client.usage().in_flight, 0);
    assert_eq!(client.usage().bearer.unwrap().retained_token_bytes, 0);
}

#[tokio::test]
async fn cache_capacity_and_epoch_authority_are_independent_between_clients() {
    let peer = Peer::new().await;
    let first = HttpOciRegistry::new(peer.config(RegistryActions::Pull)).unwrap();
    let mut second_config = peer.config(RegistryActions::Pull);
    if let crate::http::RegistryCredentials::BearerChallenge { identity, .. } =
        &mut second_config.credentials
    {
        identity.tenant.0 = "other-tenant".into();
    }
    let second = HttpOciRegistry::new(second_config).unwrap();
    assert_eq!(pull(&first, peer.address).await.unwrap(), b"abc");
    assert_eq!(pull(&second, peer.address).await.unwrap(), b"abc");
    assert_eq!(peer.state.tokens.load(Ordering::Acquire), 2);
    first
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
    assert_eq!(second.usage().bearer.unwrap().cached_tokens, 1);
}

//! Signed stream components through ordinary deployment binding and node
//! admission. This is shared-host evidence, not a standard-language claim.
use super::{
    fixture::{streams, Fixture},
    packages,
};
use latent_activation::ActivationOutcome;
use latent_artifacts::ArtifactRepository;
use latent_core::{ActivationId, CancelDisposition, PlatformErrorCode, TenantId};
use latent_network::AddressPolicy;
use latent_policy::capability::{MutationRequest, RecordKind, StreamEndpoint, StreamTransport};
use latent_streams::{StreamDestination, StreamLimits, StreamProviderConfig, StreamResolution};
use std::time::{Duration, Instant};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
};
#[path = "../outbound_streams/component.rs"]
#[allow(dead_code)]
mod component;
#[path = "../guest_sdk/package.rs"]
mod package;
#[path = "../../../latent-signing/tests/build_provenance/support.rs"]
#[allow(dead_code)]
mod provenance;
#[path = "../generic_backend/support.rs"]
#[allow(dead_code)]
mod support;

fn configuration(port: u16) -> StreamProviderConfig {
    StreamProviderConfig {
        format_version: 1,
        profile: latent_capabilities::broker::network::STREAM_PROFILE.into(),
        destinations: vec![StreamDestination {
            endpoint: StreamEndpoint {
                host: "127.0.0.1".into(),
                port,
                transport: StreamTransport::Tcp,
            },
            addresses: AddressPolicy {
                networks: vec!["127.0.0.1/32".parse().unwrap()],
                special_addresses: vec!["127.0.0.1".parse().unwrap()],
            },
            resolution: StreamResolution::Static {
                addresses: vec!["127.0.0.1".parse().unwrap()],
            },
        }],
        limits: StreamLimits::default(),
    }
}

async fn configured(root: &std::path::Path, port: u16) -> Fixture {
    let caller = packages::outbound_streams(component::bytes_with_contract(
        port,
        super::component::CALLER,
    ));
    let callee = packages::callee(42);
    let signers = package::Signers::new(latent_signing::PROVENANCE_BUILD_TYPE);
    let config = configuration(port);
    let mut uploads = vec![];
    for bundle in [&caller, &callee] {
        let mut observation = provenance::observation();
        observation.source.repository =
            "https://github.com/KirilsTurkins/latent-service-fabric".into();
        observation.component_digest = bundle.layout().component_release().unwrap().0;
        observation.component_size = bundle.blob("component.wasm").unwrap().len() as u64;
        let mut source = include_bytes!("../outbound_streams/component.rs").to_vec();
        source.extend_from_slice(include_bytes!("component.rs"));
        source.extend_from_slice(include_bytes!("packages.rs"));
        source.extend_from_slice(include_bytes!("outbound/owners.rs"));
        source.extend_from_slice(include_bytes!(
            "../../../../wit/platform/network/package.wit"
        ));
        source.extend_from_slice(&serde_json::to_vec(&config).unwrap());
        observation.source.snapshot_digest =
            latent_artifacts::package::artifact_blob_digest(&source).into_string();
        let material = observation
            .materials
            .iter_mut()
            .find(|material| material.name == "source-snapshot")
            .unwrap();
        material
            .digest
            .clone_from(&observation.source.snapshot_digest);
        material.size = source.len() as u64;
        uploads.push(signers.upload(bundle, &observation));
    }
    let catalog = package::catalog(root, signers.policy, Some(packages::budget().memory_bytes));
    for upload in uploads {
        catalog
            .admit_package(&TenantId("tenant-a".into()), upload, &mut |_| Ok(()))
            .await
            .unwrap();
    }
    Box::pin(Fixture::with_outbound_streams(
        1,
        (catalog, caller, callee),
        config,
    ))
    .await
}

fn success(receipt: latent_node::ActivationReceipt) -> latent_activation::ActivationSuccess {
    let ActivationOutcome::Succeeded(success) = receipt.outcome else {
        panic!("{:?}", receipt.outcome)
    };
    assert_eq!(
        serde_json::from_slice::<Vec<u32>>(&success.output).unwrap(),
        [4]
    );
    assert_eq!(success.consumption.outbound_requests, 1);
    assert!(success.consumption.peak_memory_bytes >= 96 * 1024);
    success
}
fn failure(receipt: latent_node::ActivationReceipt) -> latent_core::PlatformError {
    let ActivationOutcome::Failed { error, .. } = receipt.outcome else {
        panic!("{:?}", receipt.outcome)
    };
    error
}
async fn physical_closure(socket: &mut TcpStream) {
    let mut byte = [0];
    match tokio::time::timeout(Duration::from_secs(2), socket.read(&mut byte))
        .await
        .unwrap()
    {
        Ok(0) => {}
        Err(error) if error.kind() == std::io::ErrorKind::ConnectionReset => {}
        other => panic!("physical socket was retained: {other:?}"),
    }
}
async fn complete_peer(listener: &TcpListener) {
    let (mut socket, _) = listener.accept().await.unwrap();
    let mut input = Vec::new();
    socket.read_to_end(&mut input).await.unwrap();
    assert_eq!(input, b"PING");
    socket.write_all(b"PONG").await.unwrap();
    socket.shutdown().await.unwrap();
}
async fn idle(f: &Fixture) {
    f.idle().await;
    let owners = f.streams.as_ref().unwrap();
    assert_eq!(
        owners.lifecycle.status().unwrap().usage,
        latent_streams::StreamUsage::default()
    );
    assert_eq!(
        owners.io.snapshot(),
        latent_capabilities::broker::io::IoSnapshot::default()
    );
    assert_eq!(owners.pools.snapshot().unwrap().connections, 0);
    assert_eq!(owners.pools.snapshot().unwrap().running_requests, 0);
}

fn replace_record(
    f: &Fixture,
    kind: RecordKind,
    id: &str,
    operation: &str,
    document: Option<&[u8]>,
) {
    let deadline = Instant::now() + Duration::from_secs(2);
    let revision = f
        .policies
        .get("tenant-a", kind, id, 65536, deadline)
        .unwrap()
        .value()
        .as_ref()
        .unwrap()
        .revision;
    f.policies
        .mutate(
            MutationRequest {
                tenant: "tenant-a",
                actor: "operator",
                kind,
                id,
                operation_id: operation,
                expected_revision: revision,
                document,
            },
            deadline,
            |_| Ok(()),
        )
        .unwrap();
}

#[tokio::test]
async fn signed_stream_node_admission_reuses_cell_with_fresh_physical_owners() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let root = tempfile::tempdir().unwrap();
    let mut f = configured(root.path(), listener.local_addr().unwrap().port()).await;
    let peer = tokio::spawn(async move {
        for _ in 0..3 {
            complete_peer(&listener).await;
        }
    });
    for attempt in 0..3 {
        success(
            f.manager
                .start(f.request(&format!("signed-stream-{attempt}"), 0))
                .unwrap()
                .await,
        );
        idle(&f).await;
    }
    peer.await.unwrap();
    assert_eq!(f.backend.resource_snapshot().stores_created, 3);
    f.streams.take().unwrap().shutdown().await;
}

#[tokio::test]
async fn signed_stream_missing_and_stale_bindings_deny_before_peer_contact() {
    for stale in [false, true] {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let root = tempfile::tempdir().unwrap();
        let mut f = configured(root.path(), listener.local_addr().unwrap().port()).await;
        if stale {
            let mut document: serde_json::Value = serde_json::from_str(
                f.policies
                    .get(
                        "tenant-a",
                        RecordKind::ProviderBinding,
                        streams::BINDING,
                        65536,
                        Instant::now() + Duration::from_secs(2),
                    )
                    .unwrap()
                    .value()
                    .as_ref()
                    .unwrap()
                    .document
                    .as_ref()
                    .unwrap(),
            )
            .unwrap();
            document["configurationEpoch"] = serde_json::json!(2);
            replace_record(
                &f,
                RecordKind::ProviderBinding,
                streams::BINDING,
                "stale-stream-binding",
                Some(&serde_json::to_vec(&document).unwrap()),
            );
        } else {
            replace_record(
                &f,
                RecordKind::ProviderBinding,
                streams::BINDING,
                "missing-stream-binding",
                None,
            );
        }
        assert_eq!(
            failure(
                f.manager
                    .start(f.request("denied-stream", 0))
                    .unwrap()
                    .await
            )
            .code,
            PlatformErrorCode::PermissionDenied
        );
        assert!(
            tokio::time::timeout(Duration::from_millis(50), listener.accept())
                .await
                .is_err()
        );
        assert_eq!(f.backend.resource_snapshot().stores_created, 0);
        idle(&f).await;
        f.streams.take().unwrap().shutdown().await;
    }
}

#[tokio::test]
async fn signed_stream_cancellation_retires_actual_pending_io_before_fresh_work() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let root = tempfile::tempdir().unwrap();
    let mut f = configured(root.path(), listener.local_addr().unwrap().port()).await;
    let (sent, received) = tokio::sync::oneshot::channel();
    let peer = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let mut input = [0; 4];
        socket.read_exact(&mut input).await.unwrap();
        assert_eq!(&input, b"PING");
        socket.write_all(b"P").await.unwrap();
        sent.send(()).unwrap();
        physical_closure(&mut socket).await;
        complete_peer(&listener).await;
    });
    let id = ActivationId("cancel-signed-stream".into());
    let mut invocation = Box::pin(f.manager.start(f.request(&id.0, 2)).unwrap());
    tokio::select! { result = &mut invocation => panic!("read did not wait: {:?}", result.outcome), _ = received => {} }
    assert_eq!(f.backend.resource_snapshot().live_stores, 1);
    assert_eq!(f.streams.as_ref().unwrap().io.snapshot().calls, 1);
    assert_eq!(
        f.manager
            .cancel_for(&TenantId("tenant-a".into()), &id, "signed-stream-cancel")
            .unwrap(),
        CancelDisposition::Accepted
    );
    assert_eq!(f.quotas.usage().unwrap().active_activations, 1);
    assert_eq!(
        f.streams
            .as_ref()
            .unwrap()
            .lifecycle
            .status()
            .unwrap()
            .usage
            .owners,
        1
    );
    assert_eq!(failure(invocation.await).code, PlatformErrorCode::Cancelled);
    idle(&f).await;
    success(
        f.manager
            .start(f.request("fresh-after-stream-cancel", 0))
            .unwrap()
            .await,
    );
    idle(&f).await;
    peer.await.unwrap();
    f.streams.take().unwrap().shutdown().await;
}

#[tokio::test]
async fn signed_stream_policy_revocation_at_peer_barrier_retires_original_store() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let root = tempfile::tempdir().unwrap();
    let mut f = configured(root.path(), listener.local_addr().unwrap().port()).await;
    let (sent, received) = tokio::sync::oneshot::channel();
    let peer = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let mut input = [0; 4];
        socket.read_exact(&mut input).await.unwrap();
        assert_eq!(&input, b"PING");
        socket.write_all(b"P").await.unwrap();
        sent.send(()).unwrap();
        physical_closure(&mut socket).await;
    });
    let mut invocation = Box::pin(
        f.manager
            .start(f.request("revoke-signed-stream", 2))
            .unwrap(),
    );
    tokio::select! { result = &mut invocation => panic!("read did not wait: {:?}", result.outcome), _ = received => {} }
    assert_eq!(f.backend.resource_snapshot().live_stores, 1);
    replace_record(
        &f,
        RecordKind::Policy,
        streams::POLICY,
        "revoke-stream-policy",
        None,
    );
    let error = failure(
        tokio::time::timeout(Duration::from_secs(2), invocation)
            .await
            .unwrap(),
    );
    assert_ne!(error.code, PlatformErrorCode::DeadlineExceeded);
    peer.await.unwrap();
    idle(&f).await;
    f.streams.take().unwrap().shutdown().await;
}

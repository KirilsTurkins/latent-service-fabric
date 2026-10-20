//! One actual compiler-built Go fixture through signed node admission.
//! Development logical-stream ownership is not a kernel final-free certificate.
#![cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "local_service/component.rs"]
#[allow(dead_code)]
mod component;
#[path = "local_service/fixture.rs"]
#[allow(dead_code)]
mod fixture;
#[path = "guest_sdk/package.rs"]
mod package;
#[path = "local_service/packages.rs"]
#[allow(dead_code)]
mod packages;
#[path = "../../latent-signing/tests/build_provenance/support.rs"]
#[allow(dead_code)]
mod provenance;

use fixture::Fixture;
use latent_activation::{ActivationOutcome, ActivationRequest};
use latent_artifacts::ArtifactRepository;
use latent_core::{ActivationId, CancelDisposition, ContractId, PlatformErrorCode, TenantId};
use latent_network::AddressPolicy;
use latent_policy::capability::{StreamEndpoint, StreamTransport};
use latent_streams::{StreamDestination, StreamLimits, StreamProviderConfig, StreamResolution};
use serde_json::json;
use std::time::{Duration, Instant};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};

const CONTRACT: &str = "examples:go-standard-network/api@1.0.0";
const PROFILE: &str = "go-component-activation-v5";
const SOURCE: &[u8] = include_bytes!("../../../sdk/go-guest/runtime/network-conformance/main.go");
const WORLD: &str = include_str!("../../../sdk/go-guest/runtime/network-conformance/world.wit");

fn configuration(port: u16) -> StreamProviderConfig {
    StreamProviderConfig {
        format_version: 1,
        profile: latent_capabilities::broker::network::STREAM_PROFILE.into(),
        limits: StreamLimits::default(),
        destinations: vec![StreamDestination {
            tls: None,
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
    }
}

async fn configured(root: &std::path::Path, port: u16) -> Fixture {
    let prepared = std::path::PathBuf::from(
        std::env::var_os("LSF_GO_NETWORK_FIXTURE").expect("compile the guarded Go fixture"),
    );
    let record: serde_json::Value =
        serde_json::from_slice(&std::fs::read(prepared.join("GO-NETWORK-COMPILE.json")).unwrap())
            .unwrap();
    let source = std::fs::read(prepared.join("src/main.go")).unwrap();
    let component = std::fs::read(prepared.join("build/component.wasm")).unwrap();
    assert_eq!(source, SOURCE);
    assert_eq!(
        std::fs::read_to_string(prepared.join("wit/world.wit")).unwrap(),
        WORLD
    );
    assert_eq!(record["profile"], PROFILE);
    assert_eq!(record["sourceUnchanged"], true);
    assert_eq!(
        record["sourceDigest"],
        latent_artifacts::package::artifact_blob_digest(&source).as_str()
    );
    assert_eq!(
        record["componentDigest"],
        latent_artifacts::package::artifact_blob_digest(&component).as_str()
    );
    let caller = packages::go_network_runtime(component, WORLD);
    let callee = packages::callee(42);
    // This signs the actual in-process native fixture package construction.
    // The separate retained compile observation binds the real Go compiler;
    // this is not a released standalone authoring/packager qualification.
    let signers = package::Signers::new(latent_signing::PROVENANCE_BUILD_TYPE);
    let mut uploads = vec![];
    for (bundle, original) in [
        (&caller, source.as_slice()),
        (
            &callee,
            include_bytes!("local_service/component.rs").as_slice(),
        ),
    ] {
        let mut observation = provenance::observation();
        observation.source.repository =
            "https://github.com/KirilsTurkins/latent-service-fabric".into();
        observation.component_digest = bundle.layout().component_release().unwrap().0;
        observation.component_size = bundle.blob("component.wasm").unwrap().len() as u64;
        let mut capture = original.to_vec();
        capture.extend_from_slice(include_bytes!("local_service/packages.rs"));
        if std::ptr::eq(bundle, &caller) {
            capture.extend_from_slice(WORLD.as_bytes());
            capture.extend_from_slice(
                &std::fs::read(prepared.join("GO-NETWORK-COMPILE.json")).unwrap(),
            );
        }
        observation.source.snapshot_digest =
            latent_artifacts::package::artifact_blob_digest(&capture).into_string();
        let material = observation
            .materials
            .iter_mut()
            .find(|material| material.name == "source-snapshot")
            .unwrap();
        material
            .digest
            .clone_from(&observation.source.snapshot_digest);
        material.size = capture.len() as u64;
        uploads.push(signers.upload(bundle, &observation));
    }
    let catalog = package::catalog(root, signers.policy, Some(packages::budget().memory_bytes));
    for upload in uploads {
        catalog
            .admit_package(&TenantId("tenant-a".into()), upload, &mut |_| Ok(()))
            .await
            .unwrap();
    }
    Fixture::with_runtime_outbound_streams(
        (catalog, caller, callee),
        latent_core::activation_runtime::RuntimeLimits {
            tasks: 16,
            executors: 2,
            queued_work: 2,
            waits: 4,
            timers: 2,
            results: 2,
            native_owners: 2,
        },
        configuration(port),
    )
    .await
}

fn request(f: &Fixture, id: &str, mode: u32, port: u16) -> ActivationRequest {
    let mut request = f.request(id, mode);
    request.target.contract = ContractId(CONTRACT.into());
    request.input = serde_json::to_vec(&json!([mode, format!("127.0.0.1:{port}")])).unwrap();
    request
}

fn returned(receipt: latent_node::ActivationReceipt, expected: &str, contacts: u64) {
    let ActivationOutcome::Succeeded(success) = receipt.outcome else {
        panic!("{:?}", receipt.outcome);
    };
    assert_eq!(
        serde_json::from_slice::<Vec<String>>(&success.output).unwrap(),
        [expected]
    );
    assert_eq!(success.consumption.outbound_requests, contacts);
    assert!(success.consumption.cpu_fuel > 0);
    assert!(success.consumption.peak_memory_bytes <= packages::budget().memory_bytes);
}

async fn idle(f: &Fixture, label: &str) {
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
    println!(
        "GO_NETWORK_OWNER {}",
        json!({"case":label,"stores":0,"instances":0,"streamOwners":0,"ioOwners":0,"kernelRetirementQualified":false})
    );
}

fn observed(label: &str, mode: u32, result: &str, contacts: u64) {
    println!(
        "GO_NETWORK_CASE {}",
        json!({"case":label,"mode":mode,"result":result,"contacts":contacts})
    );
}

async fn peer_exchange(listener: &TcpListener, half_close: bool) {
    let (mut socket, _) = listener.accept().await.unwrap();
    let mut request = [0; 4];
    socket.read_exact(&mut request).await.unwrap();
    assert_eq!(&request, b"ping");
    if half_close {
        let mut byte = [0];
        assert_eq!(
            socket.read(&mut byte).await.unwrap(),
            0,
            "ordinary CloseWrite must send FIN while read stays live"
        );
    }
    for byte in b"pong" {
        socket.write_all(&[*byte]).await.unwrap();
        tokio::task::yield_now().await;
    }
    socket.shutdown().await.unwrap();
    let mut byte = [0];
    match tokio::time::timeout(Duration::from_secs(2), socket.read(&mut byte))
        .await
        .unwrap()
    {
        Ok(0) => (),
        Err(error) if error.kind() == std::io::ErrorKind::ConnectionReset => (),
        other => panic!("actual peer closure required: {other:?}"),
    }
}

#[tokio::test]
#[ignore = "requires a freshly constructed guarded Go net component and explicit go profile"]
#[expect(
    clippy::too_many_lines,
    reason = "one finite signed programme preserves every original owner and explicit peer barrier"
)]
async fn signed_ordinary_go_declared_tcp_preserves_refusals_io_and_cancelled_owner_retirement() {
    assert_eq!(std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(), Ok("go"));
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let root = tempfile::tempdir().unwrap();
    let mut f = configured(root.path(), port).await;
    for (mode, label, output) in [
        (0, "unsupported-network", "unsupported-network"),
        (1, "standalone-dns", "unsupported-standalone-dns"),
        (2, "pre-cancelled", "cancelled-before-connect"),
        (3, "expired", "expired-before-connect"),
        (
            5,
            "resolver-replaced",
            "unsupported-custom-default-resolver",
        ),
        (
            6,
            "resolver-prefer-go",
            "unsupported-custom-default-resolver",
        ),
        (7, "resolver-strict", "unsupported-custom-default-resolver"),
        (8, "resolver-dial", "unsupported-custom-default-resolver"),
    ] {
        returned(
            f.manager
                .start(request(&f, label, mode, port))
                .unwrap()
                .await,
            output,
            0,
        );
        idle(&f, label).await;
        assert!(
            tokio::time::timeout(Duration::from_millis(10), listener.accept())
                .await
                .is_err()
        );
        observed(label, mode, output, 0);
    }
    let (sent, received) = tokio::sync::oneshot::channel();
    let peer = tokio::spawn(async move {
        peer_exchange(&listener, false).await;
        peer_exchange(&listener, true).await;
        let (mut socket, _) = listener.accept().await.unwrap();
        let mut input = [0; 4];
        socket.read_exact(&mut input).await.unwrap();
        assert_eq!(&input, b"ping");
        socket.write_all(b"p").await.unwrap();
        sent.send(()).unwrap();
        let mut byte = [0];
        match tokio::time::timeout(Duration::from_secs(2), socket.read(&mut byte))
            .await
            .unwrap()
        {
            Ok(0) => (),
            Err(error) if error.kind() == std::io::ErrorKind::ConnectionReset => (),
            other => panic!("cancelled original socket remains live: {other:?}"),
        }
        peer_exchange(&listener, false).await;
    });
    for (mode, label, output) in [
        (4, "ordinary-tcp", "ordinary-tcp-exchange"),
        (9, "half-close-eof", "ordinary-half-close-eof"),
    ] {
        returned(
            f.manager
                .start(request(&f, label, mode, port))
                .unwrap()
                .await,
            output,
            1,
        );
        idle(&f, label).await;
        observed(label, mode, output, 1);
    }
    let id = ActivationId("go-network-cancel-pending-read".into());
    let mut invocation = Box::pin(f.manager.start(request(&f, &id.0, 4, port)).unwrap());
    tokio::select! { result = &mut invocation => panic!("read did not remain pending: {:?}",result.outcome), _ = received => {} }
    let barrier = Instant::now() + Duration::from_secs(2);
    loop {
        let usage = f
            .streams
            .as_ref()
            .unwrap()
            .lifecycle
            .status()
            .unwrap()
            .usage;
        if usage.delivered_read_bytes == 1
            && usage.pending_operations == 1
            && f.streams.as_ref().unwrap().io.snapshot().calls == 1
        {
            break;
        }
        assert!(
            Instant::now() < barrier,
            "the real second read never became pending"
        );
        tokio::select! {
            result = &mut invocation => panic!("pending read completed before cancellation: {:?}",result.outcome),
            () = tokio::task::yield_now() => (),
        }
    }
    assert_eq!(f.backend.resource_snapshot().live_stores, 1);
    assert_eq!(f.streams.as_ref().unwrap().io.snapshot().calls, 1);
    assert_eq!(
        f.manager
            .cancel_for(&TenantId("tenant-a".into()), &id, "go-network-cancel")
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
    let ActivationOutcome::Failed { error, .. } = invocation.await.outcome else {
        panic!("cancelled root must not return success");
    };
    assert_eq!(error.code, PlatformErrorCode::Cancelled);
    idle(&f, "cancel-pending-read").await;
    observed("cancel-pending-read", 4, "cancelled", 1);
    returned(
        f.manager
            .start(request(&f, "fresh-after-cancel", 4, port))
            .unwrap()
            .await,
        "ordinary-tcp-exchange",
        1,
    );
    idle(&f, "fresh-after-cancel").await;
    observed("fresh-after-cancel", 4, "ordinary-tcp-exchange", 1);
    peer.await.unwrap();
    assert_eq!(f.backend.resource_snapshot().stores_created, 12);
    f.streams.take().unwrap().shutdown().await;
    println!(
        "GO_NETWORK_COMPLETE {}",
        json!({"cases":12,"contacts":4,"cleanLogicalProviderStop":true,"kernelRetirementQualified":false,"normalProviderInstalled":false})
    );
}

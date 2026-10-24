//! SOURCE-ONLY four-case signed Write/io.Copy/transfer-credit qualification.
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
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;

use fixture::Fixture;
use latent_activation::{ActivationOutcome, ActivationRequest};
use latent_artifacts::ArtifactRepository;
use latent_core::{ContractId, TenantId};
use latent_network::AddressPolicy;
use latent_policy::capability::{StreamEndpoint, StreamTransport};
use latent_streams::{StreamDestination, StreamLimits, StreamProviderConfig, StreamResolution};
use serde_json::json;
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::oneshot,
};

const CONTRACT: &str = "examples:go-standard-network/api@1.0.0";
const PROFILE: &str = "go-component-activation-v5";
const SOURCE: &[u8] =
    include_bytes!("../../../sdk/go-guest/runtime/network-progress-conformance/main.go");
const WORLD: &str =
    include_str!("../../../sdk/go-guest/runtime/network-progress-conformance/world.wit");

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
        std::env::var_os("LSF_GO_WRITE_PROGRESS_FIXTURE").expect("compile the guarded Go fixture"),
    );
    let record: serde_json::Value = serde_json::from_slice(
        &std::fs::read(prepared.join("GO-WRITE-PROGRESS-COMPILE.json")).unwrap(),
    )
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
                &std::fs::read(prepared.join("GO-WRITE-PROGRESS-COMPILE.json")).unwrap(),
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

const WRITE_BYTES: usize = 48 * 1024 + 37;
const COPY_BYTES: usize = 40 * 1024 + 13;
const INPUT_CAP: u64 = 1024 * 1024;
const QUOTA_BYTES: usize = 1024 * 1024 + 16 * 1024;

fn request(f: &Fixture, label: &str, mode: u32, port: u16) -> ActivationRequest {
    let mut request = f.request(label, mode);
    request.target.contract = ContractId(CONTRACT.into());
    request.input = serde_json::to_vec(&json!([mode, format!("127.0.0.1:{port}")])).unwrap();
    assert_eq!(request.budget.outbound_requests, 8); // Connect charge, NOT a per-write counter.
    request
}
fn number(raw: &str) -> u64 {
    assert!(!raw.is_empty() && raw.len() <= 10 && raw.bytes().all(|byte| byte.is_ascii_digit()));
    let value: u64 = raw.parse().unwrap();
    assert_eq!(value.to_string(), raw);
    value
}
fn result(receipt: latent_node::ActivationReceipt, label: &str, mode: u32) -> serde_json::Value {
    let ActivationOutcome::Succeeded(success) = receipt.outcome else {
        panic!(
            "actual ordinary Go operation must return its typed result: {:?}",
            receipt.outcome
        );
    };
    let values: Vec<String> = serde_json::from_slice(&success.output).unwrap();
    assert_eq!(values.len(), 1);
    assert!(values[0].len() <= 256);
    let parts: Vec<_> = values[0].split('|').collect();
    let (n, accepted, uncertain, close) = if mode == 2 {
        assert_eq!(parts.len(), 6);
        assert_eq!(parts[0], "quota");
        let accepted = number(parts[1].strip_prefix("accepted=").unwrap());
        let uncertain = match parts[2].strip_prefix("may-have-applied=").unwrap() {
            "true" => true,
            "false" => false,
            other => panic!("foreign uncertainty value: {other}"),
        };
        let n = number(parts[3].strip_prefix("n=").unwrap());
        assert!(n >= 64 && n <= INPUT_CAP && accepted == n);
        assert!(parts[4] == "close=closed" || parts[4] == "close=exhausted");
        assert_eq!(parts[5], "fresh=1");
        (
            n,
            Some(accepted),
            Some(uncertain),
            parts[4].strip_prefix("close=").unwrap(),
        )
    } else {
        assert_eq!(parts.len(), 4);
        let expected = if mode == 0 { WRITE_BYTES } else { COPY_BYTES };
        assert_eq!(parts[0], if mode == 0 { "write" } else { "copy" });
        assert_eq!(parts[1], format!("n={expected}"));
        assert_eq!(parts[2], "close=closed");
        assert_eq!(parts[3], "fresh=1");
        (u64::try_from(expected).unwrap(), None, None, "closed")
    };
    assert_eq!(success.consumption.outbound_requests, 1);
    assert!(success.consumption.cpu_fuel > 0);
    assert!(success.consumption.peak_memory_bytes <= packages::budget().memory_bytes);
    // Real peer writes are effects. These reported counters are not an absence
    // claim and do not widen strict transactional or typed HTTP authority.
    let observed = json!({"case":label,"mode":mode,"result":values[0],"n":n,
        "acceptedPrefix":accepted,"mayHaveApplied":uncertain,"close":close,"fresh":1,
        "outboundRequests":success.consumption.outbound_requests,
        "reportedEffectCount":success.consumption.effect_count,
        "cpuFuel":success.consumption.cpu_fuel,"peakMemoryBytes":success.consumption.peak_memory_bytes,
        "kernelRetirementQualified":false,"normalProviderInstalled":false});
    println!("GO_WRITE_PROGRESS_CASE {observed}");
    observed
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
        "GO_WRITE_PROGRESS_OWNER {}",
        json!({"case":label,"stores":0,"instances":0,
        "streamOwners":0,"ioOwners":0,"kernelRetirementQualified":false})
    );
}
fn pattern(bytes: &[u8], offset: usize) {
    for (index, &byte) in bytes.iter().enumerate() {
        assert_eq!(
            byte,
            u8::try_from(
                u32::try_from(offset + index)
                    .unwrap()
                    .wrapping_mul(2_654_435_761)
                    >> 24
            )
            .unwrap(),
            "actual peer byte mismatch"
        );
    }
}
async fn append(socket: &mut TcpStream, bytes: &mut Vec<u8>) -> usize {
    let mut next = [0u8; 16 * 1024];
    let count = socket.read(&mut next).await.unwrap();
    assert!(
        bytes.len() + count <= QUOTA_BYTES,
        "bounded actual peer input"
    );
    pattern(&next[..count], bytes.len());
    bytes.extend_from_slice(&next[..count]);
    count
}
async fn peer(
    listener: Arc<TcpListener>,
    quota: Option<oneshot::Receiver<u64>>,
) -> serde_json::Value {
    let (mut socket, _) = listener.accept().await.unwrap();
    let mut bytes = Vec::new();
    // Bounded test-peer storage is independent observation, not a guest/native
    // allocation or new runtime budget. No fake socket or alternate transport.
    bytes.try_reserve_exact(QUOTA_BYTES).unwrap();
    if let Some(mut witness) = quota {
        let n = loop {
            tokio::select! {
                value = &mut witness => break value.unwrap(),
                count = append(&mut socket, &mut bytes) => assert_ne!(count, 0, "quota owner closed before permit"),
            }
        };
        let n = usize::try_from(n).unwrap();
        assert!(n > 0 && n <= usize::try_from(INPUT_CAP).unwrap());
        assert!(bytes.len() <= n);
        while bytes.len() < n {
            assert_ne!(
                append(&mut socket, &mut bytes).await,
                0,
                "accepted prefix truncated before permit"
            );
            assert!(bytes.len() <= n, "unreported peer side effect");
        }
        // Every locally acknowledged byte has actually reached the peer before
        // consuming Close. This is a real ordinary read on the same connection.
        socket.write_all(b"p").await.unwrap();
    }
    while append(&mut socket, &mut bytes).await != 0 {}
    json!({"bytes":bytes.len(),"sha256":latent_artifacts::package::artifact_blob_digest(&bytes).into_string(),
        "eof":true,"exactOriginalPattern":true})
}
async fn quota_barrier<F>(f: &Fixture, invocation: &mut std::pin::Pin<Box<F>>) -> serde_json::Value
where
    F: std::future::Future<Output = latent_node::ActivationReceipt>,
{
    let deadline = Instant::now() + Duration::from_secs(2);
    loop {
        let owners = f.streams.as_ref().unwrap();
        if let Ok(status) = owners.lifecycle.status() {
            let usage = status.usage;
            let io = owners.io.snapshot();
            // The guest starts this actual one-byte Read only AFTER its typed
            // write error checks. Separate output credit stays legal after the
            // input cap; the retained connection must still be live here.
            if usage.owners == 1
                && usage.connections == 1
                && usage.pending_operations == 1
                && usage.retained_chunks == 1
                && usage.input_budget_bytes == INPUT_CAP
                && io.staged_bytes == 2
                && io.buffers == 2
            {
                assert!(
                    usage.accepted_write_bytes >= 64 && usage.accepted_write_bytes <= INPUT_CAP
                );
                assert_eq!(f.backend.resource_snapshot().live_stores, 1);
                assert_eq!(f.quotas.usage().unwrap().active_activations, 1);
                let row = json!({"inputBudgetBytes":usage.input_budget_bytes,
                    "acceptedWriteBytes":usage.accepted_write_bytes,"liveConnection":true,
                    "pendingPermitRead":true,"stores":1,"activeActivations":1,
                    "ioStagedBytes":io.staged_bytes,"ioBuffers":io.buffers,
                    "perConnectionInputCap":INPUT_CAP,"perStoreTransferCap":2*INPUT_CAP,
                    "kernelRetirementQualified":false});
                println!("GO_WRITE_PROGRESS_QUOTA {row}");
                return row;
            }
        }
        assert!(
            Instant::now() < deadline,
            "actual original transfer-credit/error barrier missing"
        );
        tokio::select! {
            receipt = invocation.as_mut() => panic!("root ended before actual quota witness: {:?}", receipt.outcome),
            () = tokio::task::yield_now() => (),
        }
    }
}

#[tokio::test]
#[ignore = "requires one normal compiler-built Go progress fixture and original stream owner profile"]
async fn signed_go_large_writes_copy_and_transfer_quota_preserve_exact_peer_prefix_and_fresh_state()
{
    assert_eq!(std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(), Ok("go"));
    assert_eq!(StreamLimits::default().maximum_transfer_bytes, INPUT_CAP);
    let listener = Arc::new(TcpListener::bind("127.0.0.1:0").await.unwrap());
    let port = listener.local_addr().unwrap().port();
    let root = tempfile::tempdir().unwrap();
    let mut f = configured(root.path(), port).await;
    for (mode, label) in [
        (0, "large-write"),
        (1, "ordinary-copy"),
        (2, "transfer-quota"),
        (0, "fresh-after-quota"),
    ] {
        let (sent, received) = oneshot::channel();
        let peer = tokio::spawn(peer(Arc::clone(&listener), (mode == 2).then_some(received)));
        let mut invocation = Box::pin(f.manager.start(request(&f, label, mode, port)).unwrap());
        let quota = if mode == 2 {
            let row = quota_barrier(&f, &mut invocation).await;
            sent.send(row["acceptedWriteBytes"].as_u64().unwrap())
                .unwrap();
            Some(row)
        } else {
            drop(sent);
            None
        };
        let actual = result(invocation.await, label, mode);
        let peer = tokio::time::timeout(Duration::from_secs(2), peer)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(
            peer["bytes"], actual["n"],
            "actual peer prefix must exactly equal ordinary Go count"
        );
        if let Some(quota) = quota {
            assert_eq!(quota["acceptedWriteBytes"], actual["n"]);
        }
        println!(
            "GO_WRITE_PROGRESS_PEER {}",
            json!({"case":label,"peer":peer})
        );
        idle(&f, label).await;
    }
    assert_eq!(f.backend.resource_snapshot().stores_created, 4);
    f.streams.take().unwrap().shutdown().await;
    println!(
        "GO_WRITE_PROGRESS_COMPLETE {}",
        json!({"cases":4,"contacts":4,"cleanLogicalProviderStop":true,
        "kernelRetirementQualified":false,"normalProviderInstalled":false,"wholeGoNetworkingQualified":false})
    );
}

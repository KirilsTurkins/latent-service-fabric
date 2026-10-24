//! SOURCE-ONLY signed probe. No execution or physical-kernel certificate yet.
#![cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "local_service/component.rs"]
#[allow(dead_code)]
mod component;
#[path = "typescript_import_borrow_release/composition.rs"]
mod composition;
#[path = "local_service/fixture.rs"]
#[allow(dead_code)]
mod fixture;
#[path = "typescript_import_borrow_release/gate.rs"]
mod gate;
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
use latent_core::{ContractId, PlatformErrorCode, TenantId};
use latent_executor::ExecutionBackend;
use latent_network::AddressPolicy;
use latent_policy::capability::{StreamEndpoint, StreamTransport};
use latent_streams::{StreamDestination, StreamLimits, StreamProviderConfig, StreamResolution};
use serde_json::{json, Value};
use std::{
    future::Future,
    io::Read,
    path::Path,
    pin::Pin,
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::oneshot,
};

const SOURCE: &[u8] = include_bytes!("../../../sdk/typescript-guest/probes/borrow-release/main.ts");
const WORLD: &[u8] =
    include_bytes!("../../../sdk/typescript-guest/probes/borrow-release/world.wit");
const GATE_WIT: &[u8] =
    include_bytes!("../../../sdk/typescript-guest/probes/borrow-release/gate.wit");
const PROFILE: &str = "lsf-typescript-borrow-probe-v1";

fn read(path: &Path, maximum: usize) -> Vec<u8> {
    assert!(std::fs::symlink_metadata(path)
        .unwrap()
        .file_type()
        .is_file());
    let mut bytes = Vec::new();
    std::fs::File::open(path)
        .unwrap()
        .take(u64::try_from(maximum).unwrap() + 1)
        .read_to_end(&mut bytes)
        .unwrap();
    assert!(bytes.len() <= maximum);
    bytes
}
fn digest(bytes: &[u8]) -> String {
    latent_artifacts::package::artifact_blob_digest(bytes).into_string()
}
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

#[expect(
    clippy::too_many_lines,
    reason = "one actual source/compiler/composition/signing chain; no receipt rebinding"
)]
async fn configured(root: &Path, port: u16) -> Fixture {
    assert_eq!(
        std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(),
        Ok("typescript")
    );
    let prepared = std::path::PathBuf::from(
        std::env::var_os("LSF_TYPESCRIPT_BORROW_FIXTURE")
            .expect("compile the guarded probe against the ACTUAL qualified OWN-result engine"),
    );
    let observation_raw = read(&prepared.join("BORROW-COMPILE.json"), 1024 * 1024);
    let observed: Value = serde_json::from_slice(&observation_raw).unwrap();
    assert_eq!(
        observed["schemaVersion"],
        "latent.typescript.borrow-probe-compile.v1"
    );
    assert_eq!(observed["profile"], PROFILE);
    assert_eq!(observed["status"], "passed");
    assert_eq!(observed["sourceUnchanged"], true);
    assert_eq!(observed["engineQualificationStatus"], "passed");
    // The owning selector must authenticate this complete producer first;
    // these bytes remain its original receipt, never rebound to this programme.
    let own_raw = read(
        &prepared.join("engine-qualification/OWN-RESULTS.json"),
        4 * 1024 * 1024,
    );
    let own: Value = serde_json::from_slice(&own_raw).unwrap();
    assert_eq!(
        own["schemaVersion"],
        "latent.typescript.owned-result-prerequisites.v1"
    );
    assert_eq!(own["status"], "passed");
    assert_eq!(
        own["scope"],
        "fresh-normal-compiler-engine-unit-native-ABI-prerequisites"
    );
    for field in [
        "canonicalOwnComponentExecuted",
        "tableReuseQualified",
        "signedExecution",
        "physicalProviderQualified",
        "wholeCostQualification",
    ] {
        assert_eq!(
            own[field], false,
            "prerequisite receipt must preserve its actual scope"
        );
    }
    for field in ["sourceCommit", "sourceTree"] {
        let identity = own[field]
            .as_str()
            .expect("actual Git source identity required");
        assert_eq!(identity.len(), 40);
        assert!(identity
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)));
    }
    let engine_input = own["engineProducts"]["engine-input.json"]["sha256"]
        .as_str()
        .expect("actual fresh engine-input identity required");
    assert_eq!(engine_input.len(), 71);
    let engine_input_hex = engine_input
        .strip_prefix("sha256:")
        .expect("normal canonical digest required");
    assert!(engine_input_hex
        .bytes()
        .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)));
    assert_eq!(observed["engineInputDigest"], engine_input);
    assert_eq!(observed["ownResultsDigest"], digest(&own_raw));
    assert_eq!(observed["engineSourceCommit"], own["sourceCommit"]);
    assert_ne!(
        observed["engineInputDigest"],
        "sha256:18557c70748fd27daefa296d7bcc156533f5f943317489c3a256e16b2c78918b",
        "historical known generated-finally failure is NOT a pass candidate"
    );
    for (name, expected) in [
        ("src/main.ts", SOURCE),
        ("wit/world.wit", WORLD),
        ("wit/deps/gate/package.wit", GATE_WIT),
        (
            "wit/deps/network/package.wit",
            include_bytes!("../../../wit/platform/network/package.wit").as_slice(),
        ),
    ] {
        assert_eq!(read(&prepared.join(name), 256 * 1024), expected);
    }
    assert_eq!(observed["sourceDigest"], digest(SOURCE));
    let raw_guest = read(&prepared.join("build/component.wasm"), 32 * 1024 * 1024);
    assert_eq!(observed["rawComponentDigest"], digest(&raw_guest));
    let composed = composition::bytes(&raw_guest);
    println!(
        "TYPESCRIPT_BORROW_COMPOSITION {}",
        json!({"rawCompilerProductDigest":digest(&raw_guest),
        "composedDigest":digest(&composed),"gateSourceDigest":digest(include_bytes!("typescript_import_borrow_release/gate.rs")),
        "originalCapabilityImports":1,"resourceHandleAdoption":false,"signedQualification":"not-inferred-from-source"})
    );
    let caller = packages::typescript_borrow_probe(composed, composition::WORLD);
    let callee = packages::callee(42);
    let release = packages::release(&caller);
    let signers = package::Signers::new(latent_signing::PROVENANCE_BUILD_TYPE);
    let mut uploads = Vec::new();
    for bundle in [&caller, &callee] {
        let mut observation = provenance::observation();
        observation.source.repository =
            "https://github.com/KirilsTurkins/latent-service-fabric".into();
        observation.component_digest = bundle.layout().component_release().unwrap().0;
        observation.component_size = bundle.blob("component.wasm").unwrap().len() as u64;
        // This is the in-process composed signed test package observation. The
        // retained raw compile observation is separately bound, not rewritten.
        let mut capture = include_bytes!("local_service/packages.rs").to_vec();
        capture.extend_from_slice(include_bytes!("typescript_import_borrow_release.rs"));
        capture.extend_from_slice(include_bytes!("typescript_import_borrow_release/gate.rs"));
        capture.extend_from_slice(include_bytes!(
            "typescript_import_borrow_release/composition.rs"
        ));
        capture.extend_from_slice(composition::WORLD.as_bytes());
        capture.extend_from_slice(SOURCE);
        capture.extend_from_slice(&observation_raw);
        capture.extend_from_slice(&own_raw);
        observation.source.snapshot_digest = digest(&capture);
        let material = observation
            .materials
            .iter_mut()
            .find(|value| value.name == "source-snapshot")
            .unwrap();
        material
            .digest
            .clone_from(&observation.source.snapshot_digest);
        material.size = u64::try_from(capture.len()).unwrap();
        uploads.push(signers.upload(bundle, &observation));
    }
    let catalog = package::catalog(root, signers.policy, Some(packages::budget().memory_bytes));
    for upload in uploads {
        catalog
            .admit_package(&TenantId("tenant-a".into()), upload, &mut |_| Ok(()))
            .await
            .unwrap();
    }
    // EXACT existing TypeScript runtime ceilings; no new quota.
    let f = Fixture::with_runtime_outbound_streams(
        (catalog, caller, callee),
        latent_core::activation_runtime::RuntimeLimits {
            tasks: 16,
            executors: 2,
            queued_work: 16,
            waits: 8,
            timers: 8,
            results: 8,
            native_owners: 64,
        },
        configuration(port),
    )
    .await;
    let publication = f
        .catalog
        .execution_eligibility_selected(&release, None)
        .unwrap()
        .unwrap()
        .publication()
        .clone();
    let mut key = f.backend.preparation_key(&release).unwrap();
    key.publication = Some(publication);
    let ready = tokio::time::timeout(
        Duration::from_secs(600),
        f.backend
            .prepare_ready_from_repository(f.catalog.clone(), key),
    )
    .await
    .unwrap()
    .unwrap();
    drop(f.backend.materialize_ready(ready).unwrap());
    f.idle().await;
    assert_eq!(f.backend.resource_snapshot().stores_created, 0);
    f
}
fn request(f: &Fixture, label: &str, mode: u32, port: u16) -> ActivationRequest {
    let mut request = f.request(label, mode);
    request.target.contract = ContractId(composition::CONTRACT.into());
    request.input = serde_json::to_vec(&json!([mode, port])).unwrap();
    assert_eq!(request.budget.outbound_requests, 8);
    if mode == 2 {
        request.budget.wall_time_limit_millis = Some(1500);
    }
    request
}
fn sample(f: &Fixture, label: &str) -> Value {
    let owners = f.streams.as_ref().unwrap();
    let stream = owners.lifecycle.status().unwrap().usage;
    let io = owners.io.snapshot();
    let pool = owners.pools.snapshot().unwrap();
    let root = f.backend.resource_snapshot();
    let quota = f.quotas.usage().unwrap();
    let value = json!({"stage":label,"stream":stream,
        "io":{"calls":io.calls,"running":io.occupied_running_slots,"queued":io.queued_calls,
            "stagedBytes":io.staged_bytes,"resultBytes":io.result_bytes,"buffers":io.buffers,
            "streams":io.streams,"metadataBytes":io.metadata_bytes},
        "poolConnections":pool.connections,"poolRunningRequests":pool.running_requests,
        "liveStores":root.live_stores,"liveInstances":root.live_component_instances,
        "activeActivations":quota.active_activations,"queuedActivations":quota.queued_activations,
        "kernelRetirementQualified":false});
    println!("TYPESCRIPT_BORROW_OWNER {value}");
    value
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
    sample(f, label);
}
async fn marker<F>(invocation: &mut Pin<Box<F>>, signal: oneshot::Receiver<()>, label: &str)
where
    F: Future<Output = latent_node::ActivationReceipt>,
{
    tokio::select! {
        result = invocation.as_mut() => panic!("premature root terminal before {label}: {:?}",result.outcome),
        value = signal => value.unwrap(),
        () = tokio::time::sleep(Duration::from_millis(500)) => panic!("missing real peer marker: {label}"),
    }
}
async fn read_admitted<F>(
    f: &Fixture,
    invocation: &mut Pin<Box<F>>,
    connections: usize,
    staged_bytes: usize,
    label: &str,
) where
    F: Future<Output = latent_node::ActivationReceipt>,
{
    let until = Instant::now() + Duration::from_millis(500);
    loop {
        if let Ok(status) = f.streams.as_ref().unwrap().lifecycle.status() {
            let usage = status.usage;
            let io = f.streams.as_ref().unwrap().io.snapshot();
            // Each pending output read reserves one real byte buffer PLUS its
            // real copy reservation: primary16 ->32, control/permit1 ->2.
            // IoCall/IoTransfer are connection lifetime owners, not per-read
            // retirement witnesses. Their actual values are recorded only.
            if usage.connections == connections
                && usage.pending_operations == connections
                && usage.retained_chunks == connections
                && io.staged_bytes == staged_bytes
            {
                assert_eq!(usage.owners, connections);
                assert_eq!(io.buffers, connections * 2);
                assert!(
                    io.calls >= connections,
                    "original connection IoCalls stay admitted"
                );
                assert!(
                    io.streams >= connections,
                    "original IoTransfers stay admitted"
                );
                assert_eq!(
                    f.streams
                        .as_ref()
                        .unwrap()
                        .pools
                        .snapshot()
                        .unwrap()
                        .connections,
                    connections
                );
                assert_eq!(f.backend.resource_snapshot().live_stores, 1);
                assert_eq!(f.quotas.usage().unwrap().active_activations, 1);
                sample(f, label);
                return;
            }
        }
        assert!(
            Instant::now() < until,
            "real read admission never matched: {label}"
        );
        tokio::select! {
            result = invocation.as_mut() => panic!("premature terminal before real read barrier: {:?}",result.outcome),
            () = tokio::task::yield_now() => (),
        }
    }
}
async fn expect_bytes(socket: &mut TcpStream, expected: &[u8]) {
    let mut bytes = vec![0; expected.len()];
    tokio::time::timeout(Duration::from_secs(2), socket.read_exact(&mut bytes))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(bytes, expected);
}
async fn eof(socket: &mut TcpStream) {
    let mut byte = [0];
    match tokio::time::timeout(Duration::from_secs(2), socket.read(&mut byte))
        .await
        .unwrap()
    {
        Ok(0) => (),
        Err(error) if error.kind() == std::io::ErrorKind::ConnectionReset => (),
        other => panic!("actual original peer closure required: {other:?}"),
    }
}
fn result(receipt: latent_node::ActivationReceipt, mode: u32, label: &str) {
    let (status, consumed) = match receipt.outcome {
        ActivationOutcome::Succeeded(success) => {
            assert!(mode == 0 || mode == 3);
            let expected = if mode == 0 {
                "logical-rejected|borrow-released|connection-consumed"
            } else {
                "normal-read|copied|chunk-disposed|connection-consumed"
            };
            assert_eq!(
                serde_json::from_slice::<Vec<String>>(&success.output).unwrap(),
                [expected]
            );
            ("succeeded", success.consumption)
        }
        ActivationOutcome::Failed {
            error, consumption, ..
        } => {
            assert_eq!(
                error.code,
                if mode == 1 {
                    PlatformErrorCode::GuestTrap
                } else {
                    PlatformErrorCode::DeadlineExceeded
                }
            );
            assert!(mode == 1 || mode == 2);
            if mode == 1 {
                let kinds: Vec<_> = error
                    .details
                    .iter()
                    .filter(|detail| detail.kind == "activation.guest-trap-kind")
                    .collect();
                assert_eq!(
                    kinds.len(),
                    1,
                    "one actual closed trap classification required"
                );
                assert_eq!(
                    kinds[0].fields.get("kind").map(String::as_str),
                    Some("integer-division-by-zero"),
                    "incidental JS/wrong-phase traps must fail"
                );
            }
            ("intended-platform-failure", consumption)
        }
        other => panic!("unexpected declared outcome: {other:?}"),
    };
    assert!(consumed.outbound_requests <= 8);
    assert!(consumed.peak_memory_bytes <= packages::budget().memory_bytes);
    assert!(consumed.cpu_fuel > 0);
    println!(
        "TYPESCRIPT_BORROW_CASE {}",
        json!({"case":label,"mode":mode,"status":status,
        "plannedNetworkWitDispatches":if mode==3 {5} else {8},
        "consumedOutboundRequests":consumed.outbound_requests,
        "kernelRetirementQualified":false,"productionProviderInstalled":false})
    );
}

#[tokio::test]
#[ignore = "requires the fixed fresh TS probe and actual qualified OWN-result engine, never historical1399"]
#[expect(
    clippy::too_many_lines,
    reason = "one finite signed programme preserves real peer barriers and fresh admission"
)]
async fn signed_borrow_release_preserves_original_socket_until_consuming_close_and_root_retirement()
{
    let listener = Arc::new(TcpListener::bind("127.0.0.1:0").await.unwrap());
    let port = listener.local_addr().unwrap().port();
    let directory = tempfile::tempdir().unwrap();
    let mut f = configured(directory.path(), port).await;
    // Four semantic cases plus a fresh successful activation after each failure.
    for (mode, label) in [
        (3, "normal-copy-dispose"),
        (0, "logical-cancel-before-borrow-release"),
        (1, "root-trap-with-held-borrow"),
        (3, "fresh-after-trap"),
        (2, "root-deadline-with-held-borrow"),
        (3, "fresh-after-deadline"),
    ] {
        let (held_tx, held_rx) = oneshot::channel();
        let (admit_tx, admit_rx) = oneshot::channel();
        let (ack_tx, ack_rx) = oneshot::channel();
        let (close_tx, close_rx) = oneshot::channel();
        let (terminal_tx, mut terminal_rx) = oneshot::channel();
        let (cleanup_tx, cleanup_rx) = oneshot::channel();
        let listener = Arc::clone(&listener);
        let peer = tokio::spawn(async move {
            let (mut primary, _) = listener.accept().await.unwrap();
            if mode == 3 {
                expect_bytes(&mut primary, b"norm").await;
                primary.write_all(b"p").await.unwrap();
                eof(&mut primary).await;
                return;
            }
            let mut control = if mode == 1 || mode == 2 {
                Some(listener.accept().await.unwrap().0)
            } else {
                None
            };
            expect_bytes(&mut primary, b"canc").await;
            held_tx.send(()).unwrap();
            admit_rx.await.unwrap();
            if let Some(control) = &mut control {
                control.write_all(b"t").await.unwrap();
                eof(control).await;
                expect_bytes(&mut primary, b"held").await;
                terminal_tx.send(()).unwrap();
                let release: bool = cleanup_rx.await.unwrap();
                if release {
                    let _ = primary.write_all(b"p").await;
                }
                eof(&mut primary).await;
                return;
            }
            expect_bytes(&mut primary, b"rels").await;
            primary.write_all(b"p").await.unwrap();
            expect_bytes(&mut primary, b"ack!").await;
            ack_tx.send(()).unwrap();
            close_rx.await.unwrap();
            primary.write_all(b"c").await.unwrap();
            eof(&mut primary).await;
        });
        let started = Instant::now();
        let mut invocation = Box::pin(f.manager.start(request(&f, label, mode, port)).unwrap());
        let receipt = if mode == 3 {
            invocation.await
        } else {
            marker(&mut invocation, held_rx, "cancelled-original-read").await;
            read_admitted(
                &f,
                &mut invocation,
                if mode == 0 { 1 } else { 2 },
                if mode == 0 { 32 } else { 34 },
                "held-before-release",
            )
            .await;
            admit_tx.send(()).unwrap();
            if mode == 0 {
                marker(&mut invocation, ack_rx, "actual-borrow-acknowledged").await;
                read_admitted(
                    &f,
                    &mut invocation,
                    1,
                    2,
                    "ack-original-live;new-permit-read-separately-admitted",
                )
                .await;
                close_tx.send(()).unwrap();
                invocation.await
            } else {
                // A terminal may race network delivery of the held marker, but
                // it is NEVER accepted without the actual post-control-close
                // marker. Deadline before that barrier is a campaign FAILURE.
                let completed = tokio::select! {
                    value = &mut terminal_rx => {value.unwrap();None},
                    receipt = invocation.as_mut() => {
                        tokio::time::timeout(Duration::from_millis(500),terminal_rx).await.unwrap().unwrap();Some(receipt)
                    },
                };
                let completed = if completed.is_some() {
                    completed
                } else {
                    let bound = started + Duration::from_millis(if mode == 1 { 150 } else { 1700 });
                    tokio::time::timeout_at(bound.into(), invocation.as_mut())
                        .await
                        .ok()
                };
                let retained = f
                    .streams
                    .as_ref()
                    .unwrap()
                    .lifecycle
                    .status()
                    .unwrap()
                    .usage
                    .owners
                    > 0
                    || f.streams.as_ref().unwrap().io.snapshot()
                        != latent_capabilities::broker::io::IoSnapshot::default();
                assert!(
                    completed.is_some() || retained,
                    "pending root cannot lose all actual owners"
                );
                sample(
                    &f,
                    if retained {
                        "outstanding-owners-still-charged"
                    } else {
                        "actual-owners-already-retired"
                    },
                );
                cleanup_tx.send(retained).unwrap();
                match completed {
                    Some(receipt) => receipt,
                    None => tokio::time::timeout(Duration::from_secs(3), invocation.as_mut())
                        .await
                        .expect("retained root must complete after actual peer release"),
                }
            }
        };
        result(receipt, mode, label);
        peer.await.unwrap();
        idle(&f, label).await;
    }
    assert_eq!(f.backend.resource_snapshot().stores_created, 6);
    f.streams.take().unwrap().shutdown().await;
    println!(
        "TYPESCRIPT_BORROW_COMPLETE {}",
        json!({"semanticCases":4,"freshAfterFailure":2,
        "kernelRetirementQualified":false,"wholeCostQualification":false,"productionEnablement":false})
    );
}

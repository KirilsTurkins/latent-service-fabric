//! A second closed programme inside the existing signed stream owner/harness.
use super::*;

const MAIN: &[u8] = include_bytes!("../../../../sdk/typescript-guest/probes/node-net/main.ts");
const WIT: &[u8] = include_bytes!("../../../../sdk/typescript-guest/probes/node-net/world.wit");
const CONTRACT: &str = "tenant-a:typescript-node-net/api@1.0.0";

async fn configured_socket(root: &Path, port: u16) -> (Fixture, latent_core::ResourceBudget) {
    let prepared =
        std::path::PathBuf::from(std::env::var_os("LSF_TYPESCRIPT_BORROW_FIXTURE").unwrap());
    assert_eq!(
        read(&prepared.join("project/src/main.ts"), 256 * 1024),
        MAIN
    );
    assert_eq!(
        read(&prepared.join("project/wit/world.wit"), 256 * 1024),
        WIT
    );
    let artifact = prepared.join("typescript-node-net-service");
    let observed = package::observation("typescript-node-net-service");
    assert_eq!(
        observed.build_type,
        latent_signing::TYPESCRIPT_CAPSULE_BUILD_TYPE
    );
    let caller = package::bundle(&artifact);
    assert_eq!(
        caller.blob("component.wasm").unwrap(),
        read(&artifact.join("component.wasm"), 64 * 1024 * 1024)
    );
    assert_eq!(
        caller.blob("typescript-net-selection.json").unwrap(),
        read(&artifact.join("typescript-net-selection.json"), 65536)
    );
    let selected: Value =
        serde_json::from_slice(caller.blob("typescript-net-selection.json").unwrap()).unwrap();
    assert_eq!(selected["profile"], "lsf-node-net-tcp-v1");
    assert_eq!(selected["qualification"], "unknown");
    assert_eq!(selected["automaticCloseDrain"], false);
    let callee = packages::callee(42);
    let signers = package::Signers::typescript_with_echo_fixture();
    let caller_upload = signers.upload(&caller, &observed);
    let mut callee_observation = provenance::observation();
    callee_observation.source.repository =
        "https://github.com/KirilsTurkins/latent-service-fabric".into();
    callee_observation.component_digest = packages::release(&callee).0;
    callee_observation.component_size = callee.blob("component.wasm").unwrap().len() as u64;
    let callee_upload = signers.upload(&callee, &callee_observation);
    let release = packages::release(&caller);
    let catalog = package::catalog(root, signers.policy, Some(128 * 1024 * 1024));
    for upload in [caller_upload, callee_upload] {
        catalog
            .admit_package(&TenantId("tenant-a".into()), upload, &mut |_| Ok(()))
            .await
            .unwrap();
    }
    let f = Fixture::with_runtime_outbound_streams_and_numeric_trap_observation(
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
    let budget = f
        .catalog
        .fetch(&release)
        .await
        .unwrap()
        .manifest
        .execution
        .resource_budget_ceiling;
    (f, budget)
}

pub(super) async fn run() {
    let listener = Arc::new(TcpListener::bind("127.0.0.1:0").await.unwrap());
    let alternate = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let denied_port = alternate.local_addr().unwrap().port();
    let directory = tempfile::tempdir().unwrap();
    let (mut f, budget) = configured_socket(directory.path(), port).await;
    let observer = f.backend.arm_development_trap_observation().unwrap();
    for (index, (mode, label)) in [
        (0, "node-net-echo"),
        (1, "node-net-sibling"),
        (2, "node-net-denied"),
        (3, "node-net-destroy"),
        (4, "node-net-unclosed"),
        (0, "node-net-fresh"),
    ]
    .into_iter()
    .enumerate()
    {
        let before = observer.snapshot().unwrap();
        let mut request = f.request(label, mode);
        request.target.contract = ContractId(CONTRACT.into());
        request.input =
            serde_json::to_vec(&json!([mode, if mode == 2 { denied_port } else { port }])).unwrap();
        // The normal package's actual lower grant, not the generic fixture10b ceiling.
        request.budget = budget.clone();
        assert_eq!(request.budget.cpu_fuel, 1_000_000_000);
        assert_eq!(request.budget.memory_bytes, 128 * 1024 * 1024);
        assert_eq!(request.budget.wall_time_limit_millis, Some(120_000));
        assert_eq!(request.budget.outbound_requests, 8);
        assert_eq!(request.budget.child_calls, 0);
        assert_eq!(request.budget.log_bytes, 0);
        assert_eq!(request.budget.effect_count, 0);
        let granted = request.budget.clone();
        let (entered_tx, entered_rx) = oneshot::channel();
        let (permit_tx, permit_rx) = oneshot::channel();
        let (closed_tx, mut closed_rx) = oneshot::channel();
        let (release_tx, release_rx) = oneshot::channel();
        let peer_listener = Arc::clone(&listener);
        let peer = tokio::spawn(async move {
            if mode == 2 {
                return;
            }
            let (mut primary, _) = peer_listener.accept().await.unwrap();
            if mode == 0 {
                expect_bytes(&mut primary, b"q").await;
                eof(&mut primary).await;
                primary.write_all(b"q").await.unwrap();
                primary.shutdown().await.unwrap();
                return;
            }
            let (mut control, _) = peer_listener.accept().await.unwrap();
            entered_tx.send(()).unwrap();
            permit_rx.await.unwrap();
            control.write_all(b"p").await.unwrap();
            if mode == 1 {
                expect_bytes(&mut primary, b"s").await;
                eof(&mut primary).await;
                eof(&mut control).await;
            } else if mode == 3 {
                eof(&mut primary).await;
                expect_bytes(&mut control, b"a").await;
                eof(&mut control).await;
            } else {
                eof(&mut control).await;
                closed_tx.send(()).unwrap();
                release_rx.await.unwrap();
                // Real release only after terminal observation/retained-owner sample.
                let _ = primary.write_all(b"p").await;
                drop(primary);
            }
        });
        let mut held_owner = None;
        let mut control_peer_eof = false;
        let mut primary_released_after_observation = false;
        let mut invocation = Box::pin(f.manager.start(request).unwrap());
        let receipt = if mode == 0 || mode == 2 {
            invocation.await
        } else {
            marker(&mut invocation, entered_rx, "node-net-two-real-connections").await;
            read_admitted(
                &f,
                &mut invocation,
                2,
                65536,
                "node-net-two-real-read-barrier",
            )
            .await;
            // Original two admitted reads and owners exist BEFORE any peer
            // permission, application completion, or root teardown.
            held_owner = Some(sample(&f, "node-net-before-peer-permit"));
            permit_tx.send(()).unwrap();
            if mode != 4 {
                invocation.await
            } else {
                let early = tokio::select! {
                    value = &mut closed_rx => {value.unwrap();None},
                    value = invocation.as_mut() => {
                        tokio::time::timeout(Duration::from_millis(500), closed_rx).await.unwrap().unwrap();Some(value)
                    }
                };
                control_peer_eof = true;
                let completed = match early {
                    Some(value) => Some(value),
                    None => tokio::time::timeout(Duration::from_millis(150), invocation.as_mut())
                        .await
                        .ok(),
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
                    "pending original work cannot lose all real owners"
                );
                sample(
                    &f,
                    if retained {
                        "node-net-unclosed-owners-retained"
                    } else {
                        "node-net-unclosed-owners-retired"
                    },
                );
                release_tx.send(()).unwrap();
                primary_released_after_observation = true;
                match completed {
                    Some(value) => value,
                    None => tokio::time::timeout(Duration::from_secs(3), invocation.as_mut())
                        .await
                        .unwrap(),
                }
            }
        };
        peer.await.unwrap();
        if matches!(mode, 1 | 3) {
            control_peer_eof = true;
        }
        let diagnostic = observer.snapshot().unwrap();
        if diagnostic.observed_errors != 0 || diagnostic.borrow_admission_refusal.is_some() {
            let raw = serde_json::to_string(&diagnostic).unwrap();
            assert!(raw.len() <= 8192);
            println!("TYPESCRIPT_NODE_NET_ORIGINAL_ERROR {raw}");
        }
        // A quota refusal must not masquerade as the deliberately unclosed root.
        assert!(
            diagnostic.borrow_admission_refusal.is_none(),
            "actual first original admission failure"
        );
        let (status, used, public_code, public_trap) = match receipt.outcome {
            ActivationOutcome::Succeeded(success) => {
                let expected = match mode {
                    0 => "node-net:echo:pass",
                    1 => "node-net:sibling:pass",
                    2 => "node-net:denied:EACCES",
                    3 => "node-net:destroy:pass",
                    _ => panic!("unclosed root escaped"),
                };
                assert_eq!(
                    serde_json::from_slice::<Vec<String>>(&success.output).unwrap(),
                    [expected]
                );
                assert_eq!(diagnostic.observed_errors, before.observed_errors);
                ("succeeded", success.consumption, "none".to_owned(), None)
            }
            ActivationOutcome::Failed {
                error, consumption, ..
            } => {
                assert_eq!(mode, 4);
                assert_eq!(error.code, PlatformErrorCode::GuestTrap);
                let public_trap = public_unknown_failure(&error);
                println!(
                    "TYPESCRIPT_NODE_NET_FAILURE {}",
                    json!({"case":label,"code":error.code.wire_code(),"trap":public_trap})
                );
                // Original JS text is intentionally erased at the public
                // error boundary. Observe cleanup failure with the required
                // source-bound owner/protocol/paired-positive/fresh conditions;
                // do not claim that this identifies the throwing instruction.
                assert!(held_owner.is_some());
                assert!(control_peer_eof && primary_released_after_observation);
                (
                    "failed-with-unclosed-stream-owners",
                    consumption,
                    error.code.wire_code().to_owned(),
                    Some(public_trap),
                )
            }
            other => panic!("unexpected actual outcome: {other:?}"),
        };
        assert!(used.outbound_requests <= 8);
        assert!(used.cpu_fuel <= granted.cpu_fuel);
        assert!(used.peak_memory_bytes <= granted.memory_bytes);
        assert_eq!(used.child_calls, 0);
        assert_eq!(used.log_bytes, 0);
        assert_eq!(used.effect_count, 0);
        assert!(
            tokio::time::timeout(Duration::from_millis(50), alternate.accept())
                .await
                .is_err(),
            "denied endpoint had actual contact"
        );
        idle(&f, label).await;
        let post_root = sample(&f, "node-net-post-root-idle");
        println!(
            "TYPESCRIPT_NODE_NET_CASE {}",
            json!({"case":label,"mode":mode,"index":index,"status":status,
            "outboundRequests":used.outbound_requests,"cpuFuel":used.cpu_fuel,"peakMemoryBytes":used.peak_memory_bytes,
            "grantFuel":granted.cpu_fuel,"grantMemoryBytes":granted.memory_bytes,"grantWallTimeMillis":granted.wall_time_limit_millis,
            "outboundCeiling":8,"sameBackend":true,"kernelRetirementQualified":false,"publicErrorCode":public_code,"publicTrap":public_trap,
            "heldOwnerBeforePermit":held_owner,"controlPeerEOF":control_peer_eof,"recordedAdmissionRefusal":diagnostic.borrow_admission_refusal.is_some(),
            "primaryReleasedAfterObservation":primary_released_after_observation,"postRoot":post_root,
            "originalFailureCause":if mode==4 {"unknown"} else {"not-applicable"},
            "guardAttribution":if mode==4 {"source-only"} else {"not-applicable"}})
        );
    }
    assert_eq!(f.backend.resource_snapshot().stores_created, 6);
    drop(observer);
    f.streams.take().unwrap().shutdown().await;
    println!(
        "TYPESCRIPT_NODE_NET_COMPLETE {}",
        json!({"cases":6,"guestComponents":1,"gateComponent":false,"wholeAC7":false,"wholeCostQualification":false,"productionEnablement":false})
    );
}

// Read ONLY the node's original, closed public diagnostic projection. Do not
// recover private JS text or reinterpret known resource/stop failures as cleanup.
fn public_unknown_failure(error: &latent_core::PlatformError) -> Value {
    use latent_core::error::GuestTrapKind;
    assert_eq!(
        error.details.len(),
        2,
        "extra/ambiguous original failure diagnostics"
    );
    let mut kinds = error
        .details
        .iter()
        .filter(|d| d.kind == "activation.guest-trap-kind");
    let selected = kinds.next().expect("original public trap kind required");
    assert!(kinds.next().is_none());
    assert!(selected
        .fields
        .keys()
        .all(|key| matches!(key.as_str(), "kind" | "phase")));
    let kind = GuestTrapKind::from_wire_name(selected.fields.get("kind").unwrap()).unwrap();
    assert!(
        matches!(
            kind,
            GuestTrapKind::RuntimeError | GuestTrapKind::UnreachableCode
        ),
        "known/non-matching trap classification: {}",
        kind.wire_name()
    );
    let mut classes = error
        .details
        .iter()
        .filter(|d| d.kind == "activation.guest-trap");
    let original = classes.next().expect("original public trap class required");
    assert!(classes.next().is_none());
    let code = original.fields.get("code").unwrap();
    let phase = selected.fields.get("phase").map(String::as_str);
    match kind {
        GuestTrapKind::RuntimeError => {
            assert_eq!(code, "guest-runtime-error");
            assert!(phase.is_none() || phase == Some("call-and-postreturn"));
            assert_eq!(error.message, "guest execution failed");
        }
        GuestTrapKind::UnreachableCode => {
            assert_eq!(code, "guest-trap");
            assert!(phase.is_none());
            assert_eq!(error.message, "guest trapped: unreachable-code");
        }
        _ => unreachable!(),
    }
    json!({"code":code,"kind":kind.wire_name(),"phase":phase,"message":error.message})
}

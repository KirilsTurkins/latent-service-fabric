//! Signed V5 runtime components through the existing local node composition.
//! These tests establish shared-host ownership, not a language profile claim.
use super::{fixture::Fixture, packages};
use latent_activation::ActivationOutcome;
use latent_artifacts::ArtifactRepository;
use latent_core::diagnostic::{ActivationDiagnostic, DiagnosticReason, DiagnosticStage};
use latent_core::{activation_runtime::RuntimeLimits, ActivationId, PlatformErrorCode, TenantId};
use latent_executor::ExecutionBackend;
use std::{future::Future, pin::Pin, sync::atomic::Ordering, task::Poll, time::Duration};

#[path = "runtime/component.rs"]
mod component;
#[path = "../guest_sdk/package.rs"]
pub(super) mod package;
#[path = "../../../latent-signing/tests/build_provenance/support.rs"]
#[allow(dead_code)]
pub(super) mod provenance;
#[path = "../generic_backend/support.rs"]
#[allow(dead_code)]
pub(super) mod support;

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "runtime/typescript.rs"]
mod typescript;

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "runtime/go.rs"]
mod go;

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "runtime/native_threads.rs"]
mod native_threads;

fn limits() -> RuntimeLimits {
    // Deliberately small test ceilings; these are not a language/product default.
    RuntimeLimits {
        tasks: 2,
        executors: 2,
        queued_work: 2,
        waits: 2,
        timers: 2,
        results: 2,
        native_owners: 2,
    }
}
async fn configured(root: &std::path::Path, cells: u32) -> Fixture {
    configured_with_wait_ceiling(root, cells, 5000).await
}
async fn configured_with_wait_ceiling(
    root: &std::path::Path,
    cells: u32,
    call_wall_millis: u64,
) -> Fixture {
    let caller = packages::activation_runtime(component::bytes());
    signed_runtime(
        root,
        cells,
        call_wall_millis,
        caller,
        include_bytes!("runtime/component.rs"),
    )
    .await
}

async fn signed_runtime(
    root: &std::path::Path,
    cells: u32,
    call_wall_millis: u64,
    caller: latent_packaging::PackageBundle,
    source_input: &[u8],
) -> Fixture {
    signed_runtime_with_limits(
        root,
        cells,
        call_wall_millis,
        caller,
        source_input,
        limits(),
    )
    .await
}

async fn signed_runtime_with_limits(
    root: &std::path::Path,
    cells: u32,
    call_wall_millis: u64,
    caller: latent_packaging::PackageBundle,
    source_input: &[u8],
    runtime_limits: RuntimeLimits,
) -> Fixture {
    let callee = packages::callee(42);
    let signers = package::Signers::new(latent_signing::PROVENANCE_BUILD_TYPE);
    let mut uploads = vec![];
    for bundle in [&caller, &callee] {
        let mut observation = provenance::observation();
        observation.source.repository =
            "https://github.com/KirilsTurkins/latent-service-fabric".into();
        observation.component_digest = bundle.layout().component_release().unwrap().0;
        observation.component_size = bundle.blob("component.wasm").unwrap().len() as u64;
        // Bind the actual checked-in binary builder and frozen runtime WIT.
        let mut source = source_input.to_vec();
        source.extend_from_slice(include_bytes!(
            "../../../../wit/platform/activation-runtime/package.wit"
        ));
        observation.source.snapshot_digest =
            latent_artifacts::package::artifact_blob_digest(&source).into_string();
        let material = observation
            .materials
            .iter_mut()
            .find(|material| material.name == "source-snapshot")
            .unwrap();
        material.digest = observation.source.snapshot_digest.clone();
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
    Fixture::with_activation_runtime(
        cells,
        (catalog, caller, callee),
        runtime_limits,
        call_wall_millis,
    )
    .await
}

/// The normal suite does not build a toolchain. Run the explicit compiler
/// qualification first; a missing fixture is a failure when this is selected.
#[tokio::test]
#[ignore = "requires the pinned Java activation fiber component and explicit java profile"]
async fn signed_java_threads_spin_join_and_thread_local_use_real_activation_fibers() {
    signed_java_fiber_fixture(
        "LSF_JAVA_FIBER_FIXTURE",
        include_bytes!("../../../../sdk/java-guest/fibers/conformance/Capsule.java"),
        "java-fibers",
    )
    .await;
}

#[tokio::test]
#[ignore = "requires the pinned ordinary CompletableFuture component and explicit java profile"]
async fn signed_java_completable_futures_use_default_activation_executor() {
    signed_java_fiber_fixture(
        "LSF_JAVA_COMPLETABLE_FIXTURE",
        include_bytes!("../../../../sdk/java-guest/fibers/conformance/completable/Capsule.java"),
        "java-completable",
    )
    .await;
}

#[tokio::test]
#[ignore = "requires the pinned Java fiber I/O component and explicit I/O profile"]
async fn signed_java_host_imports_suspend_only_their_owned_callers() {
    signed_java_fiber_fixture(
        "LSF_JAVA_FIBER_IO_FIXTURE",
        include_bytes!("../../../../sdk/java-guest/fibers/conformance/fiber-io/Capsule.java"),
        "java-fiber-io",
    )
    .await;
}

#[tokio::test]
#[ignore = "requires two normally captured Java libraries and the explicit fiber I/O profile"]
async fn signed_java_published_libraries_use_unchanged_default_workers() {
    if std::env::var_os("LSF_JAVA_SCHEDULED_LIBRARIES_FIXTURE").is_some() {
        assert!(std::env::var_os("LSF_JAVA_WORKER_LIBRARIES_FIXTURE").is_none());
        signed_java_fiber_fixture(
            "LSF_JAVA_SCHEDULED_LIBRARIES_FIXTURE",
            include_bytes!(
                "../../../../sdk/java-guest/fibers/conformance/scheduled-library/Capsule.java"
            ),
            "java-scheduled-libraries",
        )
        .await;
        return;
    }
    signed_java_fiber_fixture(
        "LSF_JAVA_WORKER_LIBRARIES_FIXTURE",
        include_bytes!(
            "../../../../sdk/java-guest/fibers/conformance/worker-libraries/Capsule.java"
        ),
        "java-worker-libraries",
    )
    .await;
}

#[tokio::test]
#[ignore = "requires the pinned standard Timer component and explicit java profile"]
async fn signed_java_standard_timers_recur_cancel_and_drain_owned_workers() {
    signed_java_fiber_fixture(
        "LSF_JAVA_TIMER_FIXTURE",
        include_bytes!("../../../../sdk/java-guest/fibers/conformance/timers/Capsule.java"),
        "java-timers",
    )
    .await;
}

#[tokio::test]
#[ignore = "requires the pinned ordinary shutdownNow CompletableFuture component"]
async fn signed_java_shutdown_now_withdraws_only_unstarted_callbacks() {
    signed_java_fiber_fixture(
        "LSF_JAVA_SHUTDOWN_NOW_FIXTURE",
        include_bytes!("../../../../sdk/java-guest/fibers/conformance/shutdown-now/Capsule.java"),
        "java-shutdown-now",
    )
    .await;
}

#[tokio::test]
#[ignore = "requires the pinned normal FutureTask queue component and its one-Result fixture"]
async fn signed_java_future_tasks_retain_result_ownership_across_queue_copies() {
    signed_java_fiber_fixture(
        "LSF_JAVA_FUTURE_QUEUE_FIXTURE",
        include_bytes!("../../../../sdk/java-guest/fibers/conformance/future-queue/Capsule.java"),
        "java-future-queue",
    )
    .await;
}

async fn signed_java_fiber_fixture(variable: &str, expected_source: &[u8], name: &str) {
    assert_eq!(
        std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(),
        Ok("java")
    );
    let prepared = std::path::PathBuf::from(
        std::env::var_os(variable).expect("prepare the pinned Java fiber fixture"),
    );
    if matches!(
        name,
        "java-scheduled-libraries" | "java-shutdown-now" | "java-future-queue"
    ) {
        assert!(prepared.is_absolute());
        for (path, maximum) in [
            ("src/Capsule.java", expected_source.len() as u64),
            ("FIBERS-COMPILE.json", 8 * 1024 * 1024),
            ("build/component.wasm", 64 * 1024 * 1024),
            ("wit/service.wit", 1024 * 1024),
        ] {
            let metadata = std::fs::symlink_metadata(prepared.join(path)).unwrap();
            assert!(metadata.file_type().is_file() && !metadata.file_type().is_symlink());
            assert!(metadata.len() <= maximum);
        }
    }
    let source = std::fs::read(prepared.join("src/Capsule.java")).unwrap();
    assert_eq!(source.as_slice(), expected_source);
    let record: serde_json::Value =
        serde_json::from_slice(&std::fs::read(prepared.join("FIBERS-COMPILE.json")).unwrap())
            .unwrap();
    let profile = if name == "java-fiber-io" || name == "java-worker-libraries" {
        assert_eq!(
            record["fixture"],
            if name == "java-fiber-io" {
                "fiber-io"
            } else {
                "worker-libraries"
            }
        );
        assert_eq!(
            record["referenceKind"],
            "private-runtime-wait-reference-using-JDK-threads"
        );
        "teavm-activation-fibers-io-v1"
    } else {
        "teavm-activation-fibers-v1"
    };
    assert_eq!(record["profile"], profile);
    if name == "java-completable" {
        assert_eq!(record["fixture"], "completable");
    }
    if name == "java-timers" {
        assert_eq!(record["fixture"], "timers");
        assert_eq!(record["status"], "component-built-unqualified");
        assert_eq!(
            record["standardTimerSource"]["status"],
            "SDK-source-controls-passed"
        );
        assert_eq!(record["standardTimerSource"]["iterations"], 3);
        assert_eq!(
            record["standardTimerModel"]["status"],
            "actual-locked-classlib-model-passed"
        );
        assert_eq!(record["standardTimerModel"]["models"], 3);
        assert_eq!(
            record["standardTimerSource"]["componentExecutionPerformed"],
            false
        );
        assert_eq!(
            record["standardTimerSource"]["actualGuestBindingsUsed"],
            false
        );
    }
    if name == "java-scheduled-libraries" {
        assert_eq!(record["fixture"], "scheduled-library");
        assert_eq!(record["status"], "component-built-unqualified");
        assert_eq!(
            record["scheduledSource"]["status"],
            "SDK-source-controls-passed"
        );
        assert_eq!(
            record["scheduledSource"]["componentExecutionPerformed"],
            false
        );
        assert_eq!(record["scheduledSource"]["actualGuestBindingsUsed"], false);
        assert_eq!(
            record["scheduledModel"]["status"],
            "actual-locked-classlib-model-passed"
        );
        assert_eq!(record["scheduledModel"]["models"], 8);
        assert_eq!(record["scheduledModel"]["constructedIdentities"], 5);
        assert_eq!(record["scheduledModel"]["actualGeneratedCallbacks"], 3);
        assert_eq!(
            record["scheduledModel"]["portOrApplicationClassesInitialized"],
            false
        );
        assert_eq!(record["scheduledModel"]["actualGuestBindingsUsed"], false);
    }
    let shutdown_now = name == "java-shutdown-now";
    let future_queue = name == "java-future-queue";
    if shutdown_now {
        assert_eq!(record["fixture"], "shutdown-now");
        assert_eq!(record["status"], "component-built-unqualified");
        assert_eq!(
            record["shutdownNowSource"]["status"],
            "SDK-source-controls-passed"
        );
        assert_eq!(record["shutdownNowSource"]["ownershipChecks"], 53);
        assert_eq!(
            record["shutdownNowSource"]["componentExecutionPerformed"],
            false
        );
        assert_eq!(
            record["shutdownNowSource"]["actualGuestBindingsUsed"],
            false
        );
        assert_eq!(
            record["completableModel"]["status"],
            "actual-locked-classlib-model-passed"
        );
    }
    if future_queue {
        assert_eq!(record["fixture"], "future-queue");
        assert_eq!(record["status"], "component-built-unqualified");
        assert_eq!(
            record["futureQueueSource"]["status"],
            "SDK-source-controls-passed"
        );
        assert_eq!(record["futureQueueSource"]["ownershipChecks"], 48);
        assert_eq!(
            record["futureQueueSource"]["componentExecutionPerformed"],
            false
        );
        assert_eq!(
            record["futureQueueSource"]["actualGuestBindingsUsed"],
            false
        );
        assert_eq!(
            record["scheduledModel"]["status"],
            "actual-locked-classlib-model-passed"
        );
        assert_eq!(record["scheduledModel"]["models"], 8);
    }
    let bytes = std::fs::read(prepared.join("build/component.wasm")).unwrap();
    assert_eq!(
        record["componentDigest"],
        latent_artifacts::package::artifact_blob_digest(&bytes).as_str()
    );
    assert_eq!(
        record["sourceDigest"],
        latent_artifacts::package::artifact_blob_digest(&source).as_str()
    );
    let scheduled = name == "java-scheduled-libraries";
    assert_eq!(
        record["reference"].as_array().unwrap().len(),
        if scheduled || shutdown_now || future_queue {
            1
        } else {
            3
        }
    );
    for control in record["reference"].as_array().unwrap() {
        if scheduled {
            assert_eq!(
                control["modes"],
                serde_json::json!([0, 1, 2, 3, 4, 5, 6, 7])
            );
            assert_eq!(
                control["results"],
                serde_json::json!([42, 42, 42, 42, 42, 42, 42, 42])
            );
        } else {
            assert_eq!(control["modes"], serde_json::json!([0, 1, 2, 3]));
            assert_eq!(
                control["results"],
                if future_queue {
                    serde_json::json!([41, 42, 42, 42])
                } else {
                    serde_json::json!([42, 42, 42, 42])
                }
            );
        }
    }
    let mut provenance_source = source.clone();
    if shutdown_now || future_queue {
        provenance_source
            .extend_from_slice(&std::fs::read(prepared.join("FIBERS-COMPILE.json")).unwrap());
    }
    if name == "java-worker-libraries" || scheduled {
        assert_eq!(record["libraries"]["sourceModified"], false);
        assert_eq!(record["libraries"]["externalExecutorInjected"], false);
        assert_eq!(
            record["libraries"]["originalLibraries"],
            serde_json::json!({
                "org.apache.commons:commons-lang3:3.14.0":
                    "sha256:7b96bf3ee68949abb5bc465559ac270e0551596fa34523fddf890ec418dde13c",
                "cn.hutool:hutool-core:5.8.40":
                    "sha256:d6bedc908cba480cd12dbe6f8422fa60c0da31030b58a68c3c077f555fc0cbbc"
            })
        );
        assert_eq!(
            record["libraries"]["selectedJars"]
                .as_array()
                .unwrap()
                .len(),
            2
        );
        // Include the tested normal capture, archive selection and compiler
        // identities in this signed fixture's source observation as well.
        provenance_source
            .extend_from_slice(&std::fs::read(prepared.join("FIBERS-COMPILE.json")).unwrap());
    }
    let wit = std::fs::read_to_string(prepared.join("wit/service.wit")).unwrap();
    let caller = packages::java_activation_runtime(bytes, &wit);
    let release = packages::release(&caller);
    let root = tempfile::tempdir().unwrap();
    // Declared fixture ceiling: root plus four independent pool workers, three
    // executors, and the pending batches/rendezvous. No product default is added.
    let java_limits = RuntimeLimits {
        tasks: 5,
        executors: 3,
        queued_work: 8,
        waits: 8,
        timers: 2,
        results: if future_queue { 1 } else { 8 },
        native_owners: 2,
    };
    let f = signed_runtime_with_limits(
        root.path(),
        1,
        120_000,
        caller,
        &provenance_source,
        java_limits,
    )
    .await;
    // Qualify guest execution separately from cold native compilation. Prepare
    // this exact signed publication through the ordinary repository boundary;
    // no activation, guest Store or capability session is started here. Each
    // subsequent activation still performs its normal currentness/grant checks
    // and retains the original 120-second, fuel and memory ceilings.
    let preparation_started = std::time::Instant::now();
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
    .expect("bounded signed Java preparation setup")
    .expect("prepare the exact signed Java publication");
    let prepared_owner = f.backend.materialize_ready(ready).unwrap();
    drop(prepared_owner);
    f.idle().await;
    assert_eq!(f.backend.resource_snapshot().stores_created, 0);
    eprintln!(
        "{profile} signed-preparation-setup-micros={} stores-created=0 guest-activations=0",
        preparation_started.elapsed().as_micros()
    );
    for iteration in 0..if shutdown_now || future_queue {
        1
    } else if scheduled {
        2
    } else {
        3
    } {
        for mode in 0..if scheduled { 8 } else { 4 } {
            let requested_id = format!("{name}-{iteration}-{mode}");
            let stores_before = f.backend.resource_snapshot().stores_created;
            let actual = f
                .manager
                .start(f.request(&requested_id, mode))
                .unwrap()
                .await;
            if matches!(
                name,
                "java-fibers"
                    | "java-worker-libraries"
                    | "java-scheduled-libraries"
                    | "java-shutdown-now"
                    | "java-future-queue"
            ) {
                assert_eq!(actual.activation_id.0, requested_id);
            }
            let receipt = success(actual);
            assert_eq!(
                serde_json::from_slice::<Vec<u32>>(&receipt.output).unwrap(),
                [42]
            );
            assert!(receipt.consumption.cpu_fuel > 0);
            assert!(receipt.consumption.peak_memory_bytes <= packages::budget().memory_bytes);
            eprintln!(
                "{profile} iteration={iteration} mode={mode} consumption={:?}",
                receipt.consumption
            );
            f.idle().await;
            if matches!(
                name,
                "java-fibers"
                    | "java-worker-libraries"
                    | "java-scheduled-libraries"
                    | "java-shutdown-now"
                    | "java-future-queue"
            ) {
                let runtime = f.backend.resource_snapshot();
                let broker = f.broker.snapshot();
                assert!(runtime.stores_created > stores_before);
                eprintln!(
                    "LSF_JAVA_RETAINED={}",
                    serde_json::json!({
                        "activationId": requested_id, "iteration": iteration, "mode": mode,
                        "value": 42, "cpuFuel": receipt.consumption.cpu_fuel,
                        "reportedPeakMemoryBytes": receipt.consumption.peak_memory_bytes,
                        "storesBefore": stores_before, "storesCreated": runtime.stores_created,
                        "liveStores": runtime.live_stores,
                        "activeReservations": f.backend.active_instance_reservations(),
                        "brokerCalls": broker.calls, "brokerSessions": broker.sessions,
                        "brokerHandles": broker.handles, "brokerResults": broker.results,
                        "brokerBufferBytes": broker.buffer_bytes
                    })
                );
            }
        }
    }
}
fn success(receipt: latent_node::ActivationReceipt) -> latent_activation::ActivationSuccess {
    let ActivationOutcome::Succeeded(success) = receipt.outcome else {
        panic!("{}: {:?}", receipt.activation_id.0, receipt.outcome)
    };
    success
}
fn value(receipt: latent_node::ActivationReceipt) -> u32 {
    serde_json::from_slice::<Vec<u32>>(&success(receipt).output).unwrap()[0]
}
fn failure(receipt: latent_node::ActivationReceipt) -> latent_core::PlatformError {
    let ActivationOutcome::Failed { error, .. } = receipt.outcome else {
        panic!("{:?}", receipt.outcome)
    };
    error
}
async fn pending_timer(
    mut invocation: Pin<&mut impl Future<Output = latent_node::ActivationReceipt>>,
    f: &Fixture,
) {
    tokio::time::timeout(
        Duration::from_secs(5),
        std::future::poll_fn(|context| match invocation.as_mut().poll(context) {
            Poll::Ready(receipt) => panic!(
                "timer should be parked at the barrier: {:?}",
                receipt.outcome
            ),
            Poll::Pending
                if f.read_wait.active.load(Ordering::Acquire) != 0
                    && f.backend.resource_snapshot().live_stores == 1
                    && f.broker.snapshot().calls != 0 =>
            {
                Poll::Ready(())
            }
            Poll::Pending => Poll::Pending,
        }),
    )
    .await
    .expect("observe a real Store-owned pending timer before cancellation");
}

#[tokio::test]
async fn completed_fixed_results_release_original_calls_before_the_next_import() {
    let root = tempfile::tempdir().unwrap();
    let f = configured(root.path(), 1).await;
    // This fixture requires the ordinary installed scalar profile's 100-fuel
    // charge for every runtime operation. Omitting it from the bridge denies
    // the initial register, before any logical owner or completed result.
    // The existing fixture installs the unchanged broker default. This ceiling
    // limits simultaneous accepted calls, not completed lifetime operation count.
    assert_eq!(f.maximum_calls_per_session, 16);
    assert!(usize::try_from(component::COMPLETED_CYCLES).unwrap() > f.maximum_calls_per_session);
    for (mode, per_cycle) in [(26, 3_u64), (27, 5_u64), (32, 2_u64)] {
        let id = format!("fixed-completion-{mode}");
        let receipt = success(f.manager.start(f.request(&id, mode)).unwrap().await);
        assert_eq!(
            serde_json::from_slice::<Vec<u32>>(&receipt.output).unwrap(),
            [42]
        );
        assert!(receipt.consumption.peak_memory_bytes <= packages::budget().memory_bytes);
        assert_eq!(
            f.backend
                .take_invocation_timing(&ActivationId(id))
                .unwrap()
                .host_call_count,
            u64::from(component::COMPLETED_CYCLES) * per_cycle + 3,
            "every original import executes exactly once, including root registration/settlement/close"
        );
        f.idle().await;
        assert_eq!(f.read_wait.active.load(Ordering::Acquire), 0);
    }
    let child_failures = f.observations.child_failures.snapshot();
    assert!(child_failures.records.is_empty());
    assert!(!child_failures.incomplete);
}

#[tokio::test]
async fn pending_fixed_results_retain_only_actual_original_calls_and_drop_cleanly() {
    let root = tempfile::tempdir().unwrap();
    let f = configured(root.path(), 1).await;
    assert_eq!(
        value(f.manager.start(f.request("fixed-warm", 0)).unwrap().await),
        42
    );
    f.idle().await;
    for cancel in [true, false] {
        let id = ActivationId(format!("fixed-pending-{cancel}"));
        let mut invocation = Box::pin(f.manager.start(f.request(&id.0, 28)).unwrap());
        pending_timer(invocation.as_mut(), &f).await;
        let broker = f.broker.snapshot();
        assert_eq!(
            broker.calls, 1,
            "only the actual pending wait remains charged"
        );
        assert_eq!(broker.results, 1);
        assert_eq!(broker.buffer_bytes, 128);
        assert_eq!(f.backend.resource_snapshot().live_stores, 1);
        assert_eq!(f.quotas.usage().unwrap().active_activations, 1);
        if cancel {
            f.manager
                .cancel_for(
                    &TenantId("tenant-a".into()),
                    &id,
                    "fixed-result-owner-cancel",
                )
                .unwrap();
            assert_eq!(failure(invocation.await).code, PlatformErrorCode::Cancelled);
        } else {
            drop(invocation);
        }
        f.idle().await;
        assert_eq!(f.read_wait.active.load(Ordering::Acquire), 0);
        let fresh = f
            .manager
            .start(f.request(&format!("fixed-fresh-{cancel}"), 0))
            .unwrap()
            .await;
        if cancel {
            assert_eq!(value(fresh), 42);
        } else {
            // Dropping the outer manager future never publishes the backend's
            // reusable cleanup proof. Physical result/call/Store owners are
            // reclaimed above, but the existing scheduler must quarantine the
            // execution cell instead of inferring permission to reuse it.
            let error = failure(fresh);
            assert_eq!(error.code, PlatformErrorCode::Unavailable);
            assert_eq!(error.details.len(), 2);
            assert_eq!(error.details[0].kind, "scheduler.limit");
            assert_eq!(error.details[0].fields.len(), 1);
            assert_eq!(
                error.details[0].fields.get("reason").map(String::as_str),
                Some("all-cells-quarantined")
            );
            assert_eq!(
                error
                    .details
                    .iter()
                    .filter(|detail| detail.kind == "scheduler.limit")
                    .count(),
                1
            );
            let diagnostic = latent_core::diagnostic::ActivationDiagnostic::new(
                latent_core::diagnostic::DiagnosticStage::Queue,
                latent_core::diagnostic::DiagnosticReason::QueuePressure,
            );
            assert_eq!(error.details[1], diagnostic.detail());
            assert_eq!(
                latent_core::diagnostic::ActivationDiagnostic::from_error(&error),
                Some(diagnostic)
            );
            assert_eq!(error.details[1].kind, "activation.diagnostic.v1");
            assert_eq!(
                error.details[1].fields,
                latent_core::Metadata::from([
                    ("reason".into(), "9".into()),
                    ("stage".into(), "2".into()),
                ])
            );
        }
        f.idle().await;
    }
}

#[tokio::test]
async fn malformed_fixed_result_destinations_reclaim_original_calls() {
    let root = tempfile::tempdir().unwrap();
    let f = configured(root.path(), 1).await;
    for (mode, original_calls) in [(29, 1), (30, 0), (31, 2)] {
        let id = format!("fixed-destination-{mode}");
        assert_eq!(
            failure(f.manager.start(f.request(&id, mode)).unwrap().await).code,
            PlatformErrorCode::GuestTrap
        );
        assert_eq!(
            f.backend
                .take_invocation_timing(&ActivationId(id))
                .unwrap()
                .host_call_count,
            original_calls
        );
        f.idle().await;
        assert_eq!(f.read_wait.active.load(Ordering::Acquire), 0);
        assert_eq!(
            value(
                f.manager
                    .start(f.request(&format!("fixed-after-bad-{mode}"), 0))
                    .unwrap()
                    .await
            ),
            42
        );
        f.idle().await;
    }
}

#[tokio::test]
async fn signed_runtime_limits_closing_and_generation_fences_use_normal_node_admission() {
    let root = tempfile::tempdir().unwrap();
    let f = configured(root.path(), 1).await;
    for mode in [0, 4, 5, 6, 16, 17, 18, 19, 20, 21, 22] {
        assert_eq!(
            value(
                f.manager
                    .start(f.request(&format!("runtime-{mode}"), mode))
                    .unwrap()
                    .await
            ),
            42
        );
        f.idle().await;
    }
    let first = value(
        f.manager
            .start(f.request("first-generation", 14))
            .unwrap()
            .await,
    );
    f.idle().await;
    let exhausted = f
        .manager
        .start(f.request("linear-plus-native-memory", 24))
        .unwrap()
        .await;
    assert_eq!(
        failure(exhausted).code,
        PlatformErrorCode::ResourceExhausted
    );
    f.idle().await;
    // Compare the same scalar result with equal-width original context IDs.
    let direct_request = f.request("lazy-no-concurrency", 15);
    let owned_request = f.request("native-runtime-work", 0);
    let mut native_exhausted = f.request("native-runtime-deny", 23);
    let id_widths = [&direct_request, &owned_request, &native_exhausted]
        .map(|request| request.activation_id.as_ref().unwrap().0.len());
    assert_eq!(id_widths, [19; 3]);
    let direct = success(f.manager.start(direct_request).unwrap().await);
    // The full-grant mode21 above catches the exact third-native-owner Limit.
    assert_eq!(direct.output.as_ref(), b"[42]");
    f.idle().await;
    let owned = success(f.manager.start(owned_request).unwrap().await);
    assert_eq!(owned.output.as_ref(), direct.output.as_ref());
    f.idle().await;
    // Mode15 never calls an import. Its lazy-only ceiling cannot fund the
    // newly paid native import transport, before a WIT refusal can be caught.
    // Keep that outer failure distinct from mode21's successful API catch.
    native_exhausted.budget.memory_bytes = direct.consumption.peak_memory_bytes;
    let ActivationOutcome::Failed {
        error, consumption, ..
    } = f.manager.start(native_exhausted).unwrap().await.outcome
    else {
        panic!("lazy budget must refuse native transport")
    };
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    let diagnostic = ActivationDiagnostic::from_error(&error).unwrap();
    assert_eq!(
        (diagnostic.stage, diagnostic.reason),
        (
            DiagnosticStage::Execution,
            DiagnosticReason::GuestMemoryExhausted
        )
    );
    assert_eq!(
        consumption.peak_memory_bytes,
        direct.consumption.peak_memory_bytes
    );
    f.idle().await;
    let second = value(
        f.manager
            .start(f.request("second-generation", 14))
            .unwrap()
            .await,
    );
    assert_ne!(first, second);
    f.idle().await;
    assert!(owned.consumption.peak_memory_bytes > direct.consumption.peak_memory_bytes);
    assert!(owned.consumption.peak_memory_bytes <= packages::budget().memory_bytes);
    eprintln!(
        "activation-owned-v1 direct={:?}; runtime={:?}",
        direct.consumption, owned.consumption
    );
    f.idle().await;
}

#[tokio::test]
async fn root_result_idle_worker_and_trap_never_skip_runtime_retirement() {
    let root = tempfile::tempdir().unwrap();
    let f = configured(root.path(), 1).await;
    for mode in [1, 2, 3] {
        let error = failure(
            f.manager
                .start(f.request(&format!("unsettled-{mode}"), mode))
                .unwrap()
                .await,
        );
        assert_eq!(error.code, PlatformErrorCode::GuestTrap);
        if mode != 3 {
            assert!(
                error.message.contains("runtime-lifecycle-unproven"),
                "{error:?}"
            );
        }
        f.idle().await;
        assert_eq!(
            value(
                f.manager
                    .start(f.request(&format!("fresh-after-{mode}"), 0))
                    .unwrap()
                    .await
            ),
            42
        );
        f.idle().await;
    }
}

#[tokio::test]
async fn canonical_timer_allows_sibling_work_and_bounds_recurrence_cancellation_and_storms() {
    let root = tempfile::tempdir().unwrap();
    let f = configured(root.path(), 1).await;
    for mode in [8, 9, 10, 12, 13] {
        assert_eq!(
            value(
                f.manager
                    .start(f.request(&format!("timer-{mode}"), mode))
                    .unwrap()
                    .await
            ),
            42
        );
        f.idle().await;
        assert_eq!(f.read_wait.active.load(Ordering::Acquire), 0);
    }
}

#[tokio::test]
async fn narrower_timer_policy_deadline_preserves_root_and_allows_owner_settlement() {
    let root = tempfile::tempdir().unwrap();
    let f = configured_with_wait_ceiling(root.path(), 1, 25).await;
    assert_eq!(
        value(
            f.manager
                .start(f.request("narrower-policy-deadline", 25))
                .unwrap()
                .await
        ),
        42
    );
    f.idle().await;
    assert_eq!(f.read_wait.active.load(Ordering::Acquire), 0);
}

#[tokio::test]
async fn policy_revocation_at_real_timer_barrier_stops_original_work_and_reclaims_owners() {
    use latent_policy::capability::{MutationRequest, RecordKind};
    use std::time::Instant;
    let root = tempfile::tempdir().unwrap();
    let f = configured(root.path(), 1).await;
    let mut invocation = Box::pin(
        f.manager
            .start(f.request("revoke-parked-runtime", 11))
            .unwrap(),
    );
    pending_timer(invocation.as_mut(), &f).await;
    let record = f
        .policies
        .get(
            "tenant-a",
            RecordKind::Policy,
            "sdk-runtime-policy-0",
            65536,
            Instant::now() + Duration::from_secs(2),
        )
        .unwrap()
        .value()
        .as_ref()
        .unwrap()
        .clone();
    f.policies
        .mutate(
            MutationRequest {
                tenant: "tenant-a",
                actor: "runtime-test-operator",
                id: "sdk-runtime-policy-0",
                kind: RecordKind::Policy,
                operation_id: "revoke-runtime-policy",
                expected_revision: record.revision,
                document: None,
            },
            Instant::now() + Duration::from_secs(2),
            |_| Ok(()),
        )
        .unwrap();
    assert_eq!(failure(invocation.await).code, PlatformErrorCode::Cancelled);
    f.idle().await;
    assert_eq!(f.read_wait.active.load(Ordering::Acquire), 0);
    // Declared required imports still need fresh admission even on the lazy
    // path. Revoking the grant cannot be bypassed by omitting an actual call.
    assert_eq!(
        failure(
            f.manager
                .start(f.request("fresh-after-revocation", 15))
                .unwrap()
                .await
        )
        .code,
        PlatformErrorCode::PermissionDenied
    );
    let mut fresh = f.request("unrelated-fresh-after-revocation", 0);
    fresh.target.service = latent_core::ServiceId("callee".into());
    fresh.target.contract = latent_core::ContractId(super::component::CALLEE.into());
    fresh.target.function = latent_core::FunctionId("answer".into());
    fresh.input = b"[]".to_vec();
    assert_eq!(value(f.manager.start(fresh).unwrap().await), 42);
    f.idle().await;
}

#[tokio::test]
async fn cancellation_at_actual_timer_barrier_reclaims_original_store_and_cell() {
    let root = tempfile::tempdir().unwrap();
    let f = configured(root.path(), 1).await;
    let id = ActivationId("cancel-parked-runtime".into());
    let mut invocation = Box::pin(f.manager.start(f.request(id.0.as_str(), 11)).unwrap());
    pending_timer(invocation.as_mut(), &f).await;
    assert_eq!(f.quotas.usage().unwrap().active_activations, 1);
    f.manager
        .cancel_for(&TenantId("tenant-a".into()), &id, "runtime-fixture-cancel")
        .unwrap();
    assert_eq!(failure(invocation.await).code, PlatformErrorCode::Cancelled);
    f.idle().await;
    assert_eq!(f.read_wait.active.load(Ordering::Acquire), 0);
    assert_eq!(
        value(
            f.manager
                .start(f.request("fresh-after-timer-cancel", 0))
                .unwrap()
                .await
        ),
        42
    );
    f.idle().await;
}

#[tokio::test]
async fn root_deadline_does_not_complete_long_timer_and_cpu_loop_remains_contained() {
    let root = tempfile::tempdir().unwrap();
    let f = configured(root.path(), 1).await;
    assert_eq!(
        value(f.manager.start(f.request("warm-runtime", 0)).unwrap().await),
        42
    );
    f.idle().await;
    let mut deadline = f.request("root-deadline", 11);
    deadline.budget.wall_time_limit_millis = Some(100);
    assert_eq!(
        failure(f.manager.start(deadline).unwrap().await).code,
        PlatformErrorCode::DeadlineExceeded
    );
    f.idle().await;
    let mut cpu = f.request("runtime-cpu-loop", 7);
    cpu.budget.cpu_fuel = 50_000;
    assert_eq!(
        failure(f.manager.start(cpu).unwrap().await).code,
        PlatformErrorCode::ResourceExhausted
    );
    f.idle().await;
    assert_eq!(
        value(
            f.manager
                .start(f.request("fresh-after-containment", 0))
                .unwrap()
                .await
        ),
        42
    );
    f.idle().await;
}

mod owned_timer {
    use super::super::fixture::ObservedReadWait;
    use latent_core::{
        ActivationBudget, BudgetProfile, ClockSample, EffectiveActivationBudget, PlatformErrorCode,
        ResourceBudget,
    };
    use latent_executor::{OwnedPreparationWait, PreparationReadWait};
    use std::{
        future::{pending, Future},
        mem::size_of,
        pin::Pin,
        sync::{
            atomic::{AtomicU64, AtomicUsize, Ordering},
            Arc,
        },
        task::{Context, Poll, Waker},
        time::{Duration, Instant},
    };

    fn original(memory: u64) -> ActivationBudget {
        let limits = ResourceBudget {
            cpu_fuel: 1_000_000,
            memory_bytes: memory,
            wall_time_limit_millis: Some(30_000),
            child_calls: 0,
            outbound_requests: 0,
            state_read_bytes: 0,
            state_write_bytes: 0,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            log_bytes: 0,
            effect_count: 0,
        };
        let grant = EffectiveActivationBudget::admit_profile_at(
            BudgetProfile::Phase3,
            &limits,
            &limits,
            &limits,
            None,
            ClockSample::new(1000, Instant::now()),
        )
        .unwrap();
        ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap()
    }

    struct PendingOwned {
        budget: ActivationBudget,
        drops: Arc<AtomicUsize>,
        payload: [u8; 32],
    }
    impl Future for PendingOwned {
        type Output = ();

        fn poll(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<()> {
            assert_eq!(self.payload[0], 42);
            Poll::Pending
        }
    }
    impl Drop for PendingOwned {
        fn drop(&mut self) {
            // This actual destructor must run while its complete Box charge is
            // live. The frozen by-value field order supplies the subsequent
            // Box-deallocation-before-reservation-drop source witness.
            assert_eq!(self.budget.host_memory_bytes(), size_of::<Self>() as u64);
            self.drops.fetch_add(1, Ordering::SeqCst);
        }
    }

    #[test]
    fn original_budget_refuses_before_factory_and_preserves_foreign_capacity() {
        let budget = original(4096);
        let foreign = original(4096);
        let foreign_hold = foreign.reserve_host_memory(19).unwrap();
        let full = budget.reserve_host_memory(4096).unwrap();
        let calls = AtomicUsize::new(0);
        let drops = Arc::new(AtomicUsize::new(0));
        let result = OwnedPreparationWait::try_boxed(&budget, || {
            calls.fetch_add(1, Ordering::SeqCst);
            PendingOwned {
                budget: budget.clone(),
                drops: Arc::clone(&drops),
                payload: [42; 32],
            }
        });
        assert!(matches!(
            result,
            Err(ref error) if error.code == PlatformErrorCode::ResourceExhausted
        ));
        assert_eq!(calls.load(Ordering::SeqCst), 0);
        assert_eq!(drops.load(Ordering::SeqCst), 0);
        assert_eq!(budget.host_memory_bytes(), 4096);
        assert_eq!(foreign.host_memory_bytes(), 19);
        drop(full);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(foreign.host_memory_bytes(), 19);
        drop(foreign_hold);
    }

    #[test]
    fn pending_drop_keeps_original_charge_through_concrete_future_destruction() {
        let budget = original(4096);
        let drops = Arc::new(AtomicUsize::new(0));
        let mut wait = OwnedPreparationWait::try_boxed(&budget, || PendingOwned {
            budget: budget.clone(),
            drops: Arc::clone(&drops),
            payload: [42; 32],
        })
        .unwrap();
        assert_eq!(budget.host_memory_bytes(), size_of::<PendingOwned>() as u64);
        assert!(Pin::new(&mut wait)
            .poll(&mut Context::from_waker(Waker::noop()))
            .is_pending());
        assert_eq!(drops.load(Ordering::SeqCst), 0);
        drop(wait);
        assert_eq!(drops.load(Ordering::SeqCst), 1);
        assert_eq!(budget.host_memory_bytes(), 0);
    }

    #[tokio::test(start_paused = true)]
    async fn actual_sleep_pending_cancel_and_elapsed_keep_original_charge_until_drop() {
        let budget = original(4096);
        let timer = latent_node::CurrentnessReadTimer;
        for cancel in [true, false] {
            let deadline = tokio::time::Instant::now().into_std() + Duration::from_secs(1);
            let mut wait = timer.wait_until_owned(deadline, &budget).unwrap();
            assert_eq!(
                budget.host_memory_bytes(),
                size_of::<tokio::time::Sleep>() as u64
            );
            assert!(Pin::new(&mut wait)
                .poll(&mut Context::from_waker(Waker::noop()))
                .is_pending());
            if cancel {
                drop(wait);
                assert_eq!(budget.host_memory_bytes(), 0);
                tokio::time::advance(Duration::from_secs(2)).await;
            } else {
                tokio::time::advance(Duration::from_secs(1)).await;
                (&mut wait).await;
                assert_ne!(budget.host_memory_bytes(), 0);
                drop(wait);
                assert_eq!(budget.host_memory_bytes(), 0);
            }
        }
    }

    #[test]
    fn unknown_owned_provider_refuses_without_legacy_fallback() {
        struct Legacy(AtomicUsize);
        impl PreparationReadWait for Legacy {
            fn now(&self) -> Instant {
                panic!("owned refusal must not consult the legacy clock");
            }

            fn wait_until(&self, _: Instant) -> latent_core::BoxFuture<'_, ()> {
                self.0.fetch_add(1, Ordering::SeqCst);
                Box::pin(pending())
            }
        }
        let budget = original(4096);
        let legacy = Legacy(AtomicUsize::new(0));
        assert!(matches!(
            legacy.wait_until_owned(Instant::now(), &budget),
            Err(ref error) if error.code == PlatformErrorCode::Unavailable
        ));
        assert_eq!(legacy.0.load(Ordering::SeqCst), 0);
        assert_eq!(budget.host_memory_bytes(), 0);
        drop(legacy.wait_until(Instant::now()));
        assert_eq!(legacy.0.load(Ordering::SeqCst), 1);
    }

    #[tokio::test(start_paused = true)]
    async fn observed_inner_and_outer_refusals_and_pending_drop_preserve_originals() {
        let sleep_bytes = size_of::<tokio::time::Sleep>() as u64;
        assert!(sleep_bytes > 1);
        for memory in [sleep_bytes - 1, sleep_bytes] {
            let budget = original(memory);
            let observer = ObservedReadWait {
                active: AtomicU64::new(0),
                entered: tokio::sync::Notify::new(),
            };
            assert!(matches!(
                observer.wait_until_owned(
                    tokio::time::Instant::now().into_std() + Duration::from_secs(1),
                    &budget,
                ),
                Err(ref error) if error.code == PlatformErrorCode::ResourceExhausted
            ));
            assert_eq!(budget.host_memory_bytes(), 0);
            assert_eq!(observer.active.load(Ordering::Acquire), 0);
            let notified = observer.entered.notified();
            tokio::pin!(notified);
            assert!(notified
                .as_mut()
                .poll(&mut Context::from_waker(Waker::noop()))
                .is_pending());
        }
        let budget = original(4096);
        let foreign = original(4096);
        let foreign_hold = foreign.reserve_host_memory(23).unwrap();
        let observer = ObservedReadWait {
            active: AtomicU64::new(0),
            entered: tokio::sync::Notify::new(),
        };
        let mut wait = observer
            .wait_until_owned(
                tokio::time::Instant::now().into_std() + Duration::from_secs(1),
                &budget,
            )
            .unwrap();
        assert!(budget.host_memory_bytes() > sleep_bytes);
        assert_eq!(observer.active.load(Ordering::Acquire), 0);
        assert!(Pin::new(&mut wait)
            .poll(&mut Context::from_waker(Waker::noop()))
            .is_pending());
        observer.entered.notified().await;
        assert_eq!(observer.active.load(Ordering::Acquire), 1);
        drop(wait);
        assert_eq!(observer.active.load(Ordering::Acquire), 0);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(foreign.host_memory_bytes(), 23);
        drop(foreign_hold);
    }
}

//! Signed V5 runtime components through the existing local node composition.
//! These tests establish shared-host ownership, not a language profile claim.
use super::{fixture::Fixture, packages};
use latent_activation::ActivationOutcome;
use latent_artifacts::ArtifactRepository;
use latent_core::{activation_runtime::RuntimeLimits, ActivationId, PlatformErrorCode, TenantId};
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
    Fixture::with_activation_runtime(cells, (catalog, caller, callee), limits(), call_wall_millis)
        .await
}

/// The normal suite does not build a toolchain. Run the explicit compiler
/// qualification first; a missing fixture is a failure when this is selected.
#[tokio::test]
#[ignore = "requires the pinned Java activation fiber component and explicit java profile"]
async fn signed_java_threads_spin_join_and_thread_local_use_real_activation_fibers() {
    assert_eq!(
        std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(),
        Ok("java")
    );
    let prepared = std::path::PathBuf::from(
        std::env::var_os("LSF_JAVA_FIBER_FIXTURE").expect("prepare the pinned Java fiber fixture"),
    );
    let source = std::fs::read(prepared.join("src/dev/latent/app/Capsule.java")).unwrap();
    assert_eq!(
        source,
        include_bytes!("../../../../sdk/java-guest/fibers/conformance/Capsule.java")
    );
    let record: serde_json::Value =
        serde_json::from_slice(&std::fs::read(prepared.join("FIBERS-COMPILE.json")).unwrap())
            .unwrap();
    assert_eq!(record["profile"], "teavm-activation-fibers-v1");
    let bytes = std::fs::read(prepared.join("build/component.wasm")).unwrap();
    assert_eq!(
        record["componentDigest"],
        latent_artifacts::package::artifact_blob_digest(&bytes).as_str()
    );
    assert_eq!(
        record["sourceDigest"],
        latent_artifacts::package::artifact_blob_digest(&source).as_str()
    );
    assert_eq!(record["reference"].as_array().unwrap().len(), 3);
    let wit = std::fs::read_to_string(prepared.join("wit/service.wit")).unwrap();
    let caller = packages::java_activation_runtime(bytes, &wit);
    let root = tempfile::tempdir().unwrap();
    let f = signed_runtime(root.path(), 1, 120_000, caller, &source).await;
    for iteration in 0..3 {
        let receipt = success(
            f.manager
                .start(f.request(&format!("java-fibers-{iteration}"), 0))
                .unwrap()
                .await,
        );
        assert_eq!(
            serde_json::from_slice::<Vec<u32>>(&receipt.output).unwrap(),
            [42]
        );
        assert!(receipt.consumption.cpu_fuel > 0);
        assert!(receipt.consumption.peak_memory_bytes <= packages::budget().memory_bytes);
        eprintln!(
            "teavm-activation-fibers-v1 iteration={iteration} consumption={:?}",
            receipt.consumption
        );
        f.idle().await;
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
        assert_eq!(
            value(
                f.manager
                    .start(f.request(&format!("fixed-fresh-{cancel}"), 0))
                    .unwrap()
                    .await
            ),
            42
        );
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
    let second = value(
        f.manager
            .start(f.request("second-generation", 14))
            .unwrap()
            .await,
    );
    assert_ne!(first, second);
    f.idle().await;
    let direct = success(
        f.manager
            .start(f.request("lazy-no-concurrency", 15))
            .unwrap()
            .await,
    );
    f.idle().await;
    let owned = success(
        f.manager
            .start(f.request("accounted-runtime-owner", 0))
            .unwrap()
            .await,
    );
    f.idle().await;
    let mut native_exhausted = f.request("native-runtime-exhaustion", 23);
    native_exhausted.budget.memory_bytes = direct.consumption.peak_memory_bytes;
    let exhausted = success(f.manager.start(native_exhausted).unwrap().await);
    assert_eq!(
        serde_json::from_slice::<Vec<u32>>(&exhausted.output).unwrap(),
        [42]
    );
    assert_eq!(
        exhausted.consumption.peak_memory_bytes,
        direct.consumption.peak_memory_bytes
    );
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

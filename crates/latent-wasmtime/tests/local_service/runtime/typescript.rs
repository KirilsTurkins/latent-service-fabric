//! Maintained compiler outputs with real signing, node admission and runtime owners.
use super::{package, packages, Fixture};
use latent_activation::ActivationOutcome;
use latent_artifacts::ArtifactRepository;
use latent_core::{
    activation_runtime::RuntimeLimits, ContractId, PlatformErrorCode, ServiceId, TenantId,
};
use latent_executor::ExecutionBackend;
use std::time::Duration;

fn limits() -> RuntimeLimits {
    RuntimeLimits {
        tasks: 16,
        executors: 2,
        queued_work: 16,
        waits: 8,
        timers: 8,
        results: 8,
        native_owners: 64,
    }
}

async fn fixture(name: &str, root: &std::path::Path) -> Fixture {
    assert_eq!(
        std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(),
        Ok("typescript"),
        "the component campaign has its original explicit TypeScript ceilings"
    );
    let caller = package::bundle(&package::input(name));
    let observed = package::observation(name);
    let callee = package::bundle(&package::input("typescript-service-callee"));
    let signers = package::Signers::for_tenant(&observed.build_type, &TenantId("examples".into()));
    let caller_upload = signers.upload_for_tenant(&caller, &observed, &TenantId("examples".into()));
    let callee_observation = package::observation("typescript-service-callee");
    let callee_upload =
        signers.upload_for_tenant(&callee, &callee_observation, &TenantId("examples".into()));
    let catalog = package::catalog(root, signers.policy, Some(packages::budget().memory_bytes));
    for upload in [caller_upload, callee_upload] {
        catalog
            .admit_package(&TenantId("examples".into()), upload, &mut |_| Ok(()))
            .await
            .unwrap();
    }
    let release = packages::release(&caller);
    let identities = super::super::fixture::RuntimeIdentities {
        tenant: TenantId("examples".into()),
        caller: ServiceId(
            serde_json::from_slice::<serde_json::Value>(caller.blob("capsule.json").unwrap())
                .unwrap()["metadata"]["name"]
                .as_str()
                .unwrap()
                .into(),
        ),
        callee: ServiceId("examples/typescript-runtime-callee".into()),
    };
    let fixture = Fixture::with_named_activation_runtime(
        2,
        (catalog, caller, callee),
        limits(),
        120_000,
        identities,
    )
    .await;
    let publication = fixture
        .catalog
        .execution_eligibility_selected(&release, None)
        .unwrap()
        .unwrap()
        .publication()
        .clone();
    let mut key = fixture.backend.preparation_key(&release).unwrap();
    key.publication = Some(publication);
    let ready = tokio::time::timeout(
        Duration::from_secs(600),
        fixture
            .backend
            .prepare_ready_from_repository(fixture.catalog.clone(), key),
    )
    .await
    .expect("bounded actual signed TypeScript preparation")
    .expect("prepare the actual selected publication");
    drop(fixture.backend.materialize_ready(ready).unwrap());
    fixture.idle().await;
    assert_eq!(fixture.backend.resource_snapshot().stores_created, 0);
    fixture
}

#[tokio::test]
#[ignore = "requires current maintained TypeScript async compiler outputs with actual build observations"]
async fn signed_pending_exports_timers_rejections_and_fresh_state_use_real_node_owners() {
    let root = tempfile::tempdir().unwrap();
    let f = fixture("typescript-ordinary15", root.path()).await;
    for mode in 0..15 {
        let mut request = f.request(&format!("typescript-ordinary-{mode}"), mode);
        request.target.contract = ContractId("examples:typescript-async/ordinary@1.0.0".into());
        let receipt = f.manager.start(request).unwrap().await;
        eprintln!(
            "TypeScript mode={mode} timing={:?}; broker={:?}",
            f.backend.take_invocation_timing(&receipt.activation_id),
            f.broker.snapshot()
        );
        if (9..=12).contains(&mode) {
            let ActivationOutcome::Failed { error, .. } = receipt.outcome else {
                panic!("required rejected or opaque-work export succeeded: {receipt:?}")
            };
            assert_eq!(error.code, PlatformErrorCode::GuestTrap, "{error:?}");
        } else {
            let ActivationOutcome::Succeeded(success) = receipt.outcome else {
                panic!("{}: {:?}", receipt.activation_id.0, receipt.outcome)
            };
            assert_eq!(
                serde_json::from_slice::<Vec<u32>>(&success.output).unwrap(),
                [42]
            );
            assert!(success.consumption.cpu_fuel > 0);
            assert!(success.consumption.peak_memory_bytes <= packages::budget().memory_bytes);
            eprintln!(
                "TypeScript ordinary mode={mode} consumption={:?}",
                success.consumption
            );
        }
        f.idle().await;
    }
    let mut request = f.request("typescript-fresh-after-failures", 13);
    request.target.contract = ContractId("examples:typescript-async/ordinary@1.0.0".into());
    assert_eq!(super::value(f.manager.start(request).unwrap().await), 42);
    f.idle().await;
}

#[tokio::test]
#[ignore = "requires current maintained TypeScript clock compiler outputs with actual build observations"]
async fn signed_standard_clocks_timeout_and_date_use_exact_bound_clock_owners() {
    let root = tempfile::tempdir().unwrap();
    let f = fixture("typescript-clock4", root.path()).await;
    for mode in 0..4 {
        let mut request = f.request(&format!("typescript-clock-{mode}"), mode);
        request.target.contract = ContractId("examples:typescript-async/ordinary@1.0.0".into());
        let receipt = f.manager.start(request).unwrap().await;
        eprintln!("TypeScript clock mode={mode}: {:?}", receipt.outcome);
        assert_eq!(super::value(receipt), 42);
        f.idle().await;
    }
}

#[tokio::test]
#[ignore = "requires current maintained TypeScript service caller and callee compiler outputs with actual build observations"]
async fn signed_async_service_import_preserves_sibling_progress_and_actual_child_owners() {
    let root = tempfile::tempdir().unwrap();
    let f = fixture("typescript-service-caller", root.path()).await;
    for mode in 0..2 {
        let mut request = f.request(&format!("typescript-service-{mode}"), mode);
        request.target.contract = ContractId("examples:typescript-runtime-caller/api@1.0.0".into());
        let receipt = f.manager.start(request).unwrap().await;
        eprintln!("TypeScript service mode={mode}: {:?}", receipt.outcome);
        assert_eq!(super::value(receipt), 42);
        f.idle().await;
    }
}

#[tokio::test]
#[ignore = "requires current maintained native-lock TypeScript npm compiler outputs with actual build observations"]
async fn signed_unchanged_npm_queue_delay_timeout_and_cancellation_use_native_runtime() {
    let root = tempfile::tempdir().unwrap();
    let f = fixture("typescript-npm5", root.path()).await;
    for mode in 0..5 {
        let mut request = f.request(&format!("typescript-npm-{mode}"), mode);
        request.target.contract = ContractId("examples:typescript-async-npm/ordinary@1.0.0".into());
        let receipt = f.manager.start(request).unwrap().await;
        eprintln!("TypeScript npm mode={mode}: {:?}", receipt.outcome);
        assert_eq!(super::value(receipt), 42);
        f.idle().await;
    }
}

fn retirement_request(
    f: &Fixture,
    identity: &str,
    mode: u32,
) -> latent_activation::ActivationRequest {
    let mut request = f.request(identity, mode);
    request.target.contract =
        ContractId("examples:typescript-runtime-retirement/ordinary@1.0.0".into());
    request
}

async fn retirement_idle(f: &Fixture) -> serde_json::Value {
    f.idle().await;
    let owners = f.backend.resource_snapshot();
    let broker = f.broker.snapshot();
    let read_wait = f
        .read_wait
        .active
        .load(std::sync::atomic::Ordering::Acquire);
    assert_eq!(
        (
            owners.active_invocations,
            owners.live_stores,
            owners.live_host_states,
            owners.live_component_instances,
            owners.live_cancellation_probes,
            owners.live_temporary_buffers
        ),
        (0, 0, 0, 0, 0, 0)
    );
    assert_eq!(read_wait, 0);
    serde_json::json!({
        "activeInvocations": owners.active_invocations, "stores": owners.live_stores,
        "hostStates": owners.live_host_states, "componentInstances": owners.live_component_instances,
        "cancellationProbes": owners.live_cancellation_probes, "temporaryBuffers": owners.live_temporary_buffers,
        "calls": broker.calls, "sessions": broker.sessions, "handles": broker.handles,
        "results": broker.results, "bufferBytes": broker.buffer_bytes, "readWaits": read_wait,
        "quotaActivations": f.quotas.usage().unwrap().active_activations,
        "instanceReservations": f.backend.active_instance_reservations(),
        "cancellationRegistrations": f.manager.cancellation_snapshot().active_registrations,
    })
}

async fn retirement_success(f: &Fixture, identity: &str, mode: u32) -> serde_json::Value {
    let mut invocation = Box::pin(
        f.manager
            .start(retirement_request(f, identity, mode))
            .unwrap(),
    );
    let pending = if mode == 5 {
        super::pending_timer(invocation.as_mut(), f).await;
        Some(retirement_pending(f))
    } else {
        None
    };
    let success = super::success(invocation.await);
    let value = serde_json::from_slice::<Vec<u32>>(&success.output).unwrap();
    assert_eq!(value, [42]);
    assert!(success.consumption.cpu_fuel > 0);
    assert!(success.consumption.peak_memory_bytes <= packages::budget().memory_bytes);
    assert_eq!(success.consumption.child_calls, 0);
    assert_eq!(success.consumption.outbound_requests, 0);
    let mut row = serde_json::json!({"case": identity, "mode": mode, "outcome": "Succeeded", "decoded": value,
        "cpuFuel": success.consumption.cpu_fuel, "peakMemoryBytes": success.consumption.peak_memory_bytes});
    drop(success);
    row["idle"] = retirement_idle(f).await;
    if let Some(pending) = pending {
        row["pending"] = pending;
    }
    row
}

fn retirement_pending(f: &Fixture) -> serde_json::Value {
    serde_json::json!({
        "stores": f.backend.resource_snapshot().live_stores,
        "readWaits": f.read_wait.active.load(std::sync::atomic::Ordering::Acquire),
        "calls": f.broker.snapshot().calls,
    })
}

async fn retirement_interrupt(f: &Fixture, identity: &str, cancel: bool) -> serde_json::Value {
    let activation = latent_core::ActivationId(identity.into());
    let mut request = retirement_request(f, identity, 0);
    if !cancel {
        request.budget.wall_time_limit_millis = Some(1000);
    }
    let mut invocation = Box::pin(f.manager.start(request).unwrap());
    // The original pending timer barrier proves guest entry before either
    // cancellation or the original deadline, not merely admission/preparation.
    super::pending_timer(invocation.as_mut(), f).await;
    let pending = retirement_pending(f);
    if cancel {
        f.manager
            .cancel_for(
                &TenantId("examples".into()),
                &activation,
                "typescript-promise-cancel",
            )
            .unwrap();
    }
    let failure = super::failure(invocation.await);
    assert_eq!(
        failure.code,
        if cancel {
            PlatformErrorCode::Cancelled
        } else {
            PlatformErrorCode::DeadlineExceeded
        }
    );
    serde_json::json!({"case": identity, "mode": 0, "outcome": format!("{:?}", failure.code),
        "pending": pending, "idle": retirement_idle(f).await})
}

#[tokio::test]
#[ignore = "requires current maintained TypeScript retirement compiler outputs with actual build observations"]
async fn signed_pending_promise_cancellation_deadline_and_timer_failures_retire_before_fresh_state()
{
    let root = tempfile::tempdir().unwrap();
    let f = fixture("typescript-runtime-retirement", root.path()).await;
    let mut observations = Vec::new();
    for mode in [1, 3] {
        observations.push(
            retirement_success(&f, &format!("typescript-retirement-reference-{mode}"), mode).await,
        );
    }
    observations.push(retirement_success(&f, "typescript-promise-pending-then-resolved", 5).await);
    observations.push(retirement_success(&f, "typescript-fresh-after-promise-resolution", 1).await);
    observations.push(retirement_interrupt(&f, "typescript-pending-promise-cancel", true).await);
    observations.push(retirement_success(&f, "typescript-fresh-after-promise-cancel", 1).await);
    observations
        .push(retirement_interrupt(&f, "typescript-promise-original-root-deadline", false).await);
    observations.push(retirement_success(&f, "typescript-fresh-after-promise-deadline", 1).await);
    let trapped = super::failure(
        f.manager
            .start(retirement_request(&f, "typescript-root-trap-mode", 2))
            .unwrap()
            .await,
    );
    assert_eq!(trapped.code, PlatformErrorCode::GuestTrap);
    observations.push(serde_json::json!({"case": "typescript-root-trap-mode", "mode": 2,
        "outcome": format!("{:?}", trapped.code), "callbackOriginProven": false, "idle": retirement_idle(&f).await}));
    observations.push(retirement_success(&f, "typescript-fresh-after-root-trap", 1).await);
    assert_eq!(observations.len(), 10);
    println!(
        "TYPESCRIPT_RETIREMENT {}",
        serde_json::json!({
            "schemaVersion": "latent.typescript.runtime-retirement.v1", "status": "passed",
            "cases": observations, "fullTicketQualification": false, "crossTenantQualified": false,
        })
    );
}

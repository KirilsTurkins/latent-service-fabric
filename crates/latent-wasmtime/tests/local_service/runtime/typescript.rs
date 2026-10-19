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

#[tokio::test]
#[ignore = "requires current maintained TypeScript retirement compiler outputs with actual build observations"]
async fn signed_pending_promise_cancellation_deadline_and_timer_failures_retire_before_fresh_state()
{
    async fn retired(f: &Fixture) {
        f.idle().await;
        let owners = f.backend.resource_snapshot();
        assert_eq!(
            (
                owners.active_invocations,
                owners.live_stores,
                owners.live_host_states,
                owners.live_component_instances,
                owners.live_cancellation_probes
            ),
            (0, 0, 0, 0, 0)
        );
        assert_eq!(
            f.read_wait
                .active
                .load(std::sync::atomic::Ordering::Acquire),
            0
        );
    }
    let root = tempfile::tempdir().unwrap();
    let f = fixture("typescript-runtime-retirement", root.path()).await;
    let request = |identity: &str, mode| {
        let mut request = f.request(identity, mode);
        request.target.contract =
            ContractId("examples:typescript-runtime-retirement/ordinary@1.0.0".into());
        request
    };
    for mode in [1, 3] {
        assert_eq!(
            super::value(
                f.manager
                    .start(request(
                        &format!("typescript-retirement-reference-{mode}"),
                        mode
                    ))
                    .unwrap()
                    .await
            ),
            42
        );
        retired(&f).await;
    }
    let activation = latent_core::ActivationId("typescript-pending-promise-cancel".into());
    let mut invocation = Box::pin(f.manager.start(request(&activation.0, 0)).unwrap());
    // Use the original Store/read-wait/broker barrier. No sleep, yield count,
    // cancellation request or completed provider call is a retirement witness.
    super::pending_timer(invocation.as_mut(), &f).await;
    f.manager
        .cancel_for(
            &TenantId("examples".into()),
            &activation,
            "typescript-promise-cancel",
        )
        .unwrap();
    assert_eq!(
        super::failure(invocation.await).code,
        PlatformErrorCode::Cancelled
    );
    retired(&f).await;
    assert_eq!(
        super::value(
            f.manager
                .start(request("typescript-fresh-after-promise-cancel", 1))
                .unwrap()
                .await
        ),
        42
    );
    retired(&f).await;
    let mut deadline = request("typescript-promise-original-root-deadline", 0);
    deadline.budget.wall_time_limit_millis = Some(1000);
    let mut deadline_invocation = Box::pin(f.manager.start(deadline).unwrap());
    // An expired admission or slow preparation is not evidence that a pending
    // ordinary Promise was retired by its original root deadline.
    super::pending_timer(deadline_invocation.as_mut(), &f).await;
    assert_eq!(
        super::failure(deadline_invocation.await).code,
        PlatformErrorCode::DeadlineExceeded
    );
    retired(&f).await;
    assert_eq!(
        super::value(
            f.manager
                .start(request("typescript-fresh-after-promise-deadline", 1))
                .unwrap()
                .await
        ),
        42
    );
    retired(&f).await;
    let mode = 2;
    assert_eq!(
        super::failure(
            f.manager
                .start(request(
                    &format!("typescript-accepted-timer-error-{mode}"),
                    mode
                ))
                .unwrap()
                .await
        )
        .code,
        PlatformErrorCode::GuestTrap
    );
    retired(&f).await;
    assert_eq!(
        super::value(
            f.manager
                .start(request(
                    &format!("typescript-fresh-after-timer-error-{mode}"),
                    1
                ))
                .unwrap()
                .await
        ),
        42
    );
    retired(&f).await;
}

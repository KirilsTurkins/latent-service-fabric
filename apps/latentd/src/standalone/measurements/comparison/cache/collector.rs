use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Instant;

use serde_json::{json, Value};

use super::super::evidence;
use super::{cold, fixture, observation, plan, Fixture, Node, State, Writer};

#[expect(
    clippy::too_many_lines,
    reason = "The common collector keeps startup, all measured work and synchronous teardown in one auditable sequence."
)]
pub(super) fn collect() {
    let origin = Instant::now();
    let plan: plan::Plan = serde_json::from_slice(
        &super::super::super::read(
            &super::super::super::required("LSF_PHASE1_COMPARISON_PLAN"),
            64 * 1024,
        )
        .unwrap(),
    )
    .unwrap();
    plan.validate().unwrap();
    let identity: Value = serde_json::from_slice(
        &super::super::super::read(
            &super::super::super::required("LSF_PHASE1_COMPARISON_IDENTITY"),
            1024 * 1024,
        )
        .unwrap(),
    )
    .unwrap();
    let base = Fixture::echo().unwrap();
    evidence::validate_identity(&identity, &base).unwrap();
    let fixtures = fixture::variants(&base).unwrap();
    let releases: Vec<_> = fixtures
        .iter()
        .map(|value| value.release_digest.clone())
        .collect();
    let directory = super::super::super::required("LSF_PHASE1_COMPARISON_OUTPUT");
    let data = tempfile::Builder::new()
        .prefix("cache-comparison-owned-")
        .tempdir_in(super::super::super::required(
            "LSF_PHASE1_COMPARISON_DATA_ROOT",
        ))
        .unwrap();
    let runtime_threads = crate::standalone::RuntimeThreads::default();
    let client_threads = Arc::new(AtomicUsize::new(0));
    let invocation = super::super::super::runtime(2, &runtime_threads.invocation);
    let control = super::super::super::runtime(4, &runtime_threads.control);
    let client = super::super::super::runtime(2, &client_threads);
    let mut node = invocation
        .block_on(Node::start_configured(
            plan.commands(),
            plan.configuration(data.path()),
            base,
            control.handle().clone(),
            crate::standalone::RuntimeThreads {
                invocation: runtime_threads.invocation.clone(),
                control: runtime_threads.control.clone(),
            },
            origin,
        ))
        .unwrap();
    let observer = node.owner.backend.preparation_observer();
    let runtime_observer = node.owner.backend.prepared_runtime_observer();
    observer.enable();
    let clock = cold::call::Clock::new().unwrap();
    let setup = client.block_on(async {
        node.reconnect().await?;
        cold::fixture::publish(&mut node, fixtures, &directory).await
    });
    let mut options = evidence::options(&node);
    options["pool_capacity"] = json!("4");
    options["queue_capacity"] = json!("64");
    options["control_workers"] = json!("4");
    let header = json!({"schema":"latent.optimization.cache-behavior-arm.v1","plan":plan,"identity":identity,
        "configuration":node.config,"effective_options":options,"semantic_input":evidence::input(),"clock":clock.record(),
        "startup":node.startup,"fixtures":setup.as_ref().ok(),
        "initial_observer":cold::observation::snapshot(&observer,clock).unwrap(),
        "initial_accounting":observation::decimal(&node.owner.backend.cache_accounting_snapshot()).unwrap(),
        "configured_runtimes":{"invocation":2,"control":4,"client":2},
        "population":{"attempts":plan.attempts().to_string(),"commands":plan.commands().to_string(),
            "direct_readiness_acquisitions":"2","direct_materializations":"1","direct_executions":"1","explicit_releases":"9"},
        "event_export":{"maximum_sequential_calls":16,"sequence_policy":"contiguous-deduplicated","maximum_stage_ring":256}});
    let mut writer = Writer::named(&directory, "cache.json", 2048, &header).unwrap();
    let mut state = State::default();
    let result = match setup {
        Ok(_) => client.block_on(async {
            tokio::time::timeout(
                plan::Plan::duration(),
                Box::pin(super::run(
                    &mut node,
                    &mut writer,
                    clock,
                    &plan,
                    &releases,
                    &mut state,
                )),
            )
            .await
            .map_err(|_| Box::<dyn std::error::Error + Send + Sync>::from("cache arm deadline"))?
        }),
        Err(error) => Err(error),
    };
    let before_shutdown = node.sample("cache-before-shutdown");
    let accounting_before_shutdown = node.owner.backend.cache_accounting_snapshot();
    let work = node.work;
    // Descriptor copies carry no runtime ownership. All affine owners were
    // scoped inside run; an error also drops them before explicit shutdown.
    state.descriptors.fill(None);
    let shutdown = invocation.block_on(node.shutdown());
    let cleanup = data.close();
    drop(client);
    drop(control);
    drop(invocation);
    let runtimes = json!({"invocation":runtime_threads.invocation.load(Ordering::Acquire),
        "control":runtime_threads.control.load(Ordering::Acquire),"client":client_threads.load(Ordering::Acquire)});
    let final_observer = cold::observation::snapshot(&observer, clock).unwrap();
    let final_accounting = runtime_observer.snapshot();
    let unique_clean = final_accounting
        .is_none_or(|snapshot| snapshot == latent_wasmtime::PreparedRuntimeSnapshot::default());
    let clean = shutdown.as_ref().is_ok_and(|report| {
        report.clean
            && report.telemetry_flushed
            && report.epoch_helper_joined
            && report.quarantined_cells == 0
    }) && cleanup.is_ok()
        && before_shutdown.is_ok()
        && unique_clean
        && runtimes == json!({"invocation":0,"control":0,"client":0})
        && observer.snapshot().active_jobs == 0;
    let passed = result.is_ok()
        && clean
        && work.invoke_attempts == plan.attempts()
        && work.commands == plan.commands()
        && state.direct.readiness_acquisitions == 2
        && state.direct.materializations == 1
        && state.direct.executions == 1
        && state.direct.releases == 9;
    writer.finish(&json!({"status":if passed {"passed"} else {"failed"},"reason":(!passed).then_some("cache-comparison-failed"),
        "elapsed_micros":origin.elapsed().as_micros().to_string(),"work":work,
        "direct_work":observation::decimal(&state.direct).unwrap(),"before_shutdown":before_shutdown.ok(),
        "accounting_before_shutdown":observation::decimal(&accounting_before_shutdown).unwrap(),"shutdown":shutdown.ok(),
        "data_cleanup":{"removed":cleanup.is_ok()},"runtime_threads_after_join":runtimes,"final_observer":final_observer,
        "final_runtime_accounting":observation::decimal(&final_accounting).unwrap()})).unwrap();
    result.unwrap();
    assert!(passed, "cache behavior ownership or population failure");
}

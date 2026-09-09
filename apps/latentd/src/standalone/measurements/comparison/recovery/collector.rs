use super::super::super::{fixtures::Fixture, read, required, runtime};
use super::{
    budget::{
        self,
        collector::{fixture, ObservingClock},
    },
    cold::call::Clock,
    plan::Plan,
    sequence, Node, Writer,
};
use latent_core::{DeadlineDiagnosticObserver, DeadlineWaitObserver};
use serde_json::{json, Value};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

#[expect(
    clippy::too_many_lines,
    reason = "One bounded actual node, its diagnostic population and all owned runtimes share a teardown boundary."
)]
pub(super) fn collect() {
    let clock = Clock::new().unwrap();
    let origin = clock.origin;
    let plan: Plan =
        serde_json::from_slice(&read(&required("LSF_PHASE1_COMPARISON_PLAN"), 64 * 1024).unwrap())
            .unwrap();
    plan.validate().unwrap();
    let identity: Value = serde_json::from_slice(
        &read(&required("LSF_PHASE1_COMPARISON_IDENTITY"), 1024 * 1024).unwrap(),
    )
    .unwrap();
    let base = Fixture::generic().unwrap();
    let identities = identity["fixtures"]
        .as_array()
        .expect("recovery fixture identities");
    assert_eq!(identities.len(), 1);
    assert_eq!(identities[0]["name"], "generic");
    assert_eq!(identities[0]["sha256"], base.release_digest);
    assert_eq!(
        identities[0]["bytes"],
        base.artifact.component_bytes.len().to_string()
    );
    let directory = required("LSF_PHASE1_COMPARISON_OUTPUT");
    let data = tempfile::Builder::new()
        .prefix("transport-recovery-owned-")
        .tempdir_in(required("LSF_PHASE1_COMPARISON_DATA_ROOT"))
        .unwrap();
    let diagnostic = DeadlineDiagnosticObserver::with_limits(origin, 64, 2048).unwrap();
    let waits = DeadlineWaitObserver::new();
    let observing = Arc::new(ObservingClock {
        diagnostic: diagnostic.clone(),
        waits: waits.clone(),
    });
    let threads = crate::standalone::RuntimeThreads::default();
    let client_threads = Arc::new(AtomicUsize::new(0));
    let invocation = runtime(2, &threads.invocation);
    let control = runtime(4, &threads.control);
    let client = runtime(2, &client_threads);
    let mut node = invocation
        .block_on(Node::start_with_clock(
            256,
            plan.configuration(data.path()),
            base,
            control.handle().clone(),
            crate::standalone::RuntimeThreads {
                invocation: threads.invocation.clone(),
                control: threads.control.clone(),
            },
            origin,
            observing,
        ))
        .unwrap();
    let preparation = node.owner.backend.preparation_observer();
    let initial_cleanup = node.owner.cleanup_snapshot();
    let candidate = initial_cleanup.is_some();
    let setup = client.block_on(async {
        node.reconnect().await?;
        let publication = node.publish().await?;
        node.published().await?;
        fixture(&directory, &node, &publication)
    });
    let mut options = super::super::evidence::options(&node);
    options["memory_bytes"] = json!("67108864");
    options["pool_capacity"] = json!("4");
    options["queue_capacity"] = json!("64");
    options["control_workers"] = json!("4");
    let header = json!({"schema":"latent.optimization.recovery-arm.v1","plan":plan,"identity":identity,
        "configuration":node.config,"effective_options":options,"clock":clock.record(),"startup":node.startup,
        "fixture":setup.as_ref().ok(),"configured_runtimes":{"invocation":2,"control":4,"client":2},
        "population":{"invoke_attempts":"61","maximum_commands":"256","expected_commands":"125"},
        "diagnostic_limits":{"identities":"64","records":"2048","identifier_bytes":"256"},
        "cleanup_limits":{"grace_millis":"100","handoff_ceiling_millis":"200","observation_millis":"250"},
        "initial_waits":budget::observation::waits(&waits),"initial_cleanup":initial_cleanup,
        "initial_node":node.sample("recovery-initial").unwrap()});
    let mut writer = Writer::named(&directory, "recovery.json", 256, &header).unwrap();
    let mut state = sequence::State::default();
    let cpu_before = budget::cpu::sample(clock);
    let result = match setup {
        Ok(_) => client.block_on(async {
            tokio::time::timeout(
                Duration::from_mins(3),
                Box::pin(sequence::run(
                    &mut node,
                    clock,
                    &diagnostic,
                    &waits,
                    &mut writer,
                    &mut state,
                )),
            )
            .await
            .map_err(|_| {
                Box::<dyn std::error::Error + Send + Sync>::from("recovery arm deadline")
            })?
        }),
        Err(error) => Err(error),
    };
    let drained = client.block_on(super::cold::observation::drain(&preparation, clock));
    let cpu_after = budget::cpu::sample(clock);
    for row in &state.offers {
        writer.sample(row).unwrap();
    }
    let before_shutdown = node.sample("recovery-before-shutdown");
    let cleanup_before_shutdown = node.owner.cleanup_snapshot();
    let work = node.work;
    let shutdown = invocation.block_on(node.shutdown());
    let data_cleanup = data.close();
    drop(client);
    drop(control);
    drop(invocation);
    let joined = json!({"invocation":threads.invocation.load(Ordering::Acquire),
        "control":threads.control.load(Ordering::Acquire),"client":client_threads.load(Ordering::Acquire)});
    let diagnostics = budget::observation::diagnostic(&diagnostic, clock).unwrap();
    let clean = shutdown.as_ref().is_ok_and(|report| {
        report.clean
            && report.telemetry_flushed
            && report.epoch_helper_joined
            && (!candidate || report.quarantined_cells == 0)
    }) && data_cleanup.is_ok()
        && drained.is_ok()
        && joined == json!({"invocation":0,"control":0,"client":0})
        && waits.snapshot().live == 0
        && !waits.snapshot().overflowed
        && !diagnostic.snapshot().overflowed;
    let coverage = state.offers.len() == 61
        && diagnostic.snapshot().identities.len() == 61
        && state.offers.iter().all(|row| {
            !row["diagnostic_token"].is_null()
                && (row["outcome"] == "client-disconnected"
                    || row["outcome"] == "transport-failure"
                    || row["valid_response"] == true)
        });
    let passed = result.is_ok()
        && clean
        && coverage
        && work.invoke_attempts == 61
        && work.commands == 125
        && state.controls == 62
        && !work.budget_exhausted
        && (!candidate || state.recovery_healthy);
    writer.finish(&json!({"status":if passed {"passed"}else{"failed"},"reason":(!passed).then_some("transport-recovery-failed"),
        "elapsed_micros":origin.elapsed().as_micros().to_string(),"work":work,"diagnostic":diagnostics,
        "final_waits":budget::observation::waits(&waits),"before_shutdown":before_shutdown.ok(),
        "cleanup_before_shutdown":cleanup_before_shutdown,"shutdown":shutdown.ok(),
        "data_cleanup":{"removed":data_cleanup.is_ok()},"runtime_threads_after_join":joined,
        "process_cpu":{"scope":"owned-process-recovery-population-and-controls",
            "clock_ticks_per_second":identity["environment"]["clock_ticks_per_second"],"before":cpu_before.ok(),"after":cpu_after.ok()}})).unwrap();
    result.unwrap();
    assert!(passed, "recovery coverage, cleanup or population failed");
}

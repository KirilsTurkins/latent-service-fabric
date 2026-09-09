use std::path::Path;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use latent_artifacts::{encode_contract_metadata, ContractMetadataLimits};
use latent_core::{ActivationClock, ClockSample, DeadlineDiagnosticObserver, DeadlineWaitObserver};
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use serde_json::{json, Value};

use super::super::super::{
    fixture_inputs::retain, fixtures::Fixture, platform, read, required, runtime,
};
use super::{cold::call::Clock, observation, plan::Plan, sequence, Node, Result, Writer};

pub(in crate::standalone::measurements::comparison) struct ObservingClock {
    pub diagnostic: DeadlineDiagnosticObserver,
    pub waits: DeadlineWaitObserver,
}
impl ActivationClock for ObservingClock {
    fn sample(&self) -> ClockSample {
        ClockSample::system_now()
    }
    fn monotonic_now(&self) -> Instant {
        Instant::now()
    }
    fn uses_system_monotonic(&self) -> bool {
        true
    }
    fn deadline_wait_observer(&self) -> Option<&DeadlineWaitObserver> {
        Some(&self.waits)
    }
    fn deadline_diagnostic_observer(&self) -> Option<&DeadlineDiagnosticObserver> {
        Some(&self.diagnostic)
    }
}

pub(in crate::standalone::measurements::comparison) fn fixture(
    directory: &Path,
    node: &Node,
    publication: &Value,
) -> Result<Value> {
    let value = &node.fixture;
    let codec = JsonManifestCodec::default();
    let capsule = codec
        .encode_capsule(&value.artifact.manifest)
        .map_err(|_| "budget capsule encoding")?;
    let contracts =
        encode_contract_metadata(&value.artifact.contracts, ContractMetadataLimits::default())
            .map_err(platform)?;
    let deployment = codec
        .encode_deployment(&value.deployment)
        .map_err(|_| "budget deployment encoding")?;
    Ok(
        json!({"name":"generic","tenant":value.tenant,"service":value.service,"contract":value.contract,
        "component_sha256":value.release_digest,"component_bytes":value.artifact.component_bytes.len().to_string(),
        "capsule":retain(directory,"generic-capsule.json",&capsule)?,
        "contracts":retain(directory,"generic-contracts.json",&contracts)?,
        "deployment":retain(directory,"generic-deployment.json",&deployment)?,"publication":publication}),
    )
}

#[expect(
    clippy::too_many_lines,
    reason = "Owned runtimes, the bounded diagnostic and synchronous teardown form one auditable collector boundary."
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
    let identities = identity["fixtures"].as_array().expect("fixture identities");
    assert_eq!(identities.len(), 1);
    assert_eq!(identities[0]["name"], "generic");
    assert_eq!(identities[0]["sha256"], base.release_digest);
    assert_eq!(
        identities[0]["bytes"],
        base.artifact.component_bytes.len().to_string()
    );
    let directory = required("LSF_PHASE1_COMPARISON_OUTPUT");
    let data = tempfile::Builder::new()
        .prefix("budget-lifecycle-owned-")
        .tempdir_in(required("LSF_PHASE1_COMPARISON_DATA_ROOT"))
        .unwrap();
    let diagnostic = DeadlineDiagnosticObserver::new(origin);
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
            153,
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
    let header = json!({"schema":"latent.optimization.budget-lifecycle-arm.v1","plan":plan,"identity":identity,
        "configuration":node.config,"effective_options":options,"clock":clock.record(),"startup":node.startup,
        "fixture":setup.as_ref().ok(),"configured_runtimes":{"invocation":2,"control":4,"client":2},
        "population":{"invoke_attempts":"23","maximum_control_commands":"128"},
        "initial_waits":observation::waits(&waits),"initial_node":node.sample("budget-initial").unwrap()});
    let mut writer = Writer::named(&directory, "budget.json", 256, &header).unwrap();
    let mut state = sequence::State::default();
    let cpu_before = super::cpu::sample(clock);
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
            .map_err(|_| Box::<dyn std::error::Error + Send + Sync>::from("budget arm deadline"))?
        }),
        Err(error) => Err(error),
    };
    // A timed-out/error sequence drops every owned Invoke before bounded drain.
    let drained = client.block_on(super::cold::observation::drain(&preparation, clock));
    let cpu_after = super::cpu::sample(clock);
    state.offers.sort_by_key(|row| {
        row["ordinal"]
            .as_str()
            .and_then(|value| value.parse::<u32>().ok())
    });
    for row in &state.offers {
        writer.sample(row).unwrap();
    }
    let before_shutdown = node.sample("budget-before-shutdown");
    let idle = before_shutdown
        .as_ref()
        .is_ok_and(|sample| super::super::super::soak::assert_idle(sample).is_ok());
    let work = node.work;
    let shutdown = invocation.block_on(node.shutdown());
    let cleanup = data.close();
    drop(client);
    drop(control);
    drop(invocation);
    let joined = json!({"invocation":threads.invocation.load(Ordering::Acquire),"control":threads.control.load(Ordering::Acquire),
        "client":client_threads.load(Ordering::Acquire)});
    let diagnostics = observation::diagnostic(&diagnostic, clock).unwrap();
    let final_waits = waits.snapshot();
    let clean = shutdown.as_ref().is_ok_and(|report| {
        report.clean
            && report.telemetry_flushed
            && report.epoch_helper_joined
            && report.quarantined_cells == 0
    }) && cleanup.is_ok()
        && idle
        && drained.is_ok()
        && joined == json!({"invocation":0,"control":0,"client":0})
        && final_waits.live == 0
        && !final_waits.overflowed
        && !diagnostic.snapshot().overflowed;
    let coverage = state.offers.len() == 23
        && diagnostic.snapshot().identities.len() == 23
        && state.offers.iter().all(|row| {
            if row["diagnostic_token"].is_null() {
                return false;
            }
            !(row["case"] == "queued"
                && matches!(row["budget_millis"].as_str(), Some("5" | "10"))
                && row["queue_witness"].is_null())
        });
    let passed = result.is_ok()
        && clean
        && coverage
        && work.invoke_attempts == 23
        && work.commands == 25 + state.controls
        && !work.budget_exhausted;
    writer.finish(&json!({"status":if passed{"passed"}else{"failed"},"reason":(!passed).then_some("budget-lifecycle-failed"),
        "elapsed_micros":origin.elapsed().as_micros().to_string(),"work":work,"diagnostic":diagnostics,
        "final_waits":observation::waits(&waits),"before_shutdown":before_shutdown.ok(),"shutdown":shutdown.ok(),
        "data_cleanup":{"removed":cleanup.is_ok()},"runtime_threads_after_join":joined,
        "process_cpu":{"scope":"owned-process-diagnostic-population-and-controls",
            "clock_ticks_per_second":identity["environment"]["clock_ticks_per_second"],
            "before":cpu_before.ok(),"after":cpu_after.ok()}})).unwrap();
    result.unwrap();
    assert!(
        passed,
        "budget diagnostic coverage, ownership or population failure"
    );
}

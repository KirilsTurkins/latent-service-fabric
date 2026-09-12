//! Selected adapter/network equivalence on the actual standalone composition.
//! Invoked only by the bounded conformance runner, with prebuilt fixtures.
mod capabilities;
mod cases;
mod fixture;
mod outcomes;
mod session;
mod status;
mod telemetry;

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use latent_testkit::conformance::{encode_bounded, CaseEvidence, DriverEvidence, ReportLimits};
use latent_testkit::{InvariantProbe, ObservedInvariantProbe};
use serde_json::{json, Value};

use super::{RuntimeThreads, StandaloneNode};
use session::Session;

#[test]
#[ignore = "requires prebuilt echo/capabilities and bounded evidence runner; exactly 22 Invoke attempts"]
fn adapter_and_rpc_have_equivalent_selected_outcomes() {
    let directory = tempfile::tempdir().unwrap();
    let (config, public_config) = fixture::configuration(directory.path());
    let observed = RuntimeThreads::default();
    let invocation = runtime(&observed.invocation);
    let control = runtime(&observed.control);
    let evidence = invocation.block_on(async {
        tokio::time::timeout(
            Duration::from_secs(45),
            Box::pin(run(
                &config,
                public_config,
                control.handle().clone(),
                RuntimeThreads {
                    invocation: observed.invocation.clone(),
                    control: observed.control.clone(),
                },
            )),
        )
        .await
        .expect("45-second adapter parity deadline")
    });
    drop(invocation);
    drop(control);
    assert_eq!(observed.invocation.load(Ordering::Acquire), 0);
    assert_eq!(observed.control.load(Ordering::Acquire), 0);
    let path = std::env::var_os("LSF_PHASE1_PARITY_REPORT").expect("required parity evidence path");
    std::fs::write(
        path,
        encode_bounded(&evidence, ReportLimits::default()).unwrap(),
    )
    .unwrap();
}

async fn run(
    config: &crate::config::NodeConfig,
    public_config: Value,
    control: tokio::runtime::Handle,
    threads: RuntimeThreads,
) -> DriverEvidence {
    let config_sha256 =
        latent_artifacts::content_digest(&serde_json::to_vec(&public_config).unwrap()).0;
    let mut session = Session::start(config, control, threads).await;
    let (pairs, echo_telemetry) = outcomes::run(&mut session).await;
    let (capability_pairs, capability_telemetry) = capabilities::run(&mut session).await;
    assert_eq!(echo_telemetry["service"], capability_telemetry["service"]);
    assert_ne!(echo_telemetry["tenant"], capability_telemetry["tenant"]);
    assert_ne!(
        echo_telemetry["release_digest"],
        capability_telemetry["release_digest"]
    );
    assert_ne!(
        echo_telemetry["completion_span"]["trace"]["trace_id"],
        capability_telemetry["completion_span"]["trace"]["trace_id"]
    );
    assert!(!echo_telemetry["guest_logs"].as_array().unwrap().is_empty());
    assert!(!capability_telemetry["guest_logs"]
        .as_array()
        .unwrap()
        .is_empty());
    let probe = ObservedInvariantProbe::new(
        session.node.inventory.as_ref(),
        session.node.sink.as_ref(),
        None,
    )
    .unwrap();
    let inventory = probe.node_inventory().await.unwrap();
    assert_eq!(inventory.cache_summary.entries, 2);
    let retained_metrics = probe.telemetry().await.unwrap().len();
    assert!(
        probe.idle_scaling(1).await.is_err(),
        "no invented route latency measurement"
    );
    let Session {
        node,
        adapter,
        client,
        work,
        inputs,
        published_inputs,
        artifacts,
        ..
    } = session;
    drop(adapter);
    drop(client);
    let shutdown = node.shutdown().await.unwrap();
    assert!(
        shutdown.clean && shutdown.telemetry_flushed && shutdown.epoch_helper_joined,
        "{shutdown:?}"
    );
    assert_eq!(work.snapshot().invoke_attempts, 22);
    let counts = work.snapshot();
    DriverEvidence {
        driver: "adapter".to_owned(),
        work: counts,
        artifacts,
        cases: vec![CaseEvidence {
            diagnostics: vec!["adapter.json".to_owned()],
            ..CaseEvidence::passed(
                "adapter-rpc-parity",
                counts,
                json!({
                    "pairs":pairs,"capability_pairs":capability_pairs,
                    "tenant_telemetry":[echo_telemetry,capability_telemetry],
                    "shutdown":shutdown,"node_starts":"1",
                    "retained_metric_points":retained_metrics.to_string(),
                    "inventory_cache_entries":inventory.cache_summary.entries.to_string(),
                    "public_config":public_config,"config_sha256":config_sha256,
                    "inputs":inputs,"published_inputs":published_inputs,
                    "comparison":"typed outcomes, pins, scoped context, live budgets, clocks, trace/log correlation and retained accounting",
                    "variable_fields":["activation identity","trace identity","wall-clock and elapsed measurements","clock-dependent fuel"],
                    "scope":"eleven adapter/RPC pairs plus shared-service tenant telemetry; heavy completion evidence remains unrun"
                }),
            )
        }],
    }
}

fn runtime(observed: &Arc<AtomicUsize>) -> tokio::runtime::Runtime {
    let started = observed.clone();
    let stopped = observed.clone();
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(1)
        .max_blocking_threads(1)
        .on_thread_start(move || {
            started.fetch_add(1, Ordering::Release);
        })
        .on_thread_stop(move || {
            stopped.fetch_sub(1, Ordering::Release);
        })
        .enable_all()
        .build()
        .unwrap()
}

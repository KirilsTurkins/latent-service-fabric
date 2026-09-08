//! Matched synchronous/worker cold observation; no measured compiler barriers.
mod call;
mod fixture;
mod observation;
mod plan;
mod schedule;

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Instant;

use serde_json::{json, Value};

use super::super::{fixtures::Fixture, Result};
use super::{evidence, node::Node, writer::Writer, INPUT};

#[test]
#[ignore = "explicit cold revision profile supplies bounded plan and exact inputs"]
fn phase1_cold_preparation_collector() {
    let origin = Instant::now();
    let plan: plan::Plan = serde_json::from_slice(
        &super::super::read(
            &super::super::required("LSF_PHASE1_COMPARISON_PLAN"),
            64 * 1024,
        )
        .unwrap(),
    )
    .unwrap();
    plan.validate().unwrap();
    let identity: Value = serde_json::from_slice(
        &super::super::read(
            &super::super::required("LSF_PHASE1_COMPARISON_IDENTITY"),
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
    let directory = super::super::required("LSF_PHASE1_COMPARISON_OUTPUT");
    let data = tempfile::Builder::new()
        .prefix("cold-comparison-owned-")
        .tempdir_in(super::super::required("LSF_PHASE1_COMPARISON_DATA_ROOT"))
        .unwrap();
    let observed = crate::standalone::RuntimeThreads::default();
    let client_threads = Arc::new(AtomicUsize::new(0));
    let invocation = super::super::runtime(2, &observed.invocation);
    let control = super::super::runtime(4, &observed.control);
    let client = super::super::runtime(2, &client_threads);
    let mut node = invocation
        .block_on(Node::start_configured(
            plan.commands(),
            plan.configuration(data.path()),
            base,
            control.handle().clone(),
            crate::standalone::RuntimeThreads {
                invocation: observed.invocation.clone(),
                control: observed.control.clone(),
            },
            origin,
        ))
        .unwrap();
    let observer = node.owner.backend.preparation_observer();
    observer.enable();
    let clock = call::Clock::new().unwrap();
    let setup = client.block_on(async {
        node.reconnect().await?;
        fixture::publish(&mut node, fixtures, &directory).await
    });
    let mut effective_options = evidence::options(&node);
    effective_options["pool_capacity"] = json!("4");
    effective_options["queue_capacity"] = json!("64");
    effective_options["control_workers"] = json!("4");
    let header = json!({"schema":"latent.optimization.cold-arm.v1","plan":plan,"identity":identity,
        "configuration":node.config,"effective_options":effective_options,"semantic_input":evidence::input(),"clock":clock.record(),
        "startup":node.startup,"fixtures":setup.as_ref().ok(),"initial_observer":observation::snapshot(&observer,clock).unwrap(),
        "configured_runtimes":{"invocation":2,"control":4,"client":2},
        "population":{"attempts":plan.attempts().to_string(),"commands":plan.commands().to_string()}});
    let mut writer = Writer::named(&directory, "cold.json", 2048, &header).unwrap();
    let result = match setup {
        Ok(_) => client.block_on(async {
            tokio::time::timeout(
                plan.duration(),
                run(&mut node, &mut writer, clock, &plan, &releases),
            )
            .await
            .map_err(|_| Box::<dyn std::error::Error + Send + Sync>::from("cold arm deadline"))?
        }),
        Err(error) => Err(error),
    };
    let before_shutdown = node.sample("cold-before-shutdown");
    let work = node.work;
    let shutdown = invocation.block_on(node.shutdown());
    let cleanup = data.close();
    // Runtime ownership is synchronous and survives every measured future.
    drop(client);
    drop(control);
    drop(invocation);
    let runtimes = json!({"invocation":observed.invocation.load(Ordering::Acquire),
        "control":observed.control.load(Ordering::Acquire),"client":client_threads.load(Ordering::Acquire)});
    let final_observer = observation::snapshot(&observer, clock).unwrap();
    let clean = shutdown.as_ref().is_ok_and(|report| {
        report.clean
            && report.telemetry_flushed
            && report.epoch_helper_joined
            && report.quarantined_cells == 0
    }) && cleanup.is_ok()
        && before_shutdown.is_ok()
        && runtimes == json!({"invocation":0,"control":0,"client":0})
        && observer.snapshot().active_jobs == 0;
    let passed = result.is_ok()
        && clean
        && work.invoke_attempts == plan.attempts()
        && work.commands == plan.commands();
    writer.finish(&json!({"status":if passed {"passed"} else {"failed"},
        "reason":(!passed).then_some("cold-comparison-failed"),"elapsed_micros":origin.elapsed().as_micros().to_string(),
        "work":work,"before_shutdown":before_shutdown.ok(),"shutdown":shutdown.ok(),
        "data_cleanup":{"removed":cleanup.is_ok()},"runtime_threads_after_join":runtimes,"final_observer":final_observer})).unwrap();
    result.unwrap();
    assert!(passed, "cold comparison ownership or population failure");
}

async fn run(
    node: &mut Node,
    writer: &mut Writer,
    clock: call::Clock,
    plan: &plan::Plan,
    releases: &[String],
) -> Result<()> {
    checkpoint(node, writer, clock, "empty")?;
    schedule::sequential(node, writer, clock, "warmup", plan.warmup(), &releases[0]).await?;
    checkpoint(node, writer, clock, "after-warmup")?;
    schedule::sequential(
        node,
        writer,
        clock,
        "baseline",
        plan.baseline(),
        &releases[0],
    )
    .await?;
    checkpoint(node, writer, clock, "after-baseline")?;
    schedule::burst(
        node, writer, clock, plan, "same-key", &[1; 8], releases, false,
    )
    .await?;
    schedule::burst(
        node,
        writer,
        clock,
        plan,
        "distinct",
        &[2, 3, 4, 5, 6],
        releases,
        false,
    )
    .await?;
    schedule::burst(node, writer, clock, plan, "cancel", &[7; 8], releases, true).await?;
    schedule::sequential(node, writer, clock, "healthy", plan.healthy(), &releases[0]).await?;
    checkpoint(node, writer, clock, "after-healthy")
}

fn checkpoint(node: &Node, writer: &mut Writer, clock: call::Clock, label: &str) -> Result<()> {
    let sample = node.sample(label)?;
    super::super::soak::assert_idle(&sample)?;
    writer.sample(&json!({"kind":"checkpoint","label":label,"node":sample,
        "observer":observation::snapshot(&node.owner.backend.preparation_observer(),clock)?}))
}

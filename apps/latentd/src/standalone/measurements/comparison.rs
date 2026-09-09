//! Controlled semantic echo arm; separate from the full measurement profiles.
mod budget;
mod cache;
mod call;
mod cold;
mod evidence;
mod node;
mod ownership;
mod ownership_supervision;
mod plan;
mod recovery;
mod revision;
mod writer;

use std::path::Path;
use std::sync::atomic::Ordering;
use std::time::Instant;

use latent_executor::{ExecutionBackend, PreparedComponent};
use serde_json::{json, Value};

use super::{fixtures::Fixture, platform, Profile, Result};
use node::Node;
use plan::Plan;
use writer::Writer;

const INPUT: &str = "phase0 targeted warm echo";

#[test]
#[ignore = "explicit paired comparison runner supplies bounded plan and historical control"]
fn phase1_comparison_collector() {
    let origin = Instant::now();
    let plan: Plan = serde_json::from_slice(
        &super::read(&super::required("LSF_PHASE1_COMPARISON_PLAN"), 64 * 1024).unwrap(),
    )
    .unwrap();
    plan.validate().unwrap();
    let identity: Value = serde_json::from_slice(
        &super::read(
            &super::required("LSF_PHASE1_COMPARISON_IDENTITY"),
            1024 * 1024,
        )
        .unwrap(),
    )
    .unwrap();
    let mut fixture = Fixture::echo().unwrap();
    // The mixed-workload fixture reserves 64 MiB. This separate paired arm
    // publishes the agreed 16 MiB ceiling in both persisted policy layers,
    // matching the historical staged capsule and this node's actual limit.
    fixture
        .artifact
        .manifest
        .execution
        .resource_budget_ceiling
        .memory_bytes = 16_777_216;
    fixture.deployment.resources.memory_bytes = 16_777_216;
    evidence::validate_identity(&identity, &fixture).unwrap();
    let directory = super::required("LSF_PHASE1_COMPARISON_OUTPUT");
    let observed = crate::standalone::RuntimeThreads::default();
    let invocation = super::runtime(2, &observed.invocation);
    let control = super::runtime(1, &observed.control);
    let result = invocation.block_on(async {
        Box::pin(tokio::time::timeout(
            plan.duration(),
            run(
                &plan,
                &directory,
                &identity,
                fixture,
                control.handle().clone(),
                crate::standalone::RuntimeThreads {
                    invocation: observed.invocation.clone(),
                    control: observed.control.clone(),
                },
                origin,
            ),
        ))
        .await
        .expect("comparison wall deadline")
    });
    drop(invocation);
    drop(control);
    assert_eq!(observed.invocation.load(Ordering::Acquire), 0);
    assert_eq!(observed.control.load(Ordering::Acquire), 0);
    result.unwrap();
}

async fn run(
    plan: &Plan,
    directory: &Path,
    identity: &Value,
    fixture: Fixture,
    control: tokio::runtime::Handle,
    threads: crate::standalone::RuntimeThreads,
    origin: Instant,
) -> Result<()> {
    let data = tempfile::Builder::new()
        .prefix("paired-node-")
        .tempdir_in(super::required("LSF_PHASE1_COMPARISON_DATA_ROOT"))?;
    let mut node = Box::pin(Node::start(
        plan,
        data.path(),
        fixture,
        control,
        threads,
        origin,
    ))
    .await?;
    let setup = prepare(&mut node, directory).await;
    let (prepared, preparation, setup_error) = match setup {
        Ok((prepared, preparation)) => (Some(prepared), preparation, None),
        Err(error) => (None, Value::Null, Some(error)),
    };
    let header = json!({"schema":"latent.phase1.paired-arm.v1","arm":"candidate","profile":plan.profile,
        "warmup_samples":plan.warmup_samples.to_string(),"measured_samples":plan.measured_samples.to_string(),
        "plan":plan,"identity":identity,"semantic_input":evidence::input(),"semantic_output":evidence::input(),
        "effective_options":evidence::options(&node),"configuration":node.config,"startup":node.startup,
        "preparation_elapsed_micros":preparation["elapsed_micros"],"artifact":preparation["artifact"],
        "preparation_scope":"repository-acquisition-including-verified-refill",
        "publication":preparation["publication"],"preparation_cache_before":preparation["cache_before"],
        "preparation_cache_after":preparation["cache_after"]});
    let mut writer = Writer::new(directory, &header)?;
    let result = if let Some(error) = setup_error {
        Err(error)
    } else {
        invoke_population(&mut node, &mut writer, plan).await
    };
    let release = release(&node, prepared).await;
    let after_release = node.sample("after-prepared-release")?;
    let work = node.work;
    let shutdown = node.shutdown().await?;
    data.close()?;
    let clean = shutdown.clean
        && shutdown.telemetry_flushed
        && shutdown.epoch_helper_joined
        && shutdown.quarantined_cells == 0;
    let passed = result.is_ok() && release.is_ok() && clean;
    writer.finish(&json!({"status":if passed {"passed"} else {"failed"},
        "reason":(!passed).then_some("comparison-workload-failed"),
        "elapsed_micros":origin.elapsed().as_micros().to_string(),"work":work,"shutdown":shutdown,
        "data_cleanup":{"removed":true},"prepared_release_elapsed_micros":release.as_ref().ok(),
        "after_release":after_release}))?;
    result?;
    release?;
    if !clean {
        return Err("comparison shutdown not clean".into());
    }
    Ok(())
}

async fn prepare(node: &mut Node, directory: &Path) -> Result<(PreparedComponent, Value)> {
    let publication = node.publish().await?;
    // Fetch the stored descriptor used by real activation materialization;
    // reference/metadata normalization are part of preparation identity.
    let artifact = node.published().await?;
    let identity = evidence::artifact(directory, &node.fixture, &artifact)?;
    let backend = &node.owner.backend;
    let key = backend
        .preparation_key(&artifact.descriptor.release_digest)
        .map_err(platform)?;
    let before = backend.cache_snapshot();
    let started = Instant::now();
    let activation = backend
        .prepare_from_repository(node.artifacts.as_ref(), &key)
        .await
        .map_err(|error| {
            std::io::Error::other(format!(
                "comparison initial preparation failed: {:?}",
                error.code
            ))
        })?;
    let prepared = activation.prepared.descriptor().clone();
    drop(activation);
    let elapsed = started.elapsed().as_micros().to_string();
    let after = backend.cache_snapshot();
    if before.entries != 0
        || before.misses != 0
        || after.entries != 1
        || after.misses != 1
        || after.hits != 0
    {
        return Err("comparison preparation did not start engine-cold".into());
    }
    Ok((
        prepared,
        json!({"elapsed_micros":elapsed,"artifact":identity,"publication":publication,
        "cache_before":cache(&before),"cache_after":cache(&after)}),
    ))
}

async fn invoke_population(node: &mut Node, writer: &mut Writer, plan: &Plan) -> Result<()> {
    for iteration in 0..plan.count() {
        call::run(node, writer, iteration).await?;
    }
    if node.work.invoke_attempts != u64::from(plan.count())
        || node.work.commands != node.maximum_commands
        || node.work.budget_exhausted
    {
        return Err("comparison exact work count mismatch".into());
    }
    Ok(())
}

async fn release(node: &Node, prepared: Option<PreparedComponent>) -> Result<String> {
    let prepared = prepared.ok_or("comparison had no successful preparation")?;
    let started = Instant::now();
    node.owner
        .backend
        .release(prepared)
        .await
        .map_err(platform)?;
    let elapsed = started.elapsed().as_micros().to_string();
    if node.owner.backend.cache_snapshot().entries != 0 {
        return Err("comparison explicit release retained cache entry".into());
    }
    super::soak::assert_idle(&node.sample("after-release-check")?)?;
    Ok(elapsed)
}

fn cache(value: &latent_wasmtime::PreparedCacheSnapshot) -> Value {
    json!({"entries":value.entries.to_string(),"hits":value.hits.to_string(),"misses":value.misses.to_string(),
        "evictions":value.evictions.to_string(),"invalidations":value.invalidations.to_string(),
        "source_bytes":value.source_bytes.to_string(),"metadata_bytes":value.metadata_bytes.to_string(),
        "compiled_image_bytes":value.compiled_image_bytes.to_string(),"preparing":value.preparing.to_string()})
}

//! Shared current/current diagnostic: the first real RPC warms the cache.
//!
//! This deliberately has its own schema and collector name. The historical
//! comparison's manual preparation and release are not part of this method.

use std::path::Path;
use std::sync::atomic::Ordering;
use std::time::Instant;

use serde_json::{json, Value};

use super::super::{fixtures::Fixture, Result};
use super::{call, evidence, node::Node, plan::Plan, writer::Writer};

#[test]
#[ignore = "explicit bounded revision runner supplies exact sources and plan"]
fn phase1_revision_backend_collector() {
    let origin = Instant::now();
    let plan: Plan = serde_json::from_slice(
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
    let mut fixture = Fixture::echo().unwrap();
    fixture
        .artifact
        .manifest
        .execution
        .resource_budget_ceiling
        .memory_bytes = 16_777_216;
    fixture.deployment.resources.memory_bytes = 16_777_216;
    evidence::validate_identity(&identity, &fixture).unwrap();
    let directory = super::super::required("LSF_PHASE1_COMPARISON_OUTPUT");
    let observed = crate::standalone::RuntimeThreads::default();
    let invocation = super::super::runtime(2, &observed.invocation);
    let control = super::super::runtime(1, &observed.control);
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
        .expect("revision diagnostic wall deadline")
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
        .prefix("revision-backend-")
        .tempdir_in(super::super::required("LSF_PHASE1_COMPARISON_DATA_ROOT"))?;
    let mut node = Box::pin(Node::start(
        plan,
        data.path(),
        fixture,
        control,
        threads,
        origin,
    ))
    .await?;
    let setup = async {
        let publication = node.publish().await?;
        let artifact = node.published().await?;
        let artifact = evidence::artifact(directory, &node.fixture, &artifact)?;
        let cache = node.owner.backend.cache_snapshot();
        if cache.entries != 0 || cache.misses != 0 || cache.hits != 0 {
            return Err("revision diagnostic did not start with an empty cache".into());
        }
        Ok::<_, Box<dyn std::error::Error + Send + Sync>>((
            publication,
            artifact,
            super::cache(&cache),
        ))
    }
    .await;
    let (publication, artifact, cache, setup_error) = match setup {
        Ok((publication, artifact, cache)) => (publication, artifact, cache, None),
        Err(error) => (Value::Null, Value::Null, Value::Null, Some(error)),
    };
    let header = json!({
        "schema":"latent.optimization.backend-revision-arm.v1", "arm":"lsf", "profile":plan.profile,
        "warmup_samples":plan.warmup_samples.to_string(), "measured_samples":plan.measured_samples.to_string(),
        "plan":plan, "identity":identity, "semantic_input":evidence::input(), "semantic_output":evidence::input(),
        "effective_options":evidence::options(&node), "configuration":node.config, "startup":node.startup,
        "artifact":artifact, "publication":publication, "preparation_cache_before":cache,
        "warmup_method":"first-rpc-empty-cache-in-declared-warmup"
    });
    let mut writer = Writer::new(directory, &header)?;
    let result = if let Some(error) = setup_error {
        Err(error)
    } else {
        async {
            for iteration in 0..plan.count() {
                call::run_with_cold_start(&mut node, &mut writer, iteration, iteration == 0)
                    .await?;
            }
            Ok(())
        }
        .await
    };
    let before_shutdown = node.sample("before-revision-shutdown")?;
    let work = node.work;
    let shutdown = node.shutdown().await?;
    data.close()?;
    let clean = shutdown.clean
        && shutdown.telemetry_flushed
        && shutdown.epoch_helper_joined
        && shutdown.quarantined_cells == 0;
    let passed = result.is_ok() && clean;
    writer.finish(&json!({"status":if passed {"passed"} else {"failed"},
        "reason":(!passed).then_some("revision-diagnostic-failed"),
        "elapsed_micros":origin.elapsed().as_micros().to_string(), "work":work,
        "shutdown":shutdown, "data_cleanup":{"removed":true}, "before_shutdown":before_shutdown}))?;
    result?;
    if !clean {
        return Err("revision diagnostic shutdown not clean".into());
    }
    Ok(())
}

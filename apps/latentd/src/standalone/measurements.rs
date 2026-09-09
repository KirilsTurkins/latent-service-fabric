//! Explicit measurement collector; ordinary workspace tests never run workloads.
mod benchmark;
mod comparison;
mod fixture_inputs;
mod fixtures;
mod identity;
mod node;
mod plan;
mod scale;
mod soak;
mod writer;

use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Instant;

use serde_json::{json, Value};

pub use node::MeasurementNode;
pub use plan::{MeasurementPlan, Profile, Workload};
pub use writer::MeasurementWriter;

pub type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

pub fn platform(error: latent_core::PlatformError) -> Box<dyn std::error::Error + Send + Sync> {
    let message = format!("measurement platform error: {:?}", error.code);
    // Consume the original diagnostic without retaining arbitrary payload details.
    drop(error);
    std::io::Error::other(message).into()
}

#[test]
#[ignore = "explicit smoke/full measurement runner supplies bounded plan and prebuilt fixtures"]
fn phase1_measurement_collector() {
    let origin = Instant::now();
    let plan_path = required("LSF_PHASE1_MEASUREMENT_PLAN");
    let identity_path = required("LSF_PHASE1_MEASUREMENT_IDENTITY");
    let directory = required("LSF_PHASE1_MEASUREMENT_OUTPUT");
    let plan: MeasurementPlan =
        serde_json::from_slice(&read(&plan_path, 64 * 1024).unwrap()).unwrap();
    plan.validate().unwrap();
    let identity: Value =
        serde_json::from_slice(&read(&identity_path, 1024 * 1024).unwrap()).unwrap();
    let fixtures = fixtures::Fixtures::load().unwrap();
    identity::validate_components(
        &identity,
        [
            ("echo", fixtures.echo.artifact.component_bytes.as_slice()),
            (
                "generic",
                fixtures.generic.artifact.component_bytes.as_slice(),
            ),
            (
                "capabilities",
                fixtures.capabilities.artifact.component_bytes.as_slice(),
            ),
        ],
    )
    .unwrap();
    let observed = super::RuntimeThreads::default();
    let invocation = runtime(2, &observed.invocation);
    let control = runtime(1, &observed.control);
    let result = invocation.block_on(async {
        Box::pin(tokio::time::timeout(
            plan.duration(),
            run(
                plan,
                &directory,
                identity,
                fixtures,
                control.handle().clone(),
                super::RuntimeThreads {
                    invocation: observed.invocation.clone(),
                    control: observed.control.clone(),
                },
                origin,
            ),
        ))
        .await
        .expect("measurement plan wall deadline")
    });
    drop(invocation);
    drop(control);
    assert_eq!(observed.invocation.load(Ordering::Acquire), 0);
    assert_eq!(observed.control.load(Ordering::Acquire), 0);
    result.unwrap();
}

async fn run(
    plan: MeasurementPlan,
    directory: &Path,
    identity: Value,
    fixtures: fixtures::Fixtures,
    control: tokio::runtime::Handle,
    threads: super::RuntimeThreads,
    origin: Instant,
) -> Result<()> {
    let data_root = required("LSF_PHASE1_MEASUREMENT_DATA_ROOT");
    let data = tempfile::Builder::new()
        .prefix("owned-node-")
        .tempdir_in(data_root)?;
    let (node, config) = Box::pin(MeasurementNode::start(
        plan.clone(),
        data.path(),
        control,
        threads,
        fixtures,
        origin,
    ))
    .await?;
    let header = json!({"profile":plan.profile,"workload":plan.kind,"repetition":plan.repetition.to_string(),
        "plan":plan,"config":config,"identity":identity});
    let mut writer = MeasurementWriter::new(directory, plan.maximum_output_bytes, &header, origin)?;
    writer.write("startup", &node.startup)?;
    fixture_inputs::write(directory, &node.fixtures, &mut writer)?;
    let result = match plan.kind {
        Workload::Scale => scale::run(&node, &plan, &mut writer).await,
        Workload::Soak => soak::run(&node, &plan, &mut writer).await,
        Workload::Benchmark => Box::pin(benchmark::run(&node, &plan, &mut writer)).await,
    };
    let work = serde_json::to_value(node.work())?;
    let shutdown = Box::pin(node.shutdown()).await?;
    data.close()?;
    writer.write("data-cleanup", &json!({"removed":true}))?;
    let clean = shutdown.clean && shutdown.telemetry_flushed && shutdown.epoch_helper_joined;
    let status = if result.is_ok() && clean {
        "passed"
    } else {
        "failed"
    };
    let reason = (status != "passed").then_some("measurement-workload-failed");
    let outcome = result.as_ref().map_or(Value::Null, Clone::clone);
    writer.finish(
        directory,
        status,
        reason,
        &serde_json::to_value(shutdown)?,
        &work,
        &outcome,
    )?;
    if !clean {
        return Err(std::io::Error::other("measurement shutdown not clean").into());
    }
    result.map(|_| ())
}

fn runtime(workers: usize, observed: &Arc<AtomicUsize>) -> tokio::runtime::Runtime {
    let started = observed.clone();
    let stopped = observed.clone();
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(workers)
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

fn required(name: &str) -> PathBuf {
    std::env::var_os(name)
        .map(PathBuf::from)
        .expect("required measurement path")
}

fn read(path: &Path, maximum: usize) -> Result<Vec<u8>> {
    let mut bytes = Vec::new();
    std::fs::File::open(path)?
        .take(u64::try_from(maximum).unwrap() + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > maximum {
        return Err(std::io::Error::other("measurement input byte limit").into());
    }
    Ok(bytes)
}

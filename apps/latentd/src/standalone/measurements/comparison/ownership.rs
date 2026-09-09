//! Common current/current ownership collector; never selected by ordinary tests.
mod call;
mod collector;
mod config;
mod context;
mod files;
mod fixtures;
mod generation;
mod observation;
mod plan;
mod proof;
mod request;

use std::path::PathBuf;
use std::sync::atomic::Ordering;
use std::time::{Duration, Instant};

use latent_artifacts::content_digest;
use serde_json::{json, Value};

use super::super::platform;
use super::{Result, Writer};
use plan::Plan;

const MEDIA: &str = "application/vnd.latent.wit-values.v1+json";

#[test]
#[ignore = "explicit exact-reference ownership runner supplies immutable fixtures and bounded plan"]
fn phase1_ownership_collector() {
    execute().unwrap();
}

fn execute() -> Result<()> {
    let origin = Instant::now();
    let plan_path = required("LSF_PHASE1_COMPARISON_PLAN")?;
    let identity_path = required("LSF_PHASE1_COMPARISON_IDENTITY")?;
    let fixture_path = required("LSF_OWNERSHIP_FIXTURES")?;
    let directory = required("LSF_PHASE1_COMPARISON_OUTPUT")?.canonicalize()?;
    let root = fixture_path
        .parent()
        .ok_or("ownership fixture root")?
        .canonicalize()?;
    if !directory.starts_with(&root) {
        return Err("ownership output must remain within retained root".into());
    }
    let plan: Plan = serde_json::from_slice(&files::read(&plan_path, 64 * 1024)?)?;
    plan.validate()?;
    let identity: Value = serde_json::from_slice(&files::read(&identity_path, 1024 * 1024)?)?;
    let input = files::read(&fixture_path, 1024 * 1024)?;
    let threads = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let runtime = super::super::runtime(2, &threads);
    let result = runtime.block_on(async {
        Box::pin(tokio::time::timeout(
            plan.duration(),
            collector::run(&plan, &identity, &root, &directory, &input, origin),
        ))
        .await
        .map_err(|_| "ownership collector watchdog")?
    });
    drop(runtime);
    let mut completed = result?;
    completed.footer["runtime_threads_after_join"] = json!(threads.load(Ordering::Acquire));
    completed.passed &= threads.load(Ordering::Acquire) == 0;
    completed.footer["status"] = json!(if completed.passed { "passed" } else { "failed" });
    completed.footer["reason"] = json!((!completed.passed).then_some("ownership-collector-failed"));
    completed.writer.finish(&completed.footer)?;
    let raw_path = directory.join("ownership.json");
    let raw = files::read(&raw_path, 8 * 1024 * 1024)?;
    let reference = files::Reference {
        path: raw_path
            .strip_prefix(&root)?
            .to_str()
            .ok_or("ownership raw path")?
            .replace('\\', "/"),
        sha256: content_digest(&raw).0,
        bytes: raw.len().to_string(),
    };
    if completed.passed {
        if let Some(generated) = completed.generated {
            generated.finish(&root, reference.clone())?;
        }
    }
    files::emit(
        &json!({"schema":"latent.optimization.ownership-complete.v1","event":"measurement-complete",
        "process_id":std::process::id(),"mode":plan.mode,"plan_sha256":content_digest(&files::read(&plan_path,64*1024)?).0,
        "identity_sha256":content_digest(&files::read(&identity_path,1024*1024)?).0,
        "raw":reference,"outcome":if completed.passed {"passed"}else{"failed"},"elapsed_nanos":observation::elapsed(origin),
        "observation_hold_millis":100}),
    )?;
    std::thread::sleep(Duration::from_millis(100));
    if !completed.passed {
        return Err("ownership diagnostic did not pass".into());
    }
    Ok(())
}

fn required(name: &str) -> Result<PathBuf> {
    let path = PathBuf::from(std::env::var_os(name).ok_or("ownership required input missing")?);
    if !path.is_absolute() {
        return Err("ownership input path must be absolute".into());
    }
    Ok(path)
}

fn ready(plan: &Plan, _identity: &Value, input: &[u8], origin: Instant) -> Result<()> {
    files::emit(
        &json!({"schema":"latent.optimization.ownership-ready.v1","event":"ready",
        "process_id":std::process::id(),"mode":plan.mode,
        "plan_sha256":content_digest(&files::read(&required("LSF_PHASE1_COMPARISON_PLAN")?,64*1024)?).0,
        "identity_sha256":content_digest(&files::read(&required("LSF_PHASE1_COMPARISON_IDENTITY")?,1024*1024)?).0,
        "fixture_manifest_sha256":content_digest(input).0,"elapsed_nanos":observation::elapsed(origin),"observation_hold_millis":100}),
    )
}

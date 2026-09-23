//! Research observer using LSF's actual factory, compiler profile and containment.
//! No additional Wasmtime feature, provider, signature bypass or runtime is installed.
#[path = "../../crates/latent-wasmtime/tests/generic_backend/support.rs"]
#[allow(dead_code)]
mod support;

use std::fs;
use std::io::{Read, Write};
use std::path::Path;
use std::process::ExitCode;
use std::time::{Duration, Instant};

use latent_core::{ContractId, PlatformError};
use latent_executor::{ExecutionBackend, ExecutionCleanup, GuestOutcome};
use latent_wasmtime::{WasmtimeBackend, WasmtimeComponentEngineFactory, WasmtimeConfig};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

const CONTRACT: &str = "latent:java-probe/probe@1.0.0";
const MEMORY: u64 = 64 * 1024 * 1024;

fn resources(backend: &WasmtimeBackend) -> Value {
    let value = backend.resource_snapshot();
    json!({
        "activeInvocations": value.active_invocations,
        "liveStores": value.live_stores,
        "liveHostStates": value.live_host_states,
        "liveComponentInstances": value.live_component_instances,
        "liveTemporaryBuffers": value.live_temporary_buffers,
        "liveCancellationProbes": value.live_cancellation_probes,
        "storesCreated": value.stores_created,
    })
}

fn failure(error: &PlatformError) -> Value {
    json!({"code": error.code.wire_code(), "message": error.message,
           "retryable": error.retryable})
}

async fn observe(bytes: Vec<u8>, receipt: &mut Value) {
    let config = WasmtimeConfig {
        maximum_memory_bytes: MEMORY,
        maximum_fuel: support::MAX_FUEL,
        ..WasmtimeConfig::default()
    };
    let factory = match WasmtimeComponentEngineFactory::new(config) {
        Ok(value) => value,
        Err(error) => {
            receipt["status"] = json!("factory-error");
            receipt["error"] = failure(&error);
            return;
        }
    };
    let backend = factory.create_backend_instance();
    let mut artifact = support::artifact_bytes(bytes, &[CONTRACT]);
    artifact.manifest.world = ContractId("latent:java-probe/capsule@1.0.0".into());
    artifact.manifest.minimum_fabric_version = env!("CARGO_PKG_VERSION").into();
    artifact.manifest.execution.resource_budget_ceiling.memory_bytes = MEMORY;
    let started = Instant::now();
    let key = factory.preparation_key(artifact.descriptor.release_digest.clone());
    let prepared = tokio::time::timeout(
        Duration::from_secs(60),
        backend.prepare(&artifact, &key),
    )
    .await;
    receipt["preparationMillis"] = json!(started.elapsed().as_secs_f64() * 1000.0);
    receipt["afterPreparation"] = resources(&backend);
    let prepared = match prepared {
        Ok(Ok(value)) => value,
        Ok(Err(error)) => {
            receipt["status"] = json!("backend-rejected");
            receipt["error"] = failure(&error);
            return;
        }
        Err(_) => {
            receipt["status"] = json!("preparation-watchdog");
            return;
        }
    };
    receipt["status"] = json!("backend-executing");
    for (input, expected) in [(0_i64, -1_i64), (i64::MAX, i64::MIN),
                              (i64::MIN, i64::MIN), (-42, -42), (42, -43)] {
        let control = support::Cancellation::new(&format!("java-probe-{input}"));
        let mut budget = support::budget();
        budget.memory_bytes = MEMORY;
        budget.wall_time_limit_millis = Some(5000);
        let input_bytes = serde_json::to_vec(&json!([input.to_string()])).unwrap();
        let request = support::request(prepared.clone(), &control.id, CONTRACT,
                                       "run", &input_bytes, budget);
        let started = Instant::now();
        let report = tokio::time::timeout(
            Duration::from_secs(10),
            backend.invoke_contained(request, &control),
        )
        .await;
        let mut observation = json!({"input": input.to_string(),
            "expected": expected.to_string(), "elapsedMillis": started.elapsed().as_secs_f64() * 1000.0,
            "resourcesAfter": resources(&backend), "status": "not-returned"});
        match report {
            Ok(report) => {
                observation["cleanupReusable"] = json!(report.cleanup == ExecutionCleanup::Reusable);
                match report.outcome {
                    Ok(GuestOutcome::Returned { output, output_media_type, .. }) => {
                        let actual: Value = serde_json::from_slice(&output).unwrap();
                        observation["actual"] = actual.clone();
                        observation["status"] = json!(if output_media_type == support::MEDIA
                            && actual == json!([expected.to_string()])
                            && report.cleanup == ExecutionCleanup::Reusable { "passed" } else { "mismatch" });
                    }
                    Err(error) => observation["error"] = failure(&error),
                    Ok(other) => observation["outcome"] = json!(format!("{other:?}")),
                }
            }
            Err(_) => observation["status"] = json!("invocation-watchdog"),
        }
        let passed = observation["status"] == "passed";
        receipt["invocations"].as_array_mut().unwrap().push(observation);
        if !passed {
            receipt["status"] = json!("backend-invocation-failed");
            return;
        }
        support::idle(&backend);
    }
    receipt["status"] = json!("backend-probe-passed-not-language-qualification");
}

pub fn main() -> ExitCode {
    let args: Vec<_> = std::env::args_os().collect();
    if args.len() != 3 {
        eprintln!("Expected component.wasm and new receipt path");
        return ExitCode::from(3);
    }
    let mut receipt = json!({"formatVersion": 1, "qualification": "not-qualified",
        "scope": "actual-lsf-backend-not-signed-node-workflow", "status": "not-started",
        "wasmtime": latent_wasmtime::WASMTIME_VERSION, "invocations": [],
        "limits": {"linearMemoryBytes": MEMORY, "fuel": support::MAX_FUEL},
        "unmeasured": ["capability ownership", "declared WIT errors", "host exception heap",
            "signed admission", "deadline/cancellation matrix", "GC exhaustion", "complete fresh-state conformance"]});
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| -> std::io::Result<()> {
        let mut bytes = Vec::new();
        fs::File::open(&args[1])?.take(16 * 1024 * 1024 + 1).read_to_end(&mut bytes)?;
        if bytes.is_empty() || bytes.len() > 16 * 1024 * 1024 {
            return Err(std::io::Error::other("component size limit"));
        }
        receipt["componentSha256"] = json!(format!("{:x}", Sha256::digest(&bytes)));
        receipt["componentBytes"] = json!(bytes.len());
        let runtime = tokio::runtime::Builder::new_current_thread().enable_all().build()?;
        runtime.block_on(observe(bytes, &mut receipt));
        Ok(())
    }));
    match result {
        Ok(Ok(())) => {}
        Ok(Err(error)) => { receipt["status"] = json!("probe-environment-error"); receipt["error"] = json!(error.to_string()); }
        Err(_) => receipt["status"] = json!("probe-harness-panicked"),
    }
    let output = serde_json::to_vec_pretty(&receipt).unwrap();
    let written = fs::OpenOptions::new().write(true).create_new(true).open(Path::new(&args[2]))
        .and_then(|mut file| { file.write_all(&output)?; file.write_all(b"\n") });
    if let Err(error) = written {
        eprintln!("Could not preserve engine receipt: {error}");
        return ExitCode::from(3);
    }
    println!("{}", String::from_utf8_lossy(&output));
    // Even successful backend calls do not satisfy #548's complete language gate.
    ExitCode::from(2)
}

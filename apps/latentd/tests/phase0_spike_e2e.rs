use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

use serde_json::Value;
use sha2::{Digest as _, Sha256};
use tempfile::TempDir;

const EXIT_SUCCESS: i32 = 0;
const EXIT_DOMAIN_ERROR: i32 = 10;
const EXIT_TIMEOUT_OR_CANCELLED: i32 = 11;
const EXIT_GUEST_TRAP: i32 = 12;
const EXIT_INVALID_COMPONENT_OR_CONFIGURATION: i32 = 13;
const MAXIMUM_CONTAINMENT_FUEL: u64 = 1_000_000_000_000;
const MAXIMUM_CONTAINMENT_MEMORY: u64 = 32 * 1024 * 1024;

#[test]
#[ignore = "requires Rust Wasm targets, wasm-tools, Buf, and the contract-validation toolchain"]
fn executable_covers_success_failures_and_same_runtime_post_failure_recovery() {
    let root = repository_root();
    let fixtures = fixture_paths(&root);
    let temporary = TempDir::new().expect("temporary fixture directory must be created");
    let containment_capsule = stage_capsule(
        &fixtures.echo_capsule,
        &fixtures.containment_component,
        temporary.path().join("containment"),
        MAXIMUM_CONTAINMENT_FUEL,
        MAXIMUM_CONTAINMENT_MEMORY,
    );

    let success = invoke(
        &fixtures.echo_capsule,
        "hello through latentd",
        &["--runtime-workers", "2", "--pool-capacity", "2"],
    );
    assert_exit(&success.output, EXIT_SUCCESS);
    assert_eq!(success.document["outcome"], "success");
    assert_eq!(success.document["output"]["utf8"], "hello through latentd");
    assert_eq!(success.document["cell"]["disposition"], "released");
    assert!(!success.document["logs"]
        .as_array()
        .expect("logs must be an array")
        .is_empty());
    assert_fixed_and_clean(&success.document, 2, 2, 1);

    let domain_error = invoke(&fixtures.echo_capsule, "", &[]);
    assert_exit(&domain_error.output, EXIT_DOMAIN_ERROR);
    assert_eq!(domain_error.document["outcome"], "domain_error");
    assert_eq!(domain_error.document["error"]["kind"], "domain");
    assert_eq!(domain_error.document["error"]["code"], "empty-message");
    assert_eq!(domain_error.document["cell"]["disposition"], "released");
    assert_fixed_and_clean(&domain_error.document, 1, 1, 1);

    let timeout = invoke(
        &containment_capsule,
        "__latent_test_infinite",
        &[
            "--fuel",
            "1000000000000",
            "--memory-bytes",
            "16777216",
            "--timeout-ms",
            "25",
        ],
    );
    assert_exit(&timeout.output, EXIT_TIMEOUT_OR_CANCELLED);
    assert_eq!(timeout.document["outcome"], "timeout");
    assert_eq!(timeout.document["error"]["kind"], "platform");
    assert_eq!(timeout.document["error"]["code"], "deadline_exceeded");
    assert_eq!(timeout.document["cell"]["disposition"], "released");
    assert_fixed_and_clean(&timeout.document, 1, 1, 1);

    let trap = invoke(
        &containment_capsule,
        "__latent_test_trap",
        &["--fuel", "1000000000000", "--memory-bytes", "16777216"],
    );
    assert_exit(&trap.output, EXIT_GUEST_TRAP);
    assert_eq!(trap.document["outcome"], "trap");
    assert_eq!(trap.document["error"]["kind"], "platform");
    assert_eq!(trap.document["error"]["code"], "guest_trap");
    assert_eq!(trap.document["cell"]["disposition"], "released");
    assert_fixed_and_clean(&trap.document, 1, 1, 1);

    let cancelled = invoke(
        &containment_capsule,
        "__latent_test_infinite",
        &[
            "--fuel",
            "1000000000000",
            "--memory-bytes",
            "16777216",
            "--timeout-ms",
            "1000",
            "--cancel-after-ms",
            "5",
        ],
    );
    assert_exit(&cancelled.output, EXIT_TIMEOUT_OR_CANCELLED);
    assert_eq!(cancelled.document["outcome"], "cancelled");
    assert_eq!(cancelled.document["error"]["code"], "cancelled");
    assert_eq!(cancelled.document["cell"]["disposition"], "released");
    assert_fixed_and_clean(&cancelled.document, 1, 1, 1);

    let recovery = verify_recovery(
        &containment_capsule,
        "healthy after contained failures",
        &[
            "--pool-capacity",
            "1",
            "--fuel",
            "1000000000000",
            "--memory-bytes",
            "16777216",
            "--activation-id",
            "same-runtime-recovery",
        ],
    );
    assert_exit(&recovery.output, EXIT_SUCCESS);
    assert_eq!(
        recovery.document["surface"],
        "latentd.phase0-spike.verify-recovery"
    );
    assert_eq!(recovery.document["outcome"], "success");
    assert_eq!(
        recovery.document["output"]["utf8"],
        "healthy after contained failures"
    );
    let activations = recovery.document["recovery"]["activations"]
        .as_array()
        .expect("recovery report must expose both in-process activations");
    assert_eq!(activations.len(), 2);
    assert_eq!(activations[0]["phase"], "trap");
    assert_eq!(activations[0]["activation"]["outcome"], "trap");
    assert_eq!(activations[0]["activation"]["error"]["code"], "guest_trap");
    assert_released_capacity_one_cell(&activations[0]["activation"]);
    assert_eq!(activations[0]["runner"]["total_invocations"], 1);
    assert_eq!(activations[0]["prepared_cache"]["entries"], 1);
    assert_reclaimed_backend_resources(&activations[0]["backend_resources"]);

    assert_eq!(activations[1]["phase"], "recovery");
    assert_eq!(activations[1]["activation"]["outcome"], "success");
    assert_eq!(
        activations[1]["activation"]["output"]["utf8"],
        "healthy after contained failures"
    );
    assert_released_capacity_one_cell(&activations[1]["activation"]);
    assert_eq!(activations[1]["runner"]["total_invocations"], 2);
    assert_eq!(activations[1]["prepared_cache"]["entries"], 1);
    assert_reclaimed_backend_resources(&activations[1]["backend_resources"]);
    assert_fixed_and_clean(&recovery.document, 1, 1, 2);

    let invalid_component = temporary.path().join("invalid-component.wasm");
    fs::write(&invalid_component, [0_u8, 1, 2, 3])
        .expect("invalid component fixture must be written");
    let invalid_capsule = stage_capsule(
        &fixtures.echo_capsule,
        &invalid_component,
        temporary.path().join("invalid"),
        1_000_000,
        4 * 1024 * 1024,
    );
    let invalid = invoke(&invalid_capsule, "not invoked", &[]);
    assert_exit(&invalid.output, EXIT_INVALID_COMPONENT_OR_CONFIGURATION);
    assert_eq!(
        invalid.document["outcome"],
        "invalid_component_or_configuration"
    );
    assert_eq!(invalid.document["cell"]["disposition"], "not_leased");
    assert_eq!(invalid.document["cell"]["pool_after"]["active_leases"], 0);
    assert_fixed_and_clean(&invalid.document, 1, 1, 0);
}

struct Fixtures {
    echo_capsule: PathBuf,
    containment_component: PathBuf,
}

fn fixture_paths(root: &Path) -> Fixtures {
    let target = target_root(root);
    let echo_capsule = env::var_os("LSF_ECHO_CAPSULE")
        .map(PathBuf::from)
        .unwrap_or_else(|| target.join("capsules/echo/capsule.json"));
    let containment_component = env::var_os("LSF_CONTAINMENT_COMPONENT")
        .map(PathBuf::from)
        .unwrap_or_else(|| target.join("capsules/containment/containment-capsule.wasm"));

    if !echo_capsule.is_file() || !containment_component.is_file() {
        let status = Command::new(root.join("tools/validate_contracts.sh"))
            .current_dir(root)
            .status()
            .expect("contract validation gate must start");
        assert!(
            status.success(),
            "contract validation gate must build fixtures"
        );
    }

    assert!(echo_capsule.is_file(), "echo capsule must exist");
    assert!(
        containment_component.is_file(),
        "containment component must exist"
    );
    Fixtures {
        echo_capsule,
        containment_component,
    }
}

fn target_root(root: &Path) -> PathBuf {
    let configured = env::var_os("CARGO_TARGET_DIR").map(PathBuf::from);
    match configured {
        Some(path) if path.is_absolute() => path,
        Some(path) => root.join(path),
        None => root.join("target"),
    }
}

fn repository_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .expect("repository root must resolve")
}

fn stage_capsule(
    source_capsule: &Path,
    component: &Path,
    directory: PathBuf,
    cpu_fuel: u64,
    memory_bytes: u64,
) -> PathBuf {
    fs::create_dir_all(&directory).expect("staged capsule directory must be created");
    let component_name = component
        .file_name()
        .expect("component must have a file name")
        .to_owned();
    let staged_component = directory.join(&component_name);
    fs::copy(component, &staged_component).expect("component must be staged");
    let bytes = fs::read(&staged_component).expect("staged component must be readable");
    let digest = Sha256::digest(&bytes);
    let digest = format!(
        "sha256:{}",
        digest
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>()
    );

    let mut document: Value =
        serde_json::from_slice(&fs::read(source_capsule).expect("source capsule must be readable"))
            .expect("source capsule must be valid JSON");
    document["component"]["digest"] = Value::String(digest);
    document["execution"]["limits"]["cpuFuel"] = Value::from(cpu_fuel);
    document["execution"]["limits"]["memoryBytes"] = Value::from(memory_bytes);
    let annotations = document["metadata"]["annotations"]
        .as_object_mut()
        .expect("capsule annotations must be an object");
    annotations.insert(
        "latent.dev/artifact".to_owned(),
        Value::String(component_name.to_string_lossy().into_owned()),
    );

    let capsule = directory.join("capsule.json");
    fs::write(
        &capsule,
        serde_json::to_vec_pretty(&document).expect("capsule JSON must serialize"),
    )
    .expect("staged capsule must be written");
    capsule
}

struct Invocation {
    output: Output,
    document: Value,
}

fn invoke(capsule: &Path, input: &str, extra_arguments: &[&str]) -> Invocation {
    execute("invoke-once", capsule, input, extra_arguments)
}

fn verify_recovery(capsule: &Path, input: &str, extra_arguments: &[&str]) -> Invocation {
    execute("verify-recovery", capsule, input, extra_arguments)
}

fn execute(command: &str, capsule: &Path, input: &str, extra_arguments: &[&str]) -> Invocation {
    let output = Command::new(env!("CARGO_BIN_EXE_latentd"))
        .arg("phase0-spike")
        .arg(command)
        .arg("--capsule")
        .arg(capsule)
        .arg("--input")
        .arg(input)
        .args(extra_arguments)
        .output()
        .expect("latentd Phase 0 spike must start");
    let stdout = String::from_utf8(output.stdout.clone()).expect("stdout must be UTF-8 JSON");
    let lines = stdout.lines().collect::<Vec<_>>();
    assert_eq!(
        lines.len(),
        1,
        "machine stdout must contain exactly one JSON line: {stdout:?}"
    );
    let document = serde_json::from_str(lines[0]).expect("stdout must contain valid JSON");
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("not production-ready") && stderr.contains("not Phase 1 API compatible"),
        "stderr must carry the spike disclaimer: {stderr}"
    );
    Invocation { output, document }
}

fn assert_exit(output: &Output, expected: i32) {
    assert_eq!(
        output.status.code(),
        Some(expected),
        "unexpected exit status; stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
}

fn assert_fixed_and_clean(document: &Value, workers: u64, capacity: u64, activation_count: usize) {
    assert_eq!(document["schema_version"], "latent.phase0.spike.result.v1");
    assert_eq!(document["production_ready"], false);
    assert_eq!(document["phase1_api_compatible"], false);
    assert_eq!(document["topology"]["runtime_workers"], workers);
    assert_eq!(document["topology"]["pool_capacity"], capacity);
    assert_eq!(document["topology"]["listener_socket_count"], 0);
    let before = &document["topology"]["before_component_load"];
    assert_eq!(before["runtime_workers"], workers);
    assert_eq!(before["pool_capacity"], capacity);
    assert_eq!(before["listener_socket_count"], 0);
    let after = document["topology"]["after_activations"]
        .as_array()
        .expect("topology must expose raw post-activation observations");
    assert_eq!(after.len(), activation_count);
    for observation in after {
        assert_eq!(
            observation, before,
            "runtime worker, pool, or socket topology changed across an activation"
        );
    }
    assert_eq!(document["shutdown"]["clean"], true);
    assert_eq!(document["shutdown"]["runtime_stopped"], true);
    assert_eq!(document["shutdown"]["active_leases"], 0);
    assert_eq!(document["shutdown"]["queued_waiters"], 0);
    assert_eq!(document["shutdown"]["cancellation_registrations"], 0);
    assert_eq!(document["shutdown"]["running_invocations"], 0);
    assert_eq!(document["shutdown"]["retained_log_entries"], 0);
    assert_eq!(document["shutdown"]["prepared_cache_entries"], 0);
    assert_reclaimed_backend_resources(&document["shutdown"]["backend_resources"]);
}

fn assert_reclaimed_backend_resources(resources: &Value) {
    let resources = resources
        .as_object()
        .expect("backend resources must be an object");
    for (name, value) in resources {
        if name != "stores_created" {
            assert_eq!(value, 0, "backend resource {name} must be reclaimed");
        }
    }
}

fn assert_released_capacity_one_cell(activation: &Value) {
    assert_eq!(activation["cell"]["disposition"], "released");
    let after = &activation["cell"]["pool_after"];
    assert_eq!(after["capacity"], 1);
    assert_eq!(after["available"], 1);
    assert_eq!(after["active_leases"], 0);
    assert_eq!(after["queue_depth"], 0);
    assert_eq!(after["quarantined"], 0);
}

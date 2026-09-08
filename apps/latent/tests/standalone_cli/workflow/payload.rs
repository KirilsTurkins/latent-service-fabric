use std::fs;
use std::path::Path;

use serde_json::Value;

use super::super::process::{Process, WATCHDOG};
use super::{assert_payload, path, Harness, Package};

pub(super) fn assert_receipt_pin(value: &Value, route: &Value, digest: &str) {
    let pin = &value["data"]["resolvedRevision"];
    let snapshot = &route["data"]["snapshot"];
    assert_eq!(pin["releaseDigest"], digest);
    assert_eq!(pin["routeGeneration"], snapshot["generation"]);
    assert!(
        snapshot["services"]
            .as_array()
            .expect("published routes")
            .iter()
            .any(|service| {
                service["revisions"]
                    .as_array()
                    .expect("published revisions")
                    .iter()
                    .any(|revision| {
                        revision["revisionId"] == pin["revisionId"]
                            && revision["releaseDigest"] == pin["releaseDigest"]
                    })
            }),
        "receipt pin belongs to the exact published snapshot"
    );
}

pub(super) fn quiet_echo(harness: &Harness, package: &Package, input: &Path) -> Value {
    let mut command = harness.human_command(
        "caller",
        &[
            "invoke",
            "--service",
            package.service,
            "--contract",
            package.contract,
            "--function",
            "echo",
            "--input",
            path(input),
            "--activation-id",
            "cli-after-restart",
        ],
    );
    command.arg("--quiet");
    let output = Process::spawn(command, WATCHDOG).wait();
    assert_eq!(output.code, Some(0));
    assert!(output.stderr.is_empty());
    assert!(
        !output.stdout.is_empty(),
        "quiet mode preserves requested return data"
    );
    assert!(
        !output.stdout.contains('\u{1b}'),
        "human payload output contains no raw terminal escape"
    );
    let result: Value =
        serde_json::from_str(&output.stdout).expect("escaped human result document");
    assert_eq!(result["category"], "success");
    assert_eq!(result["data"]["activationId"], "cli-after-restart");
    result
}

pub(super) fn output_failure(
    harness: &Harness,
    package: &Package,
    input: &Path,
    destination: &Path,
) {
    let original = fs::read(destination).expect("existing output file");
    let result = harness.call(
        "caller",
        &[
            "invoke",
            "--service",
            package.service,
            "--contract",
            package.contract,
            "--function",
            "echo",
            "--input",
            path(input),
            "--activation-id",
            "cli-output-failure",
            "--payload-output",
            path(destination),
        ],
        2,
        "local-error",
    );
    assert_eq!(result["requestDispatched"], true);
    assert_eq!(result["outcomeKnown"], true);
    assert_eq!(result["data"]["remoteCompleted"], true);
    assert_eq!(result["data"]["activationId"], "cli-output-failure");
    assert!(!result["data"]["resolvedRevision"].is_null());
    assert_payload(&result, &serde_json::json!([{"ok":"hello\n\u{1b}[31m"}]));
    assert_eq!(
        fs::read(destination).expect("preserved output file"),
        original
    );
    let status = harness.call(
        "caller",
        &["activation", "get", "cli-output-failure"],
        0,
        "success",
    );
    assert_eq!(status["data"]["terminalState"], "completed");
}

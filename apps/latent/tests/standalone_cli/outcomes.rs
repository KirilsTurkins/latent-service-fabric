#[path = "outcomes/cleanup.rs"]
mod cleanup;
#[path = "outcomes/releases.rs"]
mod releases;

use std::thread;
use std::time::{Duration, Instant};

use base64::{engine::general_purpose::STANDARD, Engine};
use serde_json::{json, Value};

use super::process::{Process, WATCHDOG};
use super::support::{
    package::{path, Package, MEDIA},
    Harness,
};
use super::workflow::assert_payload;

#[test]
#[ignore = "requires prebuilt latentd and the generated generic component"]
fn cli_separates_domain_trap_deadline_and_cancel_results_then_recovers() {
    let package = Package::generic();
    let mut harness = Harness::start_with_cells(2);
    package.publish(&harness, "generic");
    releases::two_scoped_pages(&harness, &package);
    let deployment = package.deployment("generic");
    harness.call(
        "generic",
        &[
            "deployment",
            "apply",
            path(&deployment),
            "--expected-generation",
            "0",
        ],
        0,
        "success",
    );
    harness.ready();
    let empty = package.payload("empty.json", &json!([]));
    let denied = package.payload("denied.json", &json!([false]));
    let invoke =
        |function: &str, id: &str, input: &std::path::Path, extra: &[&str], code, category| {
            let mut args = arguments(&package, function, id, input);
            args.extend_from_slice(extra);
            harness.call("generic", &args, code, category)
        };
    let returned = invoke("identify", "generic-success", &empty, &[], 0, "success");
    assert_payload(&returned, &json!([11]));
    let domain = invoke(
        "checked",
        "generic-domain",
        &denied,
        &[],
        3,
        "declared-error",
    );
    assert_eq!(domain["data"]["declaredError"]["code"], "declared-error");
    let payload = &domain["data"]["declaredError"]["payload"];
    assert_eq!(payload["mediaType"], MEDIA);
    let bytes = STANDARD
        .decode(payload["data"].as_str().expect("domain payload"))
        .expect("base64 domain data");
    assert_eq!(
        serde_json::from_slice::<Value>(&bytes).expect("result array"),
        json!([{"err":{"case":"named","value":"denied"}}])
    );
    let trapped = invoke("trap", "generic-trap", &empty, &[], 4, "platform-failure");
    assert_eq!(trapped["error"]["code"], "guest-trap");
    assert_eq!(trapped["data"]["terminalState"], "guest_trap");
    assert!(!trapped.to_string().contains("wasm backtrace"));
    let deadline = invoke(
        "spin",
        "generic-deadline",
        &empty,
        &["--wall-time-ms", "80", "--cpu-fuel", "10000000000"],
        4,
        "platform-failure",
    );
    assert_eq!(deadline["error"]["code"], "deadline-exceeded");
    assert_eq!(deadline["data"]["terminalState"], "deadline_exceeded");
    cancel_running(&harness, &package, &empty);
    interrupt_cli(&harness, &package, &empty);
    let recovered = invoke("identify", "generic-recovered", &empty, &[], 0, "success");
    assert_payload(&recovered, &json!([11]));
    cleanup::assert_joined(&harness.stop_report());
}

fn arguments<'a>(
    package: &'a Package,
    function: &'a str,
    id: &'a str,
    input: &'a std::path::Path,
) -> Vec<&'a str> {
    vec![
        "invoke",
        "--service",
        package.service,
        "--contract",
        package.contract,
        "--function",
        function,
        "--input",
        path(input),
        "--activation-id",
        id,
    ]
}

fn cancel_running(harness: &Harness, package: &Package, input: &std::path::Path) {
    let id = "generic-cancel";
    let mut args = arguments(package, "spin", id, input);
    args.extend_from_slice(&["--wall-time-ms", "3000", "--cpu-fuel", "10000000000"]);
    let pending = Process::spawn(harness.command("generic", &args), WATCHDOG);
    wait_running(harness, id);
    let cancelled = harness.call(
        "generic",
        &[
            "activation",
            "cancel",
            id,
            "--reason",
            "cli test cancellation",
        ],
        0,
        "success",
    );
    assert_eq!(cancelled["data"]["disposition"], "accepted");
    let result = pending.wait().json(4, "platform-failure");
    assert_eq!(result["error"]["code"], "cancelled");
    let status = harness.call("generic", &["activation", "get", id], 0, "success");
    assert_eq!(status["data"]["terminalState"], "cancelled");
    let terminal = harness.call("generic", &["activation", "cancel", id], 0, "success");
    assert_eq!(terminal["data"]["disposition"], "already_terminal");
    assert_eq!(terminal["data"]["terminalState"], "cancelled");
    let absent = harness.call(
        "generic",
        &["activation", "cancel", "never-created"],
        6,
        "not-found",
    );
    assert_eq!(absent["data"]["disposition"], "not_found");
}

fn wait_running(harness: &Harness, id: &str) {
    let deadline = Instant::now()
        .checked_add(Duration::from_secs(2))
        .expect("running observation bound");
    let mut running = false;
    for _ in 0..20 {
        assert!(
            Instant::now() < deadline,
            "pending activation did not reach running"
        );
        let output = harness.run("generic", &["activation", "get", id]);
        if output.code == Some(0) {
            let status = output.json(0, "success");
            if status["data"]["phase"] == "running" && status["data"]["terminalState"].is_null() {
                running = true;
                break;
            }
            assert!(
                status["data"]["terminalState"].is_null(),
                "activation ended before cancellation"
            );
        } else {
            output.json(6, "not-found");
        }
        thread::sleep(Duration::from_millis(10));
    }
    assert!(running, "observed actual running state before cancellation");
}

fn interrupt_cli(harness: &Harness, package: &Package, input: &std::path::Path) {
    let id = "generic-client-interrupted";
    let mut args = arguments(package, "spin", id, input);
    args.extend_from_slice(&["--wall-time-ms", "3000", "--cpu-fuel", "10000000000"]);
    let pending = Process::spawn(harness.command("generic", &args), WATCHDOG);
    wait_running(harness, id);
    pending.signal("-INT");
    let interrupted = pending.wait().json(130, "interrupted");
    assert_eq!(interrupted["requestDispatched"], true);
    assert_eq!(interrupted["outcomeKnown"], false);
    assert_eq!(interrupted["data"]["activationId"], id);
    assert_eq!(interrupted["error"]["code"], "interrupted");
    assert!(
        interrupted["data"]["disposition"].is_null(),
        "client interrupt is not an accepted Cancel RPC"
    );
    let deadline = Instant::now()
        .checked_add(Duration::from_secs(2))
        .expect("manager cleanup watchdog");
    let mut terminal = false;
    for _ in 0..20 {
        assert!(
            Instant::now() < deadline,
            "server has not finalized the transferred owner"
        );
        let status = harness.call("generic", &["activation", "get", id], 0, "success");
        if status["data"]["terminalState"] == "cancelled" {
            terminal = true;
            break;
        }
        assert!(
            status["data"]["terminalState"].is_null(),
            "unexpected interrupted terminal state"
        );
        thread::sleep(Duration::from_millis(10));
    }
    assert!(
        terminal,
        "separate status recovers the original ID without reinvocation"
    );
    let inventory = cleanup::wait_idle(harness);
    let value = &inventory["data"]["inventory"];
    assert_eq!(value["cellCapacity"][0]["total"], 2);
    assert_eq!(
        value["cellCapacity"][0]["quarantined"], 0,
        "acknowledged native cleanup preserves both cells"
    );
    assert_eq!(value["cellCapacity"][0]["active"], 0);
    assert_eq!(
        value["cellCapacity"][0]["available"], 2,
        "the interrupted cell is reusable before the healthy follow-up"
    );
    assert_eq!(value["queueDepth"], "0");
    assert_eq!(value["cacheSummary"]["preparing"], "0");
    assert_eq!(value["quotas"]["usage"]["activeActivations"], 0);
    assert_eq!(value["quotas"]["usage"]["queuedActivations"], 0);
    assert_eq!(value["quotas"]["usage"]["reservedCpuFuel"], "0");
    assert_eq!(value["quotas"]["usage"]["reservedMemoryBytes"], "0");
}

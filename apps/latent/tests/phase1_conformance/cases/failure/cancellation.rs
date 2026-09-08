use crate::{
    evidence::Evidence,
    fixtures::Package,
    harness::{invoke_args, Harness},
};
use serde_json::{json, Value};
use std::time::Duration;

pub async fn cancel(harness: &mut Harness, evidence: &mut Evidence, package: &Package) {
    evidence.begin("cancellation");
    let id = "explicit-cancel";
    let empty = package.input("cancel.json", &json!([]));
    let mut args = invoke_args(package, "spin", id, &empty);
    args.extend_from_slice(&["--wall-time-ms", "3000", "--cpu-fuel", "10000000000"]);
    let pending = harness.spawn_cli("tests", &args);
    let running = wait_running(harness, id).await;
    let foreign = harness
        .call("examples", &["activation", "cancel", id], 6, "not-found")
        .await;
    let accepted = harness
        .call("tests", &["activation", "cancel", id], 0, "success")
        .await;
    assert_eq!(accepted["data"]["disposition"], "accepted");
    let response = harness.finish_cli(pending, 4, "platform-failure").await;
    assert_eq!(response["error"]["code"], "cancelled");
    let status = harness
        .call("tests", &["activation", "get", id], 0, "success")
        .await;
    assert_eq!(status["data"]["terminalState"], "cancelled");
    let terminal = harness
        .call("tests", &["activation", "cancel", id], 0, "success")
        .await;
    assert_eq!(terminal["data"]["disposition"], "already_terminal");
    assert_eq!(terminal["data"]["terminalState"], "cancelled");
    evidence.passed(
        harness,
        json!({"running":running,"foreign":foreign,"accepted":accepted,
        "response":response,"status":status,"terminal":terminal}),
    );
}

async fn wait_running(harness: &mut Harness, id: &str) -> Value {
    for _ in 0..20 {
        // The owner may not yet be registered; every poll is a separately counted
        // Status command, and never a repeated Invoke attempt.
        let pending = harness.spawn_cli("tests", &["activation", "get", id]);
        let status = harness.finish_status_poll(pending).await;
        if let Some(value) = status {
            assert!(
                value["data"]["terminalState"].is_null(),
                "cancel target ended prematurely"
            );
            if value["data"]["phase"] == "running" {
                return value;
            }
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    panic!("did not observe actual running activation within bounded Status polls");
}

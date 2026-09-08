#[path = "failure/cancellation.rs"]
mod cancellation;

use super::{decode_payload, payload, unsigned};
use crate::{evidence::Evidence, fixtures::Package, harness::Harness};
pub use cancellation::cancel;
use serde_json::json;

pub async fn mixed(harness: &mut Harness, evidence: &mut Evidence, package: &Package) {
    evidence.begin("mixed-outcomes");
    let combine = package.input("combine.json", &json!([-4, 9]));
    let success = harness
        .invoke(
            package,
            "combine",
            "mixed-success",
            &combine,
            &[],
            (0, "success"),
        )
        .await;
    assert_eq!(payload(&success), json!([5]));
    let denied = package.input("denied.json", &json!([false]));
    let domain = harness
        .invoke(
            package,
            "checked",
            "mixed-domain",
            &denied,
            &[],
            (3, "declared-error"),
        )
        .await;
    assert_eq!(domain["data"]["declaredError"]["code"], "declared-error");
    assert_eq!(
        decode_payload(&domain["data"]["declaredError"]["payload"]),
        json!([{"err":{"case":"named","value":"denied"}}])
    );
    let empty = package.input("trap.json", &json!([]));
    let trapped = harness
        .invoke(
            package,
            "trap",
            "mixed-trap",
            &empty,
            &[],
            (4, "platform-failure"),
        )
        .await;
    assert_eq!(trapped["error"]["code"], "guest-trap");
    assert_eq!(trapped["data"]["terminalState"], "guest_trap");
    assert!(!trapped.to_string().contains("wasm backtrace"));
    evidence.passed(
        harness,
        json!({"success":success,"declared":domain,"trap":trapped}),
    );
}

pub async fn deadline(harness: &mut Harness, evidence: &mut Evidence, package: &Package) {
    evidence.begin("deadline");
    let empty = package.input("deadline.json", &json!([]));
    let response = harness
        .invoke(
            package,
            "spin",
            "bounded-deadline",
            &empty,
            &["--wall-time-ms", "80", "--cpu-fuel", "10000000000"],
            (4, "platform-failure"),
        )
        .await;
    assert_eq!(response["error"]["code"], "deadline-exceeded");
    assert_eq!(response["data"]["terminalState"], "deadline_exceeded");
    let status = harness
        .call(
            "tests",
            &["activation", "get", "bounded-deadline"],
            0,
            "success",
        )
        .await;
    assert_eq!(status["data"]["terminalState"], "deadline_exceeded");
    evidence.passed(harness, json!({"response":response,"status":status}));
}

pub async fn malformed(harness: &mut Harness, evidence: &mut Evidence, package: &Package) {
    evidence.begin("malformed-input");
    let input = package.input("malformed.json", &json!(["not-an-s32", 1]));
    let response = harness
        .invoke(
            package,
            "combine",
            "malformed",
            &input,
            &[],
            (4, "platform-failure"),
        )
        .await;
    assert_eq!(response["error"]["code"], "invalid-argument");
    assert!(response["data"]["payload"].is_null());
    assert_eq!(response["data"]["consumption"]["cpuFuel"], "0");
    assert_eq!(response["data"]["consumption"]["peakMemoryBytes"], "0");
    evidence.passed(
        harness,
        json!({"response":response,"malformation":"string-in-s32-parameter"}),
    );
}

pub async fn memory(harness: &mut Harness, evidence: &mut Evidence, package: &Package) {
    evidence.begin("memory-budget");
    let empty = package.input("memory.json", &json!([]));
    let response = harness
        .invoke(
            package,
            "grow",
            "memory-limited",
            &empty,
            &[
                "--memory-bytes",
                "4194304",
                "--cpu-fuel",
                "100000000",
                "--wall-time-ms",
                "1000",
            ],
            (4, "platform-failure"),
        )
        .await;
    assert_eq!(response["error"]["code"], "resource-exhausted");
    let consumed = unsigned(&response["data"]["consumption"]["peakMemoryBytes"]);
    assert!(consumed > 0 && consumed <= 4 * 1024 * 1024);
    evidence.passed(
        harness,
        json!({"response":response,"memoryCeilingBytes":"4194304"}),
    );
}

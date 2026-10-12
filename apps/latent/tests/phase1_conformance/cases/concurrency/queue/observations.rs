use crate::{
    fixtures::Package,
    harness::{Harness, PendingCli},
};
use serde_json::Value;
use std::path::Path;

pub(super) fn assert_full(inventory: &Value) {
    assert_eq!(inventory["cellCapacity"][0]["total"], 2);
    assert_eq!(inventory["cellCapacity"][0]["active"], 2);
    assert_eq!(inventory["cellCapacity"][0]["available"], 0);
    assert_eq!(inventory["cellCapacity"][0]["queueDepth"], 3);
    assert_eq!(inventory["cellCapacity"][0]["queuedTenants"], 2);
    assert_eq!(inventory["queueDepth"], "3");
    assert_eq!(inventory["quotas"]["usage"]["activeActivations"], 5);
    assert_eq!(inventory["quotas"]["usage"]["queuedActivations"], 3);
}

pub(super) async fn overflow(
    harness: &mut Harness,
    package: &Package,
    input: &Path,
) -> (Value, Value) {
    let response = harness
        .invoke(
            package,
            "identify",
            "queue-overflow",
            input,
            &[],
            (4, "platform-failure"),
        )
        .await;
    assert_eq!(response["error"]["code"], "resource-exhausted");
    assert_eq!(response["requestDispatched"], true);
    assert_eq!(response["outcomeKnown"], true);
    assert_eq!(response["data"]["terminalState"], "resource_exhausted");
    let consumption = response["data"]["consumption"]
        .as_object()
        .expect("bounded refusal consumption");
    assert_eq!(consumption.len(), 11);
    assert!(consumption
        .values()
        .all(|value| value.as_u64() == Some(0) || value.as_str() == Some("0")));
    // The existing retention allowance covers one transient refusal record.
    // Admission stays full, while this terminal root proves zero guest work.
    let status = harness
        .call(
            "tests",
            &["activation", "get", "queue-overflow"],
            0,
            "success",
        )
        .await;
    assert_eq!(status["data"]["terminalState"], "resource_exhausted");
    assert_eq!(
        status["data"]["finalConsumption"],
        response["data"]["consumption"]
    );
    (response, status)
}

pub(super) async fn cancelled(harness: &mut Harness, pending: PendingCli) -> Value {
    let response = harness.finish_cli(pending, 4, "platform-failure").await;
    assert_eq!(response["error"]["code"], "cancelled");
    response
}

pub(super) async fn statuses(harness: &mut Harness, responses: [&Value; 3]) -> Vec<Value> {
    let mut statuses = Vec::new();
    for ((profile, id, terminal), response) in [
        ("tests", "queued-tests-first", "cancelled"),
        ("tests", "queued-tests-second", "cancelled"),
        ("examples", "queued-examples", "completed"),
    ]
    .into_iter()
    .zip(responses)
    {
        let status = harness
            .call(profile, &["activation", "get", id], 0, "success")
            .await;
        assert_eq!(status["data"]["terminalState"], terminal);
        assert_eq!(
            status["data"]["finalConsumption"],
            response["data"]["consumption"]
        );
        statuses.push(status);
    }
    statuses
}

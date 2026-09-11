use crate::{
    cases::{payload, unsigned},
    fixtures::Package,
    harness::Harness,
};
use serde_json::{json, Value};
use std::{
    path::Path,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

pub(super) async fn snapshot(
    harness: &mut Harness,
    package: &Package,
    input: &Path,
    id: &str,
    absolute: Option<u64>,
) -> Value {
    let deadline = absolute.map(|value| value.to_string());
    // The caller requests the full 5s node limit; the deployment's later 1s
    // ceiling must shorten it. RPC validation also bounds caller wall budgets
    // at the node's advertised limit, so equal caps are intentional here.
    let mut extra = vec!["--wall-time-ms", "5000"];
    if let Some(value) = deadline.as_deref() {
        extra.extend_from_slice(&["--deadline-unix-millis", value]);
    }
    let before = unix_millis();
    let response = harness
        .invoke(package, "snapshot", id, input, &extra, (0, "success"))
        .await;
    let after = unix_millis();
    assert!(
        after >= before,
        "wall clock remains ordered within this tiny call"
    );
    let decoded = payload(&response);
    assert_eq!(decoded[0]["activation"], id);
    let effective = unsigned(&decoded[0]["deadline"]["some"]);
    let remaining = unsigned(&decoded[0]["remaining"]["wall-time-limit-millis"]["some"]);
    assert!(effective > before && remaining > 0);
    assert_eq!(
        response["data"]["resolvedRevision"]["releaseDigest"],
        package.digest
    );
    let status = harness
        .call("tests", &["activation", "get", id], 0, "success")
        .await;
    assert_eq!(status["data"]["terminalState"], "completed");
    assert_eq!(
        status["data"]["finalConsumption"],
        response["data"]["consumption"]
    );
    json!({"response":response,"status":status,"decoded":decoded,
        "beforeUnixMillis":before.to_string(),"afterUnixMillis":after.to_string(),
        "effectiveDeadlineUnixMillis":effective.to_string(),"remainingMillis":remaining.to_string(),
        "requestedWallMillis":"5000","clockResolutionMillis":"1"})
}

pub(super) fn assert_relative(observation: &Value, ceiling: u64) {
    let before = unsigned(&observation["beforeUnixMillis"]);
    let after = unsigned(&observation["afterUnixMillis"]);
    let deadline = unsigned(&observation["effectiveDeadlineUnixMillis"]);
    // Millisecond wire clocks can differ by one rounding unit from the CLI's
    // monotonic allowance. The full before/after interval includes dispatch.
    assert!(deadline >= before + ceiling - 1);
    assert!(deadline <= after + ceiling + 1);
    assert!(unsigned(&observation["remainingMillis"]) <= ceiling);
}

pub(super) fn unix_millis() -> u64 {
    millis(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("current Unix time"),
    )
}

pub(super) fn millis(duration: Duration) -> u64 {
    u64::try_from(duration.as_millis()).expect("bounded observation interval")
}

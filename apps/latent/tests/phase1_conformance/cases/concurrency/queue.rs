use super::{cancel, phase, spin};
use crate::{
    cases::{idle, payload},
    evidence::Evidence,
    fixtures::Fixtures,
    harness::{invoke_args, Harness, PendingCli},
};
use serde_json::{json, Value};

pub async fn queue_admission(harness: &mut Harness, evidence: &mut Evidence, fixtures: &Fixtures) {
    evidence.begin("queue-admission");
    let generic = &fixtures.generic;
    let empty = generic.input("queue-empty.json", &json!([]));
    let first = spin(harness, generic, "queue-holder-first", &empty);
    let first_running = phase(harness, "tests", "queue-holder-first", "running").await;
    let second = spin(harness, generic, "queue-holder-second", &empty);
    let second_running = phase(harness, "tests", "queue-holder-second", "running").await;
    let tests = harness.spawn_cli(
        "tests",
        &invoke_args(generic, "identify", "queued-tests", &empty),
    );
    let echo_input = fixtures
        .echo
        .input("queue-echo.json", &json!(["queued other tenant"]));
    let examples = harness.spawn_cli(
        "examples",
        &invoke_args(&fixtures.echo, "echo", "queued-examples", &echo_input),
    );
    let tests_queued = phase(harness, "tests", "queued-tests", "queued").await;
    let examples_queued = phase(harness, "examples", "queued-examples", "queued").await;
    let full = harness.inventory().await;
    assert_full(&full);
    let overflow = harness
        .invoke(
            generic,
            "identify",
            "queue-overflow",
            &empty,
            &[],
            (5, "transport-failure"),
        )
        .await;
    assert_eq!(overflow["error"]["grpcCode"], "resource-exhausted");
    assert_eq!(overflow["requestDispatched"], true);
    assert_eq!(overflow["outcomeKnown"], false);
    // A bare gRPC ResourceExhausted cannot prove outcome to the CLI. The
    // explicit status lookup and unchanged inventory establish non-registration.
    let overflow_status = harness
        .call(
            "tests",
            &["activation", "get", "queue-overflow"],
            6,
            "not-found",
        )
        .await;
    let still_full = harness.inventory().await;
    assert_full(&still_full);
    let first_cancel = cancel(harness, "queue-holder-first").await;
    let second_cancel = cancel(harness, "queue-holder-second").await;
    let first_result = cancelled(harness, first).await;
    let second_result = cancelled(harness, second).await;
    let tests_result = harness.finish_cli(tests, 0, "success").await;
    let examples_result = harness.finish_cli(examples, 0, "success").await;
    assert_eq!(payload(&tests_result), json!([11]));
    assert_eq!(
        payload(&examples_result),
        json!([{"ok":"queued other tenant"}])
    );
    assert_eq!(
        tests_result["data"]["resolvedRevision"]["releaseDigest"],
        generic.digest
    );
    assert_eq!(
        examples_result["data"]["resolvedRevision"]["releaseDigest"],
        fixtures.echo.digest
    );
    let completed = completed_statuses(harness, [&tests_result, &examples_result]).await;
    let idle_sample = harness.sample("queue-settled").await;
    idle(&idle_sample);
    evidence.passed(harness,json!({"holdersRunning":[first_running,second_running],
        "queued":[tests_queued,examples_queued],"full":full,"overflow":overflow,
        "overflowStatus":overflow_status,"unchangedFull":still_full,
        "cancelled":[first_cancel,second_cancel],"holderResults":[first_result,second_result],
        "queuedResults":[tests_result,examples_result],"completedStatuses":completed,"idleSample":idle_sample,
        "overflowBoundary":"standalone-active-owner-ceiling-before-extra-journal-registration"}));
}

fn assert_full(inventory: &Value) {
    assert_eq!(inventory["cellCapacity"][0]["total"], 2);
    assert_eq!(inventory["cellCapacity"][0]["active"], 2);
    assert_eq!(inventory["cellCapacity"][0]["available"], 0);
    assert_eq!(inventory["cellCapacity"][0]["queueDepth"], 2);
    assert_eq!(inventory["cellCapacity"][0]["queuedTenants"], 2);
    assert_eq!(inventory["queueDepth"], "2");
    assert_eq!(inventory["quotas"]["usage"]["activeActivations"], 4);
    assert_eq!(inventory["quotas"]["usage"]["queuedActivations"], 2);
}

async fn cancelled(harness: &mut Harness, pending: PendingCli) -> Value {
    let response = harness.finish_cli(pending, 4, "platform-failure").await;
    assert_eq!(response["error"]["code"], "cancelled");
    response
}

async fn completed_statuses(harness: &mut Harness, responses: [&Value; 2]) -> Vec<Value> {
    let mut statuses = Vec::new();
    for ((profile, id), response) in [("tests", "queued-tests"), ("examples", "queued-examples")]
        .into_iter()
        .zip(responses)
    {
        let status = harness
            .call(profile, &["activation", "get", id], 0, "success")
            .await;
        assert_eq!(status["data"]["terminalState"], "completed");
        assert_eq!(
            status["data"]["finalConsumption"],
            response["data"]["consumption"]
        );
        statuses.push(status);
    }
    statuses
}

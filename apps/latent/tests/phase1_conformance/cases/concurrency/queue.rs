#[path = "queue/observations.rs"]
mod observations;

use super::{cancel, phase, spin};
use crate::{
    cases::{idle, payload},
    evidence::Evidence,
    fixtures::Fixtures,
    harness::{invoke_args, Harness},
};
use observations::{assert_full, cancelled, overflow, statuses};
use serde_json::json;

pub async fn queue_admission(harness: &mut Harness, evidence: &mut Evidence, fixtures: &Fixtures) {
    evidence.begin("queue-admission");
    let generic = &fixtures.generic;
    let empty = generic.input("queue-empty.json", &json!([]));
    let first = spin(harness, generic, "queue-holder-first", &empty);
    let first_running = phase(harness, "tests", "queue-holder-first", "running").await;
    let second = spin(harness, generic, "queue-holder-second", &empty);
    let second_running = phase(harness, "tests", "queue-holder-second", "running").await;
    // Observe each registration before submitting the next: A1, A2, then B.
    let first_queued = spin(harness, generic, "queued-tests-first", &empty);
    let first_waiting = phase(harness, "tests", "queued-tests-first", "queued").await;
    let second_queued = spin(harness, generic, "queued-tests-second", &empty);
    let second_waiting = phase(harness, "tests", "queued-tests-second", "queued").await;
    let echo_input = fixtures
        .echo
        .input("queue-echo.json", &json!(["queued other tenant"]));
    let examples = harness.spawn_cli(
        "examples",
        &invoke_args(&fixtures.echo, "echo", "queued-examples", &echo_input),
    );
    let examples_waiting = phase(harness, "examples", "queued-examples", "queued").await;
    let full = harness.inventory().await;
    assert_full(&full);
    let (overflow_result, overflow_status) = overflow(harness, generic, &empty).await;
    let still_full = harness.inventory().await;
    assert_full(&still_full);

    let first_cancel = cancel(harness, "queue-holder-first").await;
    let first_handoff = phase(harness, "tests", "queued-tests-first", "running").await;
    let first_queued_cancel = cancel(harness, "queued-tests-first").await;
    let examples_result = harness.finish_cli(examples, 0, "success").await;
    assert_eq!(
        payload(&examples_result),
        json!([{"ok":"queued other tenant"}])
    );
    assert_eq!(
        examples_result["data"]["resolvedRevision"]["releaseDigest"],
        fixtures.echo.digest
    );
    // B must finish while H2 and A2 still own their running stores. FIFO would
    // run A2 before B, which cannot succeed without A2 finishing or timing out.
    let held_running = phase(harness, "tests", "queue-holder-second", "running").await;
    let remaining_running = phase(harness, "tests", "queued-tests-second", "running").await;
    let second_queued_cancel = cancel(harness, "queued-tests-second").await;
    let second_cancel = cancel(harness, "queue-holder-second").await;
    let first_result = cancelled(harness, first).await;
    let second_result = cancelled(harness, second).await;
    let first_queued_result = cancelled(harness, first_queued).await;
    let second_queued_result = cancelled(harness, second_queued).await;
    for response in [&first_queued_result, &second_queued_result] {
        assert_eq!(
            response["data"]["resolvedRevision"]["releaseDigest"],
            generic.digest
        );
    }
    let queued_statuses = statuses(
        harness,
        [
            &first_queued_result,
            &second_queued_result,
            &examples_result,
        ],
    )
    .await;
    let idle_sample = harness.sample("queue-settled").await;
    idle(&idle_sample);
    evidence.passed(harness,json!({"holdersRunning":[first_running,second_running],
        "queued":[first_waiting,second_waiting,examples_waiting],"full":full,"overflow":overflow_result,
        "overflowStatus":overflow_status,"unchangedFull":still_full,"firstHandoff":first_handoff,
        "secondHandoff":{"examplesResult":examples_result,"secondHolderRunning":held_running,"secondQueuedRunning":remaining_running},
        "cancelled":[first_cancel,first_queued_cancel,second_queued_cancel,second_cancel],
        "holderResults":[first_result,second_result],
        "queuedResults":[first_queued_result,second_queued_result,examples_result],"queuedStatuses":queued_statuses,"idleSample":idle_sample,
        "fairnessOracle":"other-tenant-completes-before-uncancelled-same-tenant-spin",
        "overflowBoundary":"standalone-active-owner-ceiling-before-extra-journal-registration"}));
}

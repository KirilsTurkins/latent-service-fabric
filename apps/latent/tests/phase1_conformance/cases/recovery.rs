use super::{idle, payload};
use crate::{evidence::Evidence, fixtures::Package, harness::Harness};
use serde_json::json;

pub async fn healthy(harness: &mut Harness, evidence: &mut Evidence, package: &Package) {
    evidence.begin("healthy-recovery");
    let empty = package.input("recovery.json", &json!([]));
    let response = harness
        .invoke(
            package,
            "identify",
            "healthy-recovery",
            &empty,
            &[],
            (0, "success"),
        )
        .await;
    assert_eq!(payload(&response), json!([11]));
    let status = harness
        .call(
            "tests",
            &["activation", "get", "healthy-recovery"],
            0,
            "success",
        )
        .await;
    assert_eq!(status["data"]["terminalState"], "completed");
    let ready = harness.ready().await;
    evidence.passed(
        harness,
        json!({"response":response,"status":status,"ready":ready}),
    );
}

pub async fn resources(harness: &mut Harness, evidence: &mut Evidence) {
    evidence.begin("child-resources");
    let sample = harness.sample("post-mixed").await;
    idle(&sample);
    assert_eq!(sample.inventory["cacheSummary"]["entries"], "3");
    let empty = evidence
        .report
        .samples
        .iter()
        .find(|sample| sample.phase == "empty")
        .expect("empty sample");
    let warm = evidence
        .report
        .samples
        .iter()
        .find(|sample| sample.phase == "warm")
        .expect("warm sample");
    assert_eq!(sample.process.identity, empty.process.identity);
    assert_eq!(
        sample.process.task_count, warm.process.task_count,
        "bounded workload leaves the warmed fixed helper topology"
    );
    assert_eq!(
        sample.process.listening_tcp_socket_count,
        empty.process.listening_tcp_socket_count
    );
    let observed = json!({"sample":sample,"rssInterpretation":"point-observation-only",
        "scaleInterpretation":"four-dormant-entries-only","activationOwnersObservedZero":true});
    evidence.report.samples.push(sample);
    evidence.passed(harness, observed);
}

pub async fn shutdown(harness: &mut Harness, evidence: &mut Evidence) {
    evidence.begin("clean-shutdown");
    let sample = harness.sample("pre-shutdown").await;
    idle(&sample);
    evidence.report.samples.push(sample);
    let shutdown = harness.stop().await;
    let observed = json!({"shutdown":shutdown});
    evidence.report.shutdowns.push(shutdown);
    evidence.passed(harness, observed);
}

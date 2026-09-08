#[path = "wall/observe.rs"]
mod observe;

use crate::{
    cases::{idle, unsigned},
    evidence::Evidence,
    fixtures::{path, Package},
    harness::Harness,
};
use observe::{assert_relative, millis, snapshot, unix_millis};
use serde_json::{json, Value};
use std::time::{Duration, Instant};

const DEPLOYMENT_MILLIS: u64 = 1000;

pub async fn persistent_wall(harness: &mut Harness, evidence: &mut Evidence, package: &Package) {
    evidence.begin("persistent-wall-ceiling");
    let original = get(harness).await;
    let manifest = &original["data"]["deployment"]["manifest"];
    assert!(manifest["spec"]["resources"]["wallTimeLimitMillis"].is_null());
    let input = package.input("wall-empty.json", &json!([]));
    let node_millis = harness.public_config["execution"]["maximumWallTimeMillis"]
        .as_u64()
        .expect("configured relative node ceiling");
    assert_eq!(node_millis, 5000);
    let node_age_target = Duration::from_millis(node_millis + 1);
    if let Some(wait) = node_age_target.checked_sub(harness.node_age()) {
        tokio::time::sleep(wait).await;
    }
    let node_age = millis(harness.node_age());
    assert!(node_age > node_millis);
    // The standalone transport and admission share the node's configured cap.
    // This witnesses their aged composition; pure intersection has owning tests.
    let node_response = snapshot(harness, package, &input, "wall-node-aged", None).await;
    assert_relative(&node_response, node_millis);

    let mut changed = manifest.clone();
    changed["spec"]["resources"]["wallTimeLimitMillis"] = json!(DEPLOYMENT_MILLIS);
    let update = package.input("wall-relative-deployment.json", &changed);
    let applied = apply(harness, &update, &original).await;
    let committed_at = Instant::now();
    let committed_unix = unix_millis();
    let persisted_before = get(harness).await;
    assert_eq!(
        persisted_before["data"]["deployment"],
        applied["data"]["deployment"]
    );
    assert_eq!(persisted_before["data"]["deployment"]["manifest"], changed);
    let target = Duration::from_millis(DEPLOYMENT_MILLIS + 1);
    if let Some(wait) = target.checked_sub(committed_at.elapsed()) {
        tokio::time::sleep(wait).await;
    }
    let deployment_age = millis(committed_at.elapsed());
    assert!(deployment_age > DEPLOYMENT_MILLIS);
    let deployment_response =
        snapshot(harness, package, &input, "wall-deployment-aged", None).await;
    assert!(
        unsigned(&deployment_response["beforeUnixMillis"]) > committed_unix + DEPLOYMENT_MILLIS
    );
    assert_relative(&deployment_response, DEPLOYMENT_MILLIS);
    let absolute = unix_millis()
        .checked_add(500)
        .expect("bounded caller deadline");
    let caller_response = snapshot(
        harness,
        package,
        &input,
        "wall-caller-earlier",
        Some(absolute),
    )
    .await;
    assert_eq!(
        caller_response["effectiveDeadlineUnixMillis"],
        absolute.to_string()
    );
    let persisted_after = get(harness).await;
    assert_eq!(
        persisted_after["data"]["deployment"],
        persisted_before["data"]["deployment"]
    );
    let restore = package.input("wall-original-deployment.json", manifest);
    let restored = apply(harness, &restore, &persisted_after).await;
    assert_eq!(restored["data"]["deployment"]["manifest"], *manifest);
    let idle_sample = harness.sample("wall-ceilings-settled").await;
    idle(&idle_sample);
    evidence.passed(harness, json!({
        "nodeCeiling":{"ceilingMillis":node_millis.to_string(),"nodeAgeMillis":node_age.to_string(),
            "observation":node_response,"scope":"configured-standalone-transport-and-admission"},
        "deploymentCeiling":{"ceilingMillis":DEPLOYMENT_MILLIS.to_string(),"agedMillis":deployment_age.to_string(),
            "committedUnixMillis":committed_unix.to_string(),
            "original":original,"applied":applied,"persistedBefore":persisted_before,
            "observation":deployment_response,"persistedAfter":persisted_after},
        "callerDeadline":{"absoluteUnixMillis":absolute.to_string(),"observation":caller_response},
        "restored":restored,"idleSample":idle_sample
    }));
}

async fn get(harness: &mut Harness) -> Value {
    harness
        .call(
            "tests",
            &["deployment", "get", "capabilities"],
            0,
            "success",
        )
        .await
}

async fn apply(harness: &mut Harness, input: &std::path::Path, previous: &Value) -> Value {
    let generation = previous["data"]["deployment"]["generation"]
        .as_str()
        .expect("exact object generation");
    harness
        .call(
            "tests",
            &[
                "deployment",
                "apply",
                path(input),
                "--expected-generation",
                generation,
            ],
            0,
            "success",
        )
        .await
}

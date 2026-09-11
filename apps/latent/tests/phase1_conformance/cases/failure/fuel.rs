use crate::{
    cases::{idle, unsigned},
    evidence::Evidence,
    fixtures::Package,
    harness::Harness,
};
use serde_json::json;

pub async fn fuel(harness: &mut Harness, evidence: &mut Evidence, package: &Package) {
    evidence.begin("fuel-budget");
    let input = package.input("fuel.json", &json!([]));
    let response = harness
        .invoke(
            package,
            "spin",
            "fuel-exhausted",
            &input,
            &["--cpu-fuel", "50000", "--wall-time-ms", "1000"],
            (4, "platform-failure"),
        )
        .await;
    assert_eq!(response["error"]["code"], "resource-exhausted");
    assert_eq!(response["data"]["terminalState"], "resource_exhausted");
    let consumption = &response["data"]["consumption"];
    let fuel = unsigned(&consumption["cpuFuel"]);
    assert!(
        fuel > 0 && fuel <= 50_000,
        "positive finite guest fuel usage"
    );
    assert!(unsigned(&consumption["peakMemoryBytes"]) > 0);
    assert_eq!(
        response["data"]["resolvedRevision"]["releaseDigest"],
        package.digest
    );
    let status = harness
        .call(
            "tests",
            &["activation", "get", "fuel-exhausted"],
            0,
            "success",
        )
        .await;
    assert_eq!(status["data"]["terminalState"], "resource_exhausted");
    assert_eq!(status["data"]["finalConsumption"], *consumption);
    let idle_sample = harness.sample("fuel-settled").await;
    idle(&idle_sample);
    evidence.passed(
        harness,
        json!({"response":response,"status":status,"fuelGrant":"50000","idleSample":idle_sample}),
    );
}

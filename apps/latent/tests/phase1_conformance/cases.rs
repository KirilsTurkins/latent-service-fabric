#[path = "cases/capabilities.rs"]
mod capabilities;
#[path = "cases/catalog.rs"]
mod catalog;
#[path = "cases/concurrency.rs"]
mod concurrency;
#[path = "cases/failure.rs"]
mod failure;
#[path = "cases/recovery.rs"]
mod recovery;

use base64::{engine::general_purpose::STANDARD, Engine};
use latent_testkit::conformance::ProcessSample;
use serde_json::{json, Value};

use super::{
    evidence::Evidence,
    fixtures::{Fixtures, MEDIA},
    harness::Harness,
};

pub async fn run(harness: &mut Harness, evidence: &mut Evidence, fixtures: &Fixtures) {
    let empty = catalog::empty(harness, evidence).await;
    catalog::dormant(harness, evidence, fixtures, &empty).await;
    fresh(harness, evidence, fixtures).await;
    failure::mixed(harness, evidence, &fixtures.generic).await;
    failure::deadline(harness, evidence, &fixtures.generic).await;
    failure::cancel(harness, evidence, &fixtures.generic).await;
    failure::malformed(harness, evidence, &fixtures.generic).await;
    failure::memory(harness, evidence, &fixtures.generic).await;
    capabilities::context(harness, evidence, &fixtures.capabilities).await;
    capabilities::logs(harness, evidence, &fixtures.capabilities).await;
    catalog::tenants(harness, evidence, fixtures).await;
    concurrency::route_update(harness, evidence, &fixtures.generic).await;
    concurrency::queue_admission(harness, evidence, fixtures).await;
    recovery::healthy(harness, evidence, &fixtures.generic).await;
    recovery::resources(harness, evidence).await;
    recovery::shutdown(harness, evidence).await;
}

async fn fresh(harness: &mut Harness, evidence: &mut Evidence, fixtures: &Fixtures) {
    evidence.begin("fresh-store");
    let package = &fixtures.generic;
    let input = package.input("empty.json", &json!([]));
    let warm = harness
        .invoke(package, "identify", "warmup", &input, &[], (0, "success"))
        .await;
    assert_eq!(payload(&warm), json!([11]));
    let mut responses = vec![warm];
    for id in ["fresh-first", "fresh-second"] {
        let response = harness
            .invoke(package, "bump", id, &input, &[], (0, "success"))
            .await;
        assert_eq!(
            payload(&response),
            json!([1]),
            "fresh guest static memory on each invocation"
        );
        responses.push(response);
    }
    let sample = harness.sample("warm").await;
    idle(&sample);
    assert_eq!(sample.inventory["cacheSummary"]["entries"], "1");
    let observed = json!({"responses":responses,"sample":sample});
    evidence.report.samples.push(sample);
    evidence.passed(harness, observed);
}

pub fn payload(response: &Value) -> Value {
    decode_payload(&response["data"]["payload"])
}

pub fn decode_payload(payload: &Value) -> Value {
    assert_eq!(payload["encoding"], "base64");
    assert_eq!(payload["mediaType"], MEDIA);
    let bytes = STANDARD
        .decode(payload["data"].as_str().expect("bounded base64 response"))
        .expect("canonical payload bytes");
    assert_eq!(
        unsigned(&payload["byteLength"]),
        u64::try_from(bytes.len()).expect("response length")
    );
    serde_json::from_slice(&bytes).expect("canonical typed result array")
}

pub fn unsigned(value: &Value) -> u64 {
    value
        .as_str()
        .expect("canonical decimal string")
        .parse()
        .expect("u64")
}

pub fn idle(sample: &ProcessSample) {
    let inventory = &sample.inventory;
    assert_eq!(inventory["queueDepth"], "0");
    assert_eq!(inventory["cacheSummary"]["preparing"], "0");
    assert_eq!(inventory["cacheSummary"]["preparingSourceBytes"], "0");
    assert_eq!(inventory["cacheSummary"]["preparingMetadataBytes"], "0");
    assert_eq!(inventory["quotas"]["usage"]["activeActivations"], 0);
    assert_eq!(inventory["quotas"]["usage"]["queuedActivations"], 0);
    assert_eq!(inventory["quotas"]["usage"]["reservedCpuFuel"], "0");
    assert_eq!(inventory["quotas"]["usage"]["reservedMemoryBytes"], "0");
    let cells = inventory["cellCapacity"].as_array().expect("fixed cells");
    assert_eq!(cells.len(), 1);
    assert_eq!(cells[0]["total"], 2);
    assert_eq!(cells[0]["active"], 0);
    assert_eq!(cells[0]["available"], 2);
    assert_eq!(cells[0]["quarantined"], 0);
    assert_eq!(cells[0]["queueDepth"], 0);
    assert_eq!(inventory["topology"]["available"], true);
    for entry in inventory["topology"]["entries"]
        .as_array()
        .expect("ownership rows")
    {
        if entry["ownership"] == "service-resident" {
            assert_eq!(entry["configuredCount"], "0");
            assert_eq!(entry["activeCount"], "0");
        }
        if entry["ownership"] == "activation-scoped" {
            assert_eq!(entry["activeCount"], "0", "{}", entry["name"]);
        }
    }
}

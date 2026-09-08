use super::{payload, unsigned};
use crate::{evidence::Evidence, fixtures::Package, harness::Harness};
use serde_json::{json, Value};

pub async fn context(harness: &mut Harness, evidence: &mut Evidence, package: &Package) {
    evidence.begin("capability-context");
    let empty = package.input("context.json", &json!([]));
    let mut snapshots = Vec::new();
    for (id, marker) in [
        ("context-first", "first"),
        ("context-second", "second"),
        ("context-third", "third"),
    ] {
        let visible = format!("guest.visible={marker}");
        let root = format!("root-{marker}");
        let parent = format!("parent-{marker}");
        let response = harness
            .invoke(
                package,
                "snapshot",
                id,
                &empty,
                &[
                    "--root-activation-id",
                    &root,
                    "--parent-activation-id",
                    &parent,
                    "--metadata",
                    &visible,
                    "--metadata",
                    "internal.credential=private-context-marker",
                    "--wall-time-ms",
                    "1000",
                ],
                (0, "success"),
            )
            .await;
        let output = payload(&response);
        let value = &output[0];
        assert_eq!(value["activation"], id);
        assert_eq!(value["root"], root);
        assert_eq!(value["parent"], json!({"some":parent}));
        assert_eq!(value["principal"]["subject"], "tests-operator");
        assert_eq!(value["principal"]["tenant"], json!({"some":"tests"}));
        assert_eq!(value["principal"]["claims"], json!([]));
        assert_eq!(value["trace"]["baggage"], json!([]));
        assert_eq!(value["metadata"], json!([["guest.visible", marker]]));
        assert!(!output.to_string().contains("private-context-marker"));
        assert!(unsigned(&value["deadline"]["some"]) > 0);
        assert!(unsigned(&value["remaining"]["cpu-fuel"]) < 100_000_000);
        assert!(unsigned(&value["remaining"]["memory-bytes"]) < 67_108_864);
        assert_eq!(value["remaining"]["log-bytes"], "16384");
        snapshots.push(json!({"response":response,"decoded":output}));
    }
    assert_ne!(
        snapshots[0]["decoded"][0]["trace"]["trace-id"],
        snapshots[1]["decoded"][0]["trace"]["trace-id"]
    );
    assert_ne!(
        snapshots[0]["decoded"][0]["trace"]["trace-id"],
        snapshots[2]["decoded"][0]["trace"]["trace-id"]
    );
    let first_cell = snapshots[0]["response"]["data"]["metadata"]["cell-id"]
        .as_str()
        .expect("actual context cell");
    assert_eq!(
        snapshots[2]["response"]["data"]["metadata"]["cell-id"],
        first_cell
    );
    assert_ne!(
        snapshots[1]["response"]["data"]["metadata"]["cell-id"],
        first_cell
    );
    let live = live_budget(harness, package, &empty).await;
    let clocks = clocks(harness, package, &empty).await;
    evidence.passed(
        harness,
        json!({"snapshots":snapshots,"liveBudget":live,"clocks":clocks}),
    );
}

async fn live_budget(harness: &mut Harness, package: &Package, empty: &std::path::Path) -> Value {
    let response = harness
        .invoke(
            package,
            "work-observe",
            "live-budget",
            empty,
            &[],
            (0, "success"),
        )
        .await;
    let output = payload(&response);
    let before = &output[0]["before"];
    let after = &output[0]["after"];
    assert_eq!(output[0]["checksum"], 1024);
    assert_eq!(output[0]["logged"], json!({"ok":true}));
    for field in ["cpu-fuel", "memory-bytes", "log-bytes"] {
        assert!(
            unsigned(&after[field]) < unsigned(&before[field]),
            "live {field} budget"
        );
    }
    let consumption = &response["data"]["consumption"];
    assert_eq!(
        unsigned(&consumption["logBytes"]),
        16_384 - unsigned(&after["log-bytes"])
    );
    assert!(unsigned(&consumption["cpuFuel"]) >= 100_000_000 - unsigned(&after["cpu-fuel"]));
    assert!(
        unsigned(&consumption["peakMemoryBytes"]) >= 67_108_864 - unsigned(&after["memory-bytes"])
    );
    json!({"response":response,"decoded":output})
}

async fn clocks(harness: &mut Harness, package: &Package, empty: &std::path::Path) -> Value {
    let response = harness
        .invoke(package, "clocks", "clock-log", empty, &[], (0, "success"))
        .await;
    let output = payload(&response);
    let readings = output[0].as_array().expect("clock readings");
    assert_eq!(readings.len(), 3);
    assert!(readings
        .iter()
        .all(|reading| unsigned(&reading["wall"]) > 0));
    assert!(readings
        .windows(2)
        .all(|pair| unsigned(&pair[0]["monotonic"]) <= unsigned(&pair[1]["monotonic"])));
    assert!(unsigned(&response["data"]["consumption"]["logBytes"]) > 0);
    json!({"response":response,"decoded":output})
}

pub async fn logs(harness: &mut Harness, evidence: &mut Evidence, package: &Package) {
    evidence.begin("log-budget");
    let input = package.input("log.json", &json!(["quoted \"line\"\nslash\\", []]));
    let denied = harness
        .invoke(
            package,
            "log-probe",
            "log-denied",
            &input,
            &["--log-bytes", "0"],
            (0, "success"),
        )
        .await;
    let denied_payload = payload(&denied);
    assert_eq!(
        denied_payload[0]["outcome"],
        json!({"err":{"case":"budget-exhausted"}})
    );
    assert_eq!(denied_payload[0]["before"], "0");
    assert_eq!(denied_payload[0]["after"], "0");
    assert_eq!(denied["data"]["consumption"]["logBytes"], "0");
    let accepted = harness
        .invoke(
            package,
            "log-probe",
            "log-accepted",
            &input,
            &["--log-bytes", "4096"],
            (0, "success"),
        )
        .await;
    let accepted_payload = payload(&accepted);
    assert_eq!(accepted_payload[0]["outcome"], json!({"ok":true}));
    assert_eq!(accepted_payload[0]["before"], "4096");
    let used = 4096 - unsigned(&accepted_payload[0]["after"]);
    assert!(used > 0);
    assert_eq!(unsigned(&accepted["data"]["consumption"]["logBytes"]), used);
    evidence.passed(
        harness,
        json!({"denied":denied,"deniedDecoded":denied_payload,
        "accepted":accepted,"acceptedDecoded":accepted_payload}),
    );
}

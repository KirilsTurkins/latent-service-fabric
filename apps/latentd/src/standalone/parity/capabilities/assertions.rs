use serde_json::{json, Value};

use super::{FUEL, LOG, MEMORY, PARENT, ROOT, WALL};

pub fn check(function: &str, call: &Value, before: u64, after: u64) {
    let output = &call["decoded"][0];
    match function {
        "snapshot" => snapshot(call, before, after),
        "work-observe" => work(call),
        "clocks" => {
            let readings = output.as_array().unwrap();
            assert_eq!(readings.len(), 3);
            assert!(readings.iter().all(|value| unsigned(&value["wall"]) > 0));
            assert!(readings
                .windows(2)
                .all(|pair| unsigned(&pair[0]["monotonic"]) <= unsigned(&pair[1]["monotonic"])));
            assert!(unsigned(&call["consumption"]["log_bytes"]) > 0);
        }
        _ => unreachable!("three fixed capability cases"),
    }
}

fn snapshot(call: &Value, before: u64, after: u64) {
    let value = &call["decoded"][0];
    assert_eq!(value["activation"], call["activation_id"]);
    assert_eq!(value["root"], ROOT);
    assert_eq!(value["parent"], json!({"some":PARENT}));
    assert_eq!(value["principal"]["subject"], "parity-tests");
    assert_eq!(value["principal"]["tenant"], json!({"some":"tests"}));
    assert_eq!(value["principal"]["claims"], json!([]));
    assert_eq!(value["trace"]["baggage"], json!([]));
    assert_eq!(value["metadata"], json!([["guest.visible", "paired"]]));
    let observed_trace = &call["completion_span"]["trace"];
    assert_eq!(value["trace"]["trace-id"], observed_trace["trace_id"]);
    assert_eq!(value["trace"]["span-id"], observed_trace["span_id"]);
    assert_eq!(value["trace"]["trace-flags"], observed_trace["trace_flags"]);
    let deadline = unsigned(&value["deadline"]["some"]);
    assert!(deadline >= before + WALL && deadline <= after + WALL);
    let remaining = &value["remaining"];
    assert!(unsigned(&remaining["cpu-fuel"]) < FUEL);
    assert!(unsigned(&remaining["memory-bytes"]) < MEMORY);
    assert_eq!(unsigned(&remaining["log-bytes"]), LOG);
    assert_eq!(unsigned(&call["consumption"]["log_bytes"]), 0);
}

fn work(call: &Value) {
    let value = &call["decoded"][0];
    assert_eq!(value["checksum"], 1024);
    assert_eq!(value["logged"], json!({"ok":true}));
    let before = &value["before"];
    let after = &value["after"];
    for field in ["cpu-fuel", "memory-bytes", "log-bytes"] {
        assert!(unsigned(&after[field]) < unsigned(&before[field]));
    }
    assert_eq!(unsigned(&before["log-bytes"]), LOG);
    assert_eq!(
        unsigned(&call["consumption"]["log_bytes"]),
        LOG - unsigned(&after["log-bytes"])
    );
    assert!(unsigned(&call["consumption"]["cpu_fuel"]) >= FUEL - unsigned(&after["cpu-fuel"]));
    assert!(
        unsigned(&call["consumption"]["peak_memory_bytes"])
            >= MEMORY - unsigned(&after["memory-bytes"])
    );
}

fn unsigned(value: &Value) -> u64 {
    value.as_str().expect("decimal u64").parse().unwrap()
}

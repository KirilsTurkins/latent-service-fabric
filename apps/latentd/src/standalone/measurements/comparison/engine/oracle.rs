use super::{call::Offer, fixture::DIRTY, Node, Result};
use latent_core::{DeadlineDiagnosticObservation, DeadlineDiagnosticObserver};
use serde_json::{json, Value};

pub(super) fn logs(node: &Node, id: &str) -> Result<Vec<Value>> {
    node.owner.backend.log_sink().snapshot().into_iter().filter(|entry|entry.activation_id.0==id).map(|entry| {
        let encoded=serde_json::to_vec(&entry)?;
        Ok(json!({"record":entry,"encoded_bytes":encoded.len().to_string(),"sha256":latent_artifacts::content_digest(&encoded).0}))
    }).collect()
}
pub(super) fn check(offer: &Offer, row: &Value, observer: &DeadlineDiagnosticObserver) -> bool {
    if row["valid_response"] != true {
        return false;
    }
    let Some(logs) = row["guest_logs"].as_array() else {
        return false;
    };
    let logged = logs.iter().try_fold(0_u64, |n, v| {
        n.checked_add(v["encoded_bytes"].as_str()?.parse::<u64>().ok()?)
    });
    if logged.map(|n| n.to_string()).as_deref()
        != row["response"]["consumption"]["log_bytes"].as_str()
    {
        return false;
    }
    for value in logs {
        let record = &value["record"];
        if record["activation_id"] != offer.id
            || record["fields"]["latent.activation_id"] != offer.id
            || record["fields"]["latent.trace_id"]
                .as_str()
                .is_none_or(|v| v.len() != 32)
            || record["fields"]["latent.span_id"]
                .as_str()
                .is_none_or(|v| v.len() != 16)
        {
            return false;
        }
    }
    if offer.target.service == "engine-memory" {
        return logs.len() == 1
            && logs[0]["record"]["message"] == DIRTY
            && logs[0]["record"]["level"] == "info"
            && logs[0]["record"]["fields"]
                .as_object()
                .is_some_and(|v| v.len() == 3);
    }
    if offer.phase != "functional" {
        return true;
    }
    let output = &row["response"]["payload"]["value"];
    match offer.function.as_str() {
        "snapshot" => snapshot(offer, &output[0], observer) && logs.is_empty(),
        "clocks" => {
            let Some(readings) = output[0].as_array().filter(|v| v.len() == 3) else {
                return false;
            };
            let times = readings
                .iter()
                .map(|v| v["monotonic"].as_str().and_then(|v| v.parse::<u64>().ok()))
                .collect::<Option<Vec<_>>>();
            times.is_some_and(|v| v.windows(2).all(|pair| pair[0] <= pair[1]))
                && readings.iter().all(|v| {
                    v["wall"]
                        .as_str()
                        .and_then(|v| v.parse::<u64>().ok())
                        .is_some()
                })
                && logs.len() == 2
                && logs.iter().all(|v| v["record"]["message"] == "clock-step")
        }
        "log-probe" => {
            let value = &output[0];
            let before = value["before"].as_str().and_then(|v| v.parse::<u64>().ok());
            let after = value["after"].as_str().and_then(|v| v.parse::<u64>().ok());
            logs.len() == 1
                && value["outcome"] == json!({"ok":true})
                && before.zip(after).and_then(|(a, b)| a.checked_sub(b)) == logged
                && logs[0]["record"]["message"] == offer.payload[0]
                && logs[0]["record"]["fields"]["probe"] == offer.payload[1][0]["value"]
        }
        "spin" if offer.expected_code == Some("resource-exhausted") => {
            detail(row, "activation.fuel-exhausted") && logs.is_empty()
        }
        "grow" => detail(row, "activation.memory-exhausted") && logs.is_empty(),
        _ => logs.is_empty(),
    }
}
fn detail(row: &Value, kind: &str) -> bool {
    row["response"]["details"]
        .as_array()
        .is_some_and(|v| v.iter().any(|d| d["kind"] == kind))
}
fn snapshot(offer: &Offer, value: &Value, observer: &DeadlineDiagnosticObserver) -> bool {
    let marker = if offer.target.tenant == "engine-a" {
        "a"
    } else {
        "b"
    };
    let current = observer.snapshot();
    let token = current
        .identities
        .iter()
        .find(|v| v.activation_id.as_deref() == Some(&offer.id))
        .map(|v| v.token);
    let ledger = current.records.iter().find_map(|record| {
        if Some(record.token) == token {
            if let DeadlineDiagnosticObservation::AdmittedLedger {
                deadline, budget, ..
            } = &record.observation
            {
                return Some((deadline, budget));
            }
        }
        None
    });
    let Some((deadline, budget)) = ledger else {
        return false;
    };
    let remaining = &value["remaining"];
    let within = |key: &str, maximum: u64| {
        remaining[key]
            .as_str()
            .and_then(|v| v.parse::<u64>().ok())
            .is_some_and(|v| v <= maximum)
    };
    value["activation"] == offer.id
        && value["root"] == format!("engine-root-{marker}")
        && value["parent"] == json!({"some":format!("engine-parent-{marker}")})
        && value["principal"]["kind"] == "administrator"
        && value["principal"]["subject"] == format!("engine-subject-{marker}")
        && value["principal"]["tenant"] == json!({"some":offer.target.tenant})
        && value["principal"]["service"].is_null()
        && value["principal"]["claims"] == json!([])
        && value["metadata"] == json!([["guest.marker", marker]])
        && value["trace"]["trace-flags"] == 0
        && value["trace"]["baggage"] == json!([])
        && hex(&value["trace"]["trace-id"], 32)
        && hex(&value["trace"]["span-id"], 16)
        && value["deadline"]
            == deadline
                .unix_millis()
                .map_or(Value::Null, |v| json!({"some":v.to_string()}))
        && within("cpu-fuel", budget.cpu_fuel)
        && within("memory-bytes", budget.memory_bytes)
        && within("log-bytes", budget.log_bytes)
        && !value.to_string().contains("private-")
}
fn hex(value: &Value, length: usize) -> bool {
    value
        .as_str()
        .is_some_and(|s| s.len() == length && s.bytes().all(|v| v.is_ascii_hexdigit()))
}

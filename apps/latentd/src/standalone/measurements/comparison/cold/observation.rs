use latent_wasmtime::PreparationObserver;
use serde_json::{json, Value};

use super::{call::Clock, Result};

fn decimal_numbers(value: &mut Value) {
    match value {
        Value::Number(number) => *value = Value::String(number.to_string()),
        Value::Array(values) => values.iter_mut().for_each(decimal_numbers),
        Value::Object(values) => values.values_mut().for_each(decimal_numbers),
        _ => {}
    }
}

pub(super) fn snapshot(observer: &PreparationObserver, clock: Clock) -> Result<Value> {
    let began = clock.elapsed();
    let snapshot = observer.snapshot();
    let finished = clock.elapsed();
    let mut value = serde_json::to_value(snapshot)?;
    decimal_numbers(&mut value);
    Ok(
        json!({"collector_started_nanos":began.to_string(),"collector_finished_nanos":finished.to_string(),
        "snapshot":value}),
    )
}

pub(super) async fn compilation(
    observer: PreparationObserver,
    digest: String,
    clock: Clock,
) -> Result<Value> {
    let digest = digest.strip_prefix("sha256:").ok_or("cold digest prefix")?;
    if digest.len() != 64 {
        return Err("cold digest length".into());
    }
    let mut expected = [0_u8; 32];
    for (index, byte) in expected.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&digest[index * 2..index * 2 + 2], 16)?;
    }
    for _ in 0..128 {
        let current = observer.snapshot();
        let running = current.running.iter().any(|entry| {
            entry.component_digest == Some(expected) && entry.stage.name() == "component_new"
        });
        let completed = current.recent_stages.iter().any(|entry| {
            entry.component_digest == Some(expected) && entry.stage.name() == "component_new"
        });
        if running || completed {
            return Ok(
                json!({"running_when_observed":running,"observation":snapshot(&observer,clock)?}),
            );
        }
        tokio::time::timeout(
            std::time::Duration::from_secs(5),
            observer.wait_for_change(current.revision),
        )
        .await
        .map_err(|_| "cold compiler observation timed out")?
        .map_err(super::super::super::platform)?;
    }
    Err("cold compiler observation change bound".into())
}

use latent_scheduler::CellClass;
use serde_json::{json, Value};

use super::{MeasurementNode, Result};

pub(super) fn snapshot(node: &MeasurementNode) -> (u64, u64) {
    let snapshot = node.node.scheduler.observations(CellClass::Standard);
    (snapshot.granted, snapshot.total_wait_micros)
}

pub(super) fn complete(node: &MeasurementNode, before: (u64, u64), expected: u64) -> Result<Value> {
    let after = snapshot(node);
    let grants = after
        .0
        .checked_sub(before.0)
        .ok_or("scheduler grant counter regressed")?;
    let wait = after
        .1
        .checked_sub(before.1)
        .ok_or("scheduler wait counter regressed")?;
    if grants != expected {
        return Err("scheduler batch grant count mismatch".into());
    }
    Ok(
        json!({"granted_before":before.0.to_string(),"granted_after":after.0.to_string(),
        "total_wait_micros_before":before.1.to_string(),"total_wait_micros_after":after.1.to_string(),
        "grants":grants.to_string(),"wait_sum_micros":wait.to_string()}),
    )
}

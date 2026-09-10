use latent_core::PlatformError;
use serde_json::{json, Value};

use super::{Clock, Node, Result, Writer};

#[derive(Clone, Copy)]
pub(super) enum Operation {
    Publish,
    Apply,
    Resolve,
    Pin,
    Policy,
}

#[derive(Default, Clone, Copy)]
struct Count {
    attempted: u64,
    ok: u64,
    error: u64,
}

#[derive(Default)]
pub(super) struct Counts([Count; 5]);

impl Counts {
    pub fn issued(&mut self, node: &mut Node, operation: Operation) -> Result<()> {
        node.command(false)?;
        let row = &mut self.0[operation as usize];
        row.attempted = row
            .attempted
            .checked_add(1)
            .ok_or("catalog operation overflow")?;
        Ok(())
    }

    pub fn returned(&mut self, operation: Operation, succeeded: bool) {
        let row = &mut self.0[operation as usize];
        if succeeded {
            row.ok += 1;
        } else {
            row.error += 1;
        }
    }

    pub fn snapshot(&self) -> Value {
        Value::Object(["publications", "applies", "resolves", "pins", "policies"]
            .iter().zip(self.0).map(|(name,row)| (name.to_string(),
                json!({"attempted":row.attempted.to_string(),"returned_ok":row.ok.to_string(),
                    "returned_error":row.error.to_string()}))).collect())
    }

    pub fn complete(&self, expected: &Value, commands: u64) -> Result<()> {
        let mut total = 0;
        for (name, row) in ["publications", "applies", "resolves", "pins", "policies"]
            .iter()
            .zip(self.0)
        {
            if expected[name].as_str() != Some(row.attempted.to_string().as_str())
                || row.attempted != row.ok + row.error
            {
                return Err("catalog operation population incomplete".into());
            }
            total += row.attempted;
        }
        if total != commands {
            return Err("catalog command population mismatch".into());
        }
        Ok(())
    }
}

pub(super) fn error(value: &PlatformError) -> Value {
    json!({"code":format!("{:?}",value.code),"message":value.message,"retryable":value.retryable,
        "details":value.details.iter().map(|detail|json!({"kind":detail.kind,"fields":detail.fields})).collect::<Vec<_>>()})
}

pub(super) fn decimals(value: &mut Value) {
    match value {
        Value::Number(number) => *value = json!(number.to_string()),
        Value::Array(rows) => rows.iter_mut().for_each(decimals),
        Value::Object(rows) => rows.values_mut().for_each(decimals),
        _ => {}
    }
}

pub(super) fn verification(node: &Node) -> Result<Value> {
    let v = node.artifacts.verification_snapshot();
    let values = [
        v.full_fetch_attempts,
        v.metadata_fetch_attempts,
        v.component_verification_attempts,
        v.component_bytes_hashed,
        v.metadata_fingerprint_attempts,
    ];
    if values.contains(&u64::MAX) {
        return Err("catalog verification counter saturated".into());
    }
    Ok(
        json!({"full_fetch_attempts":v.full_fetch_attempts.to_string(),
        "metadata_fetch_attempts":v.metadata_fetch_attempts.to_string(),
        "component_verification_attempts":v.component_verification_attempts.to_string(),
        "component_bytes_hashed":v.component_bytes_hashed.to_string(),
        "metadata_fingerprint_attempts":v.metadata_fingerprint_attempts.to_string()}),
    )
}

pub(super) fn checkpoint(
    node: &Node,
    writer: &mut Writer,
    clock: Clock,
    label: &str,
    count: u32,
    old_pin: bool,
) -> Result<()> {
    let resources = node.owner.backend.resource_snapshot();
    if resources.stores_created != 0
        || resources.active_invocations != 0
        || resources.live_stores != 0
        || resources.live_host_states != 0
        || resources.live_component_instances != 0
        || resources.live_temporary_buffers != 0
        || resources.live_cancellation_probes != 0
    {
        return Err("catalog workload created guest ownership".into());
    }
    let mut compiler = serde_json::to_value(node.owner.backend.compiler_snapshot())?;
    let mut accounting = serde_json::to_value(node.owner.backend.cache_accounting_snapshot())?;
    decimals(&mut compiler);
    decimals(&mut accounting);
    writer.sample(&json!({"kind":"checkpoint","label":label,"count":count.to_string(),"old_pin":old_pin,
        "node":node.sample(label)?,"verification":verification(node)?,"compiler":compiler,"accounting":accounting,
        "preparation":super::super::cold::observation::snapshot(&node.owner.backend.preparation_observer(),clock)?,
        "cleanup":node.owner.cleanup_snapshot(),"memory":super::super::engine::resources::capture(label,clock)?,
        "cpu":super::super::budget::cpu::sample(clock)?}))
}

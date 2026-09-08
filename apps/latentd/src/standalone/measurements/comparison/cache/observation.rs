use serde::Serialize;
use serde_json::{json, Value};

use super::{cold, Node, Result, Writer};

pub(super) fn decimal<T: Serialize>(value: &T) -> Result<Value> {
    fn visit(value: &mut Value) {
        match value {
            Value::Number(number) => *value = Value::String(number.to_string()),
            Value::Array(values) => values.iter_mut().for_each(visit),
            Value::Object(values) => values.values_mut().for_each(visit),
            _ => {}
        }
    }
    let mut value = serde_json::to_value(value)?;
    visit(&mut value);
    Ok(value)
}

/// Only a sequence cursor is retained; archived stage rows are never accumulated.
#[derive(Default)]
pub(super) struct Events {
    next: u64,
}

impl Events {
    pub fn export(
        &mut self,
        node: &Node,
        writer: &mut Writer,
        clock: cold::call::Clock,
        label: &str,
    ) -> Result<()> {
        let started = clock.elapsed();
        let snapshot = node.owner.backend.preparation_observer().snapshot();
        let finished = clock.elapsed();
        let before = self.next;
        let mut rows = Vec::new();
        for event in &snapshot.recent_stages {
            if event.sequence < self.next {
                continue;
            }
            if event.sequence != self.next {
                return Err("cache preparation event sequence gap".into());
            }
            rows.push(decimal(event)?);
            self.next = self
                .next
                .checked_add(1)
                .ok_or("cache preparation sequence overflow")?;
        }
        if snapshot.dropped_running_entries != 0 {
            return Err("cache preparation running observation gap".into());
        }
        writer.sample(&json!({"kind":"preparation-events","label":label,
            "collector_started_nanos":started.to_string(),"collector_finished_nanos":finished.to_string(),
            "first_sequence":before.to_string(),"next_sequence":self.next.to_string(),"events":rows,
            "observed_nanos":snapshot.observed_nanos.to_string(),"stages":decimal(&snapshot.stages)?,
            "ring_overwrites":snapshot.dropped_stage_observations.to_string(),"compiler":decimal(&snapshot.compiler)?}))
    }
}

pub(super) fn checkpoint(
    node: &Node,
    writer: &mut Writer,
    clock: cold::call::Clock,
    label: &str,
    idle: bool,
) -> Result<()> {
    let sample = node.sample(label)?;
    if idle {
        super::super::super::soak::assert_idle(&sample)?;
    }
    let accounting = node.owner.backend.cache_accounting_snapshot();
    writer.sample(&json!({"kind":"checkpoint","label":label,"node":sample,
        "accounting":decimal(&accounting)?,
        "observer":cold::observation::snapshot(&node.owner.backend.preparation_observer(),clock)?}))?;
    if let Some(runtime) = accounting.runtimes {
        let expected = match label {
            "ownership-empty" => Some((0, 0, 0)),
            "held-two-ready" | "held-ready-and-active" => Some((1, 1, 0)),
            "evicted-held-ready-and-active"
            | "evicted-held-ready"
            | "resident-new-and-evicted-old" => Some((5, 4, 1)),
            "released-old-ready" | "ownership-complete" => Some((4, 4, 0)),
            _ => None,
        };
        if expected.is_some_and(|counts| {
            counts
                != (
                    runtime.live.runtimes,
                    runtime.resident.runtimes,
                    runtime.evicted_live.runtimes,
                )
        }) || runtime.unpublished.runtimes != 0
        {
            return Err("cache unique runtime ownership mismatch".into());
        }
    }
    Ok(())
}

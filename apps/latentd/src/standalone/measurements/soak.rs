mod call;
mod idle;
#[cfg(test)]
mod tests;

use std::collections::BTreeMap;

use serde_json::{json, Value};

use super::{MeasurementNode, MeasurementPlan, MeasurementWriter, Profile, Result};
pub(super) use call::{execute, finish, wait_running, Case, Observation};
pub(super) use idle::assert_idle;

pub(super) async fn run(
    node: &MeasurementNode,
    plan: &MeasurementPlan,
    writer: &mut MeasurementWriter,
) -> Result<Value> {
    for fixture in [
        &node.fixtures.echo,
        &node.fixtures.generic,
        &node.fixtures.capabilities,
    ] {
        writer.write("publication", &node.publish(fixture).await?)?;
    }
    checkpoint(node, writer, "before-warmup")?;
    let mut warmup = Batch::default();
    for index in 0..plan.warmup_invocations {
        let case = if plan.profile == Profile::Full {
            cycle(index)
        } else {
            match index {
                0 => Case::Echo,
                1 => Case::Context,
                _ => Case::Success,
            }
        };
        warmup.add(&execute(node, case, &format!("soak-warm-{index}")).await?)?;
        if warmup.latencies.len() == plan.batch_size as usize
            || index + 1 == plan.warmup_invocations
        {
            warmup.write(
                node,
                writer,
                "warmup",
                index / plan.batch_size,
                index + 1 - u32::try_from(warmup.latencies.len())?,
            )?;
            warmup = Batch::default();
        }
    }
    checkpoint(node, writer, "after-warmup")?;
    let mut totals = BTreeMap::new();
    for batch_index in 0..plan.measured_invocations / plan.batch_size {
        let first = batch_index * plan.batch_size;
        let mut batch = Batch::default();
        for offset in (0..plan.batch_size).step_by(2) {
            let left_index = first + offset;
            let right_index = left_index + 1;
            let left_id = format!("soak-{left_index}");
            let right_id = format!("soak-{right_index}");
            let (left, right) = tokio::join!(
                execute(node, cycle(left_index), &left_id),
                execute(node, cycle(right_index), &right_id)
            );
            batch.add(&left?)?;
            batch.add(&right?)?;
        }
        for (case, count) in &batch.outcomes {
            *totals.entry(*case).or_insert(0_u64) += count;
        }
        batch.write(node, writer, "measured", batch_index, first)?;
    }
    checkpoint(node, writer, "final")?;
    Ok(
        json!({"warmup_invocations":plan.warmup_invocations.to_string(),"measured_invocations":plan.measured_invocations.to_string(),
        "measured_batches":(plan.measured_invocations/plan.batch_size).to_string(),"cycle_length":"20",
        "outcome_counts":decimal_counts(&totals),"work":node.work()}),
    )
}

pub(super) fn checkpoint(
    node: &MeasurementNode,
    writer: &mut MeasurementWriter,
    phase: &str,
) -> Result<()> {
    let resources = node.sample(phase)?;
    assert_idle(&resources)?;
    writer.write("checkpoint", &json!({"phase":phase,"resources":resources}))?;
    Ok(())
}

fn cycle(index: u32) -> Case {
    match index % 20 {
        1 => Case::Domain,
        3 => Case::Trap,
        5 => Case::Fuel,
        7 => Case::Memory,
        9 => Case::Deadline,
        11 => Case::Cancel,
        13 => Case::LogDenied,
        14 => Case::LogAccepted,
        15 => Case::Context,
        16 => Case::Malformed,
        18 => Case::FreshStore,
        4 | 17 => Case::Echo,
        _ => Case::Success,
    }
}

#[derive(Default)]
struct Batch {
    latencies: Vec<String>,
    outcomes: BTreeMap<&'static str, u64>,
    cpu: u64,
    log: u64,
    peak: u64,
}

impl Batch {
    fn add(&mut self, observation: &Observation) -> Result<()> {
        self.latencies.push(observation.elapsed.to_string());
        *self.outcomes.entry(observation.case).or_default() += 1;
        self.cpu = self
            .cpu
            .checked_add(observation.consumption.cpu_fuel)
            .ok_or("fuel sum overflow")?;
        self.log = self
            .log
            .checked_add(observation.consumption.log_bytes)
            .ok_or("log sum overflow")?;
        self.peak = self.peak.max(observation.consumption.peak_memory_bytes);
        Ok(())
    }

    fn write(
        &self,
        node: &MeasurementNode,
        writer: &mut MeasurementWriter,
        stage: &str,
        batch: u32,
        first: u32,
    ) -> Result<()> {
        let resources = node.sample(stage)?;
        assert_idle(&resources)?;
        writer.write("soak-batch", &json!({"stage":stage,"batch_index":batch.to_string(),"first_invocation":first.to_string(),
            "attempts":self.latencies.len().to_string(),"concurrency":if stage=="warmup" {"1"}else{"2"},
            "outcome_counts":decimal_counts(&self.outcomes),"rpc_latency_micros":self.latencies,
            "consumed_cpu_fuel":self.cpu.to_string(),"consumed_log_bytes":self.log.to_string(),
            "peak_memory_bytes":self.peak.to_string(),"resources":resources}))?;
        Ok(())
    }
}

fn decimal_counts(counts: &BTreeMap<&'static str, u64>) -> BTreeMap<&'static str, String> {
    counts
        .iter()
        .map(|(key, value)| (*key, value.to_string()))
        .collect()
}

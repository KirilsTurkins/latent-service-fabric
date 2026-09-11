mod input;
mod management;
mod preparation;
mod queue;
mod routes;
mod scheduling;

use serde_json::{json, Value};
use std::time::{Duration, Instant};

use super::{
    platform,
    soak::{self, execute, Case, Observation},
    MeasurementNode, MeasurementPlan, MeasurementWriter, Profile, Result,
};

pub(super) async fn run(
    node: &MeasurementNode,
    plan: &MeasurementPlan,
    writer: &mut MeasurementWriter,
) -> Result<Value> {
    input::write(node, writer)?;
    for fixture in [
        &node.fixtures.echo,
        &node.fixtures.generic,
        &node.fixtures.capabilities,
    ] {
        writer.write("publication", &node.publish(fixture).await?)?;
    }
    soak::checkpoint(node, writer, "before-warmup")?;
    preparation::initial(node, writer).await?;
    let warmup = match plan.profile {
        Profile::Smoke => 1,
        Profile::Full => 40,
    };
    for index in 0..warmup {
        let before = node.node.backend.cache_snapshot();
        let observation = execute(node, Case::Echo, &format!("bench-warm-{index}")).await?;
        preparation::require_reuse(node, &before)?;
        write_call(writer, "warmup", index, &observation)?;
    }
    // Compilation is isolated from cause-specific failure/recovery timings.
    preparation::prewarm_failures(node).await?;
    soak::checkpoint(node, writer, "after-warmup")?;
    for index in 0..plan.benchmark_samples {
        preparation::pair(node, writer, index).await?;
        let left_id = format!("bench-capacity-{index}-0");
        let right_id = format!("bench-capacity-{index}-1");
        let scheduling_before = scheduling::snapshot(node);
        let started = Instant::now();
        let (left, right) = tokio::join!(
            execute(node, Case::Echo, &left_id),
            execute(node, Case::Echo, &right_id)
        );
        let elapsed = started.elapsed();
        write_call(writer, "offered_capacity_rpc", index, &left?)?;
        write_call(writer, "offered_capacity_rpc", index, &right?)?;
        let scheduling = scheduling::complete(node, scheduling_before, 2)?;
        write_batch(
            writer,
            "offered_capacity_rpc",
            index,
            elapsed,
            2,
            0,
            &scheduling,
        )?;
        Box::pin(queue::sample(node, writer, index)).await?;
        for case in [
            Case::Domain,
            Case::Trap,
            Case::Fuel,
            Case::Memory,
            Case::Deadline,
            Case::Cancel,
        ] {
            let name = case.name();
            let observation = execute(node, case, &format!("bench-{name}-{index}")).await?;
            write_call(writer, &format!("fault_{name}"), index, &observation)?;
            let recovery =
                execute(node, Case::Echo, &format!("bench-recovery-{name}-{index}")).await?;
            write_call(writer, &format!("recovery_{name}"), index, &recovery)?;
        }
        routes::sample(node, writer, index)?;
        Box::pin(management::sample(node, writer, index)).await?;
        soak::checkpoint(node, writer, "sample-complete")?;
    }
    soak::checkpoint(node, writer, "final")?;
    let planned = u64::from(warmup) + u64::from(plan.benchmark_samples) * 21;
    if node.work().invoke_attempts != planned {
        return Err("benchmark exact Invoke count mismatch".into());
    }
    Ok(
        json!({"samples_per_boundary":plan.benchmark_samples.to_string(),"warmup_invocations":warmup.to_string(),
        "planned_invoke_attempts":planned.to_string(),"actual_invoke_attempts":node.work().invoke_attempts.to_string(),
        "offered_capacity_concurrency":"2","queue_holder_count":"2","queue_waiter_count":"3","work":node.work()}),
    )
}

fn write_call(
    writer: &mut MeasurementWriter,
    boundary: &str,
    sample: u32,
    observation: &Observation,
) -> Result<()> {
    writer.write(
        "benchmark-call",
        &json!({"boundary":boundary,"sample":sample.to_string(),"invocation":observation.value()}),
    )?;
    Ok(())
}

fn write_batch(
    writer: &mut MeasurementWriter,
    boundary: &str,
    sample: u32,
    elapsed: Duration,
    attempted: u32,
    cancelled: u32,
    scheduler: &Value,
) -> Result<()> {
    writer.write("benchmark-batch", &json!({"boundary":boundary,"sample":sample.to_string(),"attempted_invocations":attempted.to_string(),"successful_invocations":(attempted-cancelled).to_string(),"cancelled_invocations":cancelled.to_string(),"elapsed_micros":elapsed.as_micros().to_string(),"offered_concurrency":attempted.to_string(),"includes_retained_status_validation":true,"scheduler":scheduler}))?;
    Ok(())
}

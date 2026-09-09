use std::time::Instant;

use rustix::time::{clock_getres, clock_gettime, ClockId};
use serde_json::{json, Value};
use wasmtime::component::Val;

use crate::preparation_observer::{
    sample_thread_cpu, PreparationThreadCpuInterval, PreparationThreadIdentity,
};
use crate::values::ValueCodecLimits;

use super::{fixtures::Fixture, frames, input::Plan, output, ProbeResult};

pub(super) fn direction(
    direction: &str,
    fixture: &Fixture,
    values: &[Val],
    limits: ValueCodecLimits,
    plan: &Plan,
    origin: Instant,
    identity: PreparationThreadIdentity,
) -> ProbeResult<Value> {
    let warmup = match direction {
        "decode" => frames::decode_loop(fixture, limits, plan.warmup_iterations),
        "encode" => frames::encode_loop(fixture, values, limits, plan.warmup_iterations),
        _ => return Err("unknown codec direction".into()),
    };
    let resolution = output::nanos(clock_getres(ClockId::ThreadCPUTime))?;
    let before = sample_thread_cpu().ok_or("codec CPU task unavailable")?;
    let cpu_before = output::nanos(clock_gettime(ClockId::ThreadCPUTime))?;
    let started = Instant::now();
    let batch = if warmup.failure.is_some() {
        frames::Batch::default()
    } else if direction == "decode" {
        super::measured_decode_and_drop(fixture, limits, plan.measured_iterations)
    } else {
        super::measured_encode_and_drop(fixture, values, limits, plan.measured_iterations)
    };
    let finished = Instant::now();
    let cpu_after = output::nanos(clock_gettime(ClockId::ThreadCPUTime))?;
    let after = sample_thread_cpu().ok_or("codec CPU task unavailable")?;
    if before.identity != identity
        || after.identity != identity
        || before.user_ticks > after.user_ticks
        || before.system_ticks > after.system_ticks
        || cpu_before > cpu_after
        || resolution == 0
    {
        return Err("codec clock or task identity changed".into());
    }
    let failure = if warmup.failure.is_some() {
        warmup.failure_json("warmup")
    } else {
        batch.failure_json("measured")
    };
    Ok(json!({
        "direction": direction, "warmup_attempted": warmup.attempted.to_string(),
        "warmup_completed": warmup.completed.to_string(), "warmup_successes": warmup.successes.to_string(),
        "measured_attempted": batch.attempted.to_string(), "measured_completed": batch.completed.to_string(),
        "measured_successes": batch.successes.to_string(), "observed_arity_or_bytes": batch.observed.to_string(),
        "started_nanos": started.duration_since(origin).as_nanos().to_string(),
        "finished_nanos": finished.duration_since(origin).as_nanos().to_string(),
        "elapsed_nanos": finished.duration_since(started).as_nanos().to_string(),
        "cpu": {"clock": "CLOCK_THREAD_CPUTIME_ID", "resolution_nanos": resolution.to_string(),
            "before_nanos": cpu_before.to_string(), "after_nanos": cpu_after.to_string()},
        "coarse_thread_cpu": PreparationThreadCpuInterval { before, after }, "failure": failure,
    }))
}

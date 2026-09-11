use std::time::Instant;

use latent_core::ActivationId;
use latent_wire::invocation::proto;
use serde_json::{json, Value};

use super::super::soak;
use super::{evidence, node::Node, writer::Writer, Result, INPUT};

pub(super) async fn run(node: &mut Node, writer: &mut Writer, iteration: u32) -> Result<()> {
    run_with_cold_start(node, writer, iteration, false).await
}

pub(super) async fn run_with_cold_start(
    node: &mut Node,
    writer: &mut Writer,
    iteration: u32,
    cold_start: bool,
) -> Result<()> {
    let id = format!("baseline-warm-echo-{iteration:08}");
    let result = invoke(node, iteration, &id, cold_start).await;
    match result {
        Ok(sample) => writer.sample(&sample),
        Err(error) => {
            // Retain the attempted identity even when no successful response
            // or complete terminal/resource observation can be obtained.
            writer.sample(
                &json!({"iteration":iteration.to_string(),"activation_id":id,
                "outcome":"failed","reason":"comparison-invocation-failed"}),
            )?;
            Err(error)
        }
    }
}

async fn invoke(node: &mut Node, iteration: u32, id: &str, cold_start: bool) -> Result<Value> {
    let mut request = node.fixture.request("echo", id, &json!([INPUT]));
    let budget = request.budget.as_mut().ok_or("comparison budget missing")?;
    budget.cpu_fuel = 10_000_000_000;
    budget.memory_bytes = 16_777_216;
    budget.wall_time_limit_millis = Some(1000);
    budget.log_bytes = 16384;
    let before = node.owner.backend.cache_snapshot();
    let started = Instant::now();
    let response = node.invoke(request).await?;
    let elapsed = started.elapsed().as_micros();
    if response.activation_id != id
        || response.release_digest != node.fixture.release_digest
        || response.revision_id.is_empty()
        || response.route_generation != 1
    {
        return Err("comparison resolved receipt identity mismatch".into());
    }
    let Some(proto::invoke_response::Result::Success(success)) = &response.result else {
        return Err("comparison echo was not successful".into());
    };
    if success.media_type != super::super::fixtures::MEDIA
        || serde_json::from_slice::<Value>(&success.payload)? != json!([{"ok":INPUT}])
    {
        return Err("comparison semantic output mismatch".into());
    }
    let consumption = response
        .consumption
        .as_ref()
        .ok_or("comparison terminal consumption absent")?;
    if consumption.cpu_fuel == 0
        || consumption.cpu_fuel >= 10_000_000_000
        || consumption.peak_memory_bytes == 0
        || consumption.peak_memory_bytes > 16_777_216
        || consumption.wall_time_micros >= 1_000_000
        || consumption.log_bytes == 0
        || consumption.log_bytes > 16384
    {
        return Err("comparison echo exhausted its common resource grant".into());
    }
    let status = node.status(id).await?;
    if status.activation_id != id
        || status.terminal_state.as_deref() != Some("completed")
        || !matches!(
            status.terminal_outcome,
            Some(proto::activation_status::TerminalOutcome::Succeeded(_))
        )
        || status.final_consumption != response.consumption
    {
        return Err("comparison retained terminal outcome differs".into());
    }
    let timing = node
        .owner
        .backend
        .take_invocation_timing(&ActivationId(id.to_owned()))
        .ok_or("comparison completed backend timing missing")?;
    let after = node.owner.backend.cache_snapshot();
    if after.entries != 1
        || after.misses != 1
        || after.hits != before.hits + u64::from(!cold_start)
        || after.evictions != 0
        || after.invalidations != 0
        || (cold_start && (iteration != 0 || before.entries != 0 || before.misses != 0))
    {
        return Err("comparison RPC did not reuse the single published preparation".into());
    }
    let sample = node.sample(&format!("after-warm-echo-{iteration:08}"))?;
    soak::assert_idle(&sample)?;
    Ok(json!({"iteration":iteration.to_string(),"activation_id":id,
        "receipt":{"release_digest":response.release_digest,"revision_id":response.revision_id,
            "route_generation":response.route_generation.to_string(),"terminal_state":status.terminal_state,
            "retained_consumption_matches":status.final_consumption == response.consumption},
        "semantic_output_sha256":evidence::input()["sha256"],"outcome":"success",
        "elapsed_micros":elapsed.to_string(),"timing":evidence::timing(timing),
        "consumption":{"cpu_fuel":consumption.cpu_fuel.to_string(),"peak_memory_bytes":consumption.peak_memory_bytes.to_string(),
            "wall_time_micros":consumption.wall_time_micros.to_string(),"log_bytes":consumption.log_bytes.to_string()},
        "post_call":sample}))
}

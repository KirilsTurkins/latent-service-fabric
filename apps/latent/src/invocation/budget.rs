use serde::Deserialize;

use super::proto;
use crate::{args::InvokeArgs, error::Failure, input};

#[derive(Deserialize)]
#[serde(default, rename_all = "camelCase", deny_unknown_fields)]
struct Budget {
    cpu_fuel: u64,
    memory_bytes: u64,
    wall_time_limit_millis: Option<u64>,
    child_calls: u32,
    outbound_requests: u32,
    state_read_bytes: u64,
    state_write_bytes: u64,
    blob_read_bytes: u64,
    blob_write_bytes: u64,
    log_bytes: u64,
    effect_count: u32,
}
impl Default for Budget {
    fn default() -> Self {
        Self {
            cpu_fuel: 100_000_000,
            memory_bytes: 64 * 1024 * 1024,
            wall_time_limit_millis: None,
            child_calls: 0,
            outbound_requests: 0,
            state_read_bytes: 0,
            state_write_bytes: 0,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            log_bytes: 16 * 1024,
            effect_count: 0,
        }
    }
}

pub(super) fn resolve(args: &InvokeArgs) -> Result<proto::ResourceBudget, Failure> {
    let mut budget = args
        .budget
        .as_ref()
        .map(|path| {
            let bytes = input::read(path, 16 * 1024, "budget")?;
            serde_json::from_slice::<Budget>(&bytes).map_err(|_| invalid())
        })
        .transpose()?
        .unwrap_or_default();
    if let Some(value) = args.cpu_fuel {
        budget.cpu_fuel = value;
    }
    if let Some(value) = args.memory_bytes {
        budget.memory_bytes = value;
    }
    if let Some(value) = args.wall_time_ms {
        budget.wall_time_limit_millis = Some(value);
    }
    if let Some(value) = args.log_bytes {
        budget.log_bytes = value;
    }
    let result = proto::ResourceBudget {
        cpu_fuel: budget.cpu_fuel,
        memory_bytes: budget.memory_bytes,
        wall_time_limit_millis: budget.wall_time_limit_millis,
        child_calls: budget.child_calls,
        outbound_requests: budget.outbound_requests,
        state_read_bytes: budget.state_read_bytes,
        state_write_bytes: budget.state_write_bytes,
        blob_read_bytes: budget.blob_read_bytes,
        blob_write_bytes: budget.blob_write_bytes,
        log_bytes: budget.log_bytes,
        effect_count: budget.effect_count,
    };
    latent_wire::invocation::budget_from_proto(result)
        .validate_phase1_request()
        .map_err(|_| invalid())?;
    if result.cpu_fuel > 10_000_000_000
        || result.memory_bytes > 1024 * 1024 * 1024
        || result.log_bytes > 64 * 1024 * 1024
        || result
            .wall_time_limit_millis
            .is_some_and(|value| value > 300_000)
    {
        return Err(invalid());
    }
    Ok(result)
}

fn invalid() -> Failure {
    Failure::local("invalid-budget", "Invalid Phase 1 resource budget.")
}

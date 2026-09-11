use latent_core::ResourceBudget;

use super::super::proto;

/// Preserves every grant and optional relative wall-time value.
#[must_use]
pub fn control_budget_from_proto(value: &proto::ResourceBudget) -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: value.cpu_fuel,
        memory_bytes: value.memory_bytes,
        wall_time_limit_millis: value.wall_time_limit_millis,
        child_calls: value.child_calls,
        outbound_requests: value.outbound_requests,
        state_read_bytes: value.state_read_bytes,
        state_write_bytes: value.state_write_bytes,
        blob_read_bytes: value.blob_read_bytes,
        blob_write_bytes: value.blob_write_bytes,
        log_bytes: value.log_bytes,
        effect_count: value.effect_count,
    }
}

/// Conversion preserves unsupported later-phase values; request validation rejects them.
#[must_use]
pub fn control_budget_to_proto(value: &ResourceBudget) -> proto::ResourceBudget {
    proto::ResourceBudget {
        cpu_fuel: value.cpu_fuel,
        memory_bytes: value.memory_bytes,
        wall_time_limit_millis: value.wall_time_limit_millis,
        child_calls: value.child_calls,
        outbound_requests: value.outbound_requests,
        state_read_bytes: value.state_read_bytes,
        state_write_bytes: value.state_write_bytes,
        blob_read_bytes: value.blob_read_bytes,
        blob_write_bytes: value.blob_write_bytes,
        log_bytes: value.log_bytes,
        effect_count: value.effect_count,
    }
}

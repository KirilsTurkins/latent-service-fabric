//! Hierarchical invocation resource budgets.

/// Maximum resources delegated to an activation and its descendants.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResourceBudget {
    pub cpu_fuel: u64,
    pub memory_bytes: u64,
    pub wall_deadline_unix_millis: Option<u64>,
    pub child_calls: u32,
    pub outbound_requests: u32,
    pub state_read_bytes: u64,
    pub state_write_bytes: u64,
    pub blob_read_bytes: u64,
    pub blob_write_bytes: u64,
    pub log_bytes: u64,
    pub effect_count: u32,
}

/// Resources consumed by a completed or interrupted activation.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct BudgetConsumption {
    pub cpu_fuel: u64,
    pub peak_memory_bytes: u64,
    pub wall_time_micros: u64,
    pub child_calls: u32,
    pub outbound_requests: u32,
    pub state_read_bytes: u64,
    pub state_write_bytes: u64,
    pub blob_read_bytes: u64,
    pub blob_write_bytes: u64,
    pub log_bytes: u64,
    pub effect_count: u32,
}

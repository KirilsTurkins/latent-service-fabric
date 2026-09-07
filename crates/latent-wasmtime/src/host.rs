use std::collections::VecDeque;
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Instant;

use latent_core::{
    ActivationId, InvocationPrincipal as FabricPrincipal, Metadata, PrincipalKind,
    ResourceBudget as FabricBudget,
};
use wasmtime::{ResourceLimiter, StoreLimits, StoreLimitsBuilder};

use crate::bindings::latent::context::context;
use crate::bindings::latent::log::log;
use crate::config::WasmtimeConfig;

mod request_context;
pub(crate) use request_context::validate_request_context;

const MAX_LOG_MESSAGE_BYTES: usize = 256;
const MAX_LOG_FIELDS: usize = 16;
const MAX_LOG_FIELD_NAME_BYTES: usize = 64;
const MAX_LOG_FIELD_VALUE_BYTES: usize = 256;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CapturedLog {
    pub activation_id: ActivationId,
    pub level: String,
    pub message: String,
    pub fields: Metadata,
}

#[derive(Debug)]
struct LogSinkState {
    entries: VecDeque<CapturedLog>,
    bytes: usize,
}

#[derive(Debug, Clone)]
pub struct BoundedLogSink {
    state: Arc<Mutex<LogSinkState>>,
    maximum_entries: usize,
    maximum_bytes: usize,
}

impl BoundedLogSink {
    pub fn new(maximum_entries: usize, maximum_bytes: usize) -> Self {
        Self {
            state: Arc::new(Mutex::new(LogSinkState {
                entries: VecDeque::new(),
                bytes: 0,
            })),
            maximum_entries,
            maximum_bytes,
        }
    }

    pub fn snapshot(&self) -> Vec<CapturedLog> {
        self.lock_state().entries.iter().cloned().collect()
    }

    pub fn snapshot_for(&self, activation_id: &ActivationId) -> Vec<CapturedLog> {
        self.lock_state()
            .entries
            .iter()
            .filter(|entry| &entry.activation_id == activation_id)
            .cloned()
            .collect()
    }

    pub fn clear(&self) {
        let mut state = self.lock_state();
        state.entries.clear();
        state.bytes = 0;
    }

    pub(crate) fn publish(&self, entries: Vec<CapturedLog>) {
        let mut state = self.lock_state();
        for entry in entries {
            let entry_bytes = captured_log_size(&entry);
            if entry_bytes > self.maximum_bytes || self.maximum_entries == 0 {
                continue;
            }
            while state.entries.len() >= self.maximum_entries
                || state.bytes.saturating_add(entry_bytes) > self.maximum_bytes
            {
                let Some(evicted) = state.entries.pop_front() else {
                    break;
                };
                state.bytes = state.bytes.saturating_sub(captured_log_size(&evicted));
            }
            state.bytes = state.bytes.saturating_add(entry_bytes);
            state.entries.push_back(entry);
        }
    }

    fn lock_state(&self) -> MutexGuard<'_, LogSinkState> {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

fn captured_log_size(entry: &CapturedLog) -> usize {
    entry.activation_id.0.len()
        + entry.level.len()
        + entry.message.len()
        + entry
            .fields
            .iter()
            .map(|(name, value)| name.len() + value.len())
            .sum::<usize>()
}

#[derive(Debug)]
pub(crate) struct InvocationLogBuffer {
    activation_id: ActivationId,
    maximum_entries: usize,
    maximum_bytes: usize,
    bytes: usize,
    entries: Vec<CapturedLog>,
}

impl InvocationLogBuffer {
    fn new(
        activation_id: ActivationId,
        maximum_entries: usize,
        configured_maximum_bytes: usize,
        delegated_log_bytes: u64,
    ) -> Self {
        let delegated = usize::try_from(delegated_log_bytes).unwrap_or(usize::MAX);
        Self {
            activation_id,
            maximum_entries,
            maximum_bytes: configured_maximum_bytes.min(delegated),
            bytes: 0,
            entries: Vec::new(),
        }
    }

    fn write(
        &mut self,
        level: log::Level,
        message: String,
        fields: Vec<log::Field>,
    ) -> Result<bool, log::LogError> {
        if message.len() > MAX_LOG_MESSAGE_BYTES {
            return Err(log::LogError::InvalidField("message-too-large".to_owned()));
        }
        if fields.len() > MAX_LOG_FIELDS {
            return Err(log::LogError::InvalidField("too-many-fields".to_owned()));
        }

        let mut normalized = Metadata::new();
        for field in fields {
            if field.name.is_empty()
                || field.name.len() > MAX_LOG_FIELD_NAME_BYTES
                || !field
                    .name
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-' | b'.'))
            {
                return Err(log::LogError::InvalidField("invalid-field-name".to_owned()));
            }
            if field.value.len() > MAX_LOG_FIELD_VALUE_BYTES {
                return Err(log::LogError::InvalidField(field.name));
            }
            if normalized.insert(field.name.clone(), field.value).is_some() {
                return Err(log::LogError::InvalidField(field.name));
            }
        }

        let entry = CapturedLog {
            activation_id: self.activation_id.clone(),
            level: level_name(level).to_owned(),
            message,
            fields: normalized,
        };
        let entry_bytes = captured_log_size(&entry);
        if self.entries.len() >= self.maximum_entries
            || self.bytes.saturating_add(entry_bytes) > self.maximum_bytes
        {
            return Err(log::LogError::BudgetExhausted);
        }

        self.bytes = self.bytes.saturating_add(entry_bytes);
        self.entries.push(entry);
        Ok(true)
    }

    pub(crate) fn entries(&self) -> Vec<CapturedLog> {
        self.entries.clone()
    }

    pub(crate) fn bytes(&self) -> u64 {
        u64::try_from(self.bytes).unwrap_or(u64::MAX)
    }
}

fn level_name(level: log::Level) -> &'static str {
    match level {
        log::Level::Trace => "trace",
        log::Level::Debug => "debug",
        log::Level::Info => "info",
        log::Level::Warn => "warn",
        log::Level::Error => "error",
    }
}

#[derive(Debug)]
struct PendingMemoryGrowth {
    bytes: usize,
    previous_peak_memory_bytes: usize,
}

#[derive(Debug)]
pub(crate) struct TrackingLimiter {
    limits: StoreLimits,
    maximum_memory_bytes: usize,
    current_memory_bytes: usize,
    peak_memory_bytes: usize,
    pending_memory_growth: Option<PendingMemoryGrowth>,
}

impl TrackingLimiter {
    #[cfg(test)]
    pub(crate) fn new(maximum_memory_bytes: usize) -> Self {
        Self::with_config(maximum_memory_bytes, &WasmtimeConfig::default())
    }

    fn with_config(maximum_memory_bytes: usize, config: &WasmtimeConfig) -> Self {
        Self {
            limits: StoreLimitsBuilder::new()
                .memory_size(maximum_memory_bytes)
                .table_elements(config.maximum_table_elements)
                .instances(config.maximum_instances_per_store)
                .tables(config.maximum_tables_per_store)
                .memories(config.maximum_memories_per_store)
                .trap_on_grow_failure(true)
                .build(),
            maximum_memory_bytes,
            current_memory_bytes: 0,
            peak_memory_bytes: 0,
            pending_memory_growth: None,
        }
    }

    pub(crate) fn peak_memory_bytes(&self) -> u64 {
        u64::try_from(self.peak_memory_bytes).unwrap_or(u64::MAX)
    }

    #[cfg(test)]
    fn current_memory_bytes(&self) -> usize {
        self.current_memory_bytes
    }
}

impl ResourceLimiter for TrackingLimiter {
    fn memory_growing(
        &mut self,
        current: usize,
        desired: usize,
        maximum: Option<usize>,
    ) -> wasmtime::Result<bool> {
        // A later limiter callback means the previous permitted growth completed.
        self.pending_memory_growth = None;

        let growth = desired.saturating_sub(current);
        let aggregate = self
            .current_memory_bytes
            .checked_add(growth)
            .ok_or_else(|| wasmtime::Error::msg("aggregate linear-memory accounting overflow"))?;
        if aggregate > self.maximum_memory_bytes {
            return Err(wasmtime::Error::msg(format!(
                "aggregate linear-memory budget exceeded: requested {aggregate} bytes, limit {} bytes",
                self.maximum_memory_bytes
            )));
        }

        let allowed = self.limits.memory_growing(current, desired, maximum)?;
        if allowed {
            let previous_peak_memory_bytes = self.peak_memory_bytes;
            self.current_memory_bytes = aggregate;
            self.peak_memory_bytes = self.peak_memory_bytes.max(aggregate);
            self.pending_memory_growth = Some(PendingMemoryGrowth {
                bytes: growth,
                previous_peak_memory_bytes,
            });
        }
        Ok(allowed)
    }

    fn memory_grow_failed(&mut self, error: wasmtime::Error) -> wasmtime::Result<()> {
        if let Some(pending) = self.pending_memory_growth.take() {
            self.current_memory_bytes = self.current_memory_bytes.saturating_sub(pending.bytes);
            self.peak_memory_bytes = pending.previous_peak_memory_bytes;
        }
        self.limits.memory_grow_failed(error)
    }

    fn table_growing(
        &mut self,
        current: usize,
        desired: usize,
        maximum: Option<usize>,
    ) -> wasmtime::Result<bool> {
        self.pending_memory_growth = None;
        self.limits.table_growing(current, desired, maximum)
    }

    fn table_grow_failed(&mut self, error: wasmtime::Error) -> wasmtime::Result<()> {
        self.limits.table_grow_failed(error)
    }

    fn instances(&self) -> usize {
        self.limits.instances()
    }

    fn tables(&self) -> usize {
        self.limits.tables()
    }

    fn memories(&self) -> usize {
        self.limits.memories()
    }
}

#[derive(Debug, Clone)]
pub(crate) struct ActivationHostContext {
    activation_id: ActivationId,
    root_activation_id: ActivationId,
    parent_activation_id: Option<ActivationId>,
    principal: FabricPrincipal,
    trace_id: String,
    span_id: String,
    trace_flags: u8,
    baggage: Metadata,
    deadline_unix_millis: Option<u64>,
    budget: FabricBudget,
    metadata: Metadata,
}

impl ActivationHostContext {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn new(
        activation_id: ActivationId,
        root_activation_id: ActivationId,
        parent_activation_id: Option<ActivationId>,
        principal: FabricPrincipal,
        trace_id: String,
        span_id: String,
        trace_flags: u8,
        baggage: Metadata,
        deadline_unix_millis: Option<u64>,
        budget: FabricBudget,
        metadata: Metadata,
    ) -> Self {
        Self {
            activation_id,
            root_activation_id,
            parent_activation_id,
            principal,
            trace_id,
            span_id,
            trace_flags,
            baggage,
            deadline_unix_millis,
            budget,
            metadata,
        }
    }
}

#[derive(Debug)]
pub(crate) struct HostState {
    context: ActivationHostContext,
    pub(crate) limiter: TrackingLimiter,
    pub(crate) logs: InvocationLogBuffer,
    host_call_timing: HostCallTiming,
}

/// In-guest host-import time. This is intentionally reported separately from
/// setup and cleanup; it is a subset of the guest-call interval, not an
/// additional latency component.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub(crate) struct HostCallTiming {
    pub(crate) calls: u64,
    pub(crate) elapsed_micros: u64,
}

impl HostState {
    #[cfg(test)]
    pub(crate) fn new(
        context: ActivationHostContext,
        maximum_memory_bytes: usize,
        maximum_log_entries: usize,
        maximum_log_bytes: usize,
    ) -> Self {
        let config = WasmtimeConfig {
            invocation_log_maximum_entries: maximum_log_entries,
            invocation_log_maximum_bytes: maximum_log_bytes,
            ..WasmtimeConfig::default()
        };
        Self::with_config(context, maximum_memory_bytes, &config)
    }

    pub(crate) fn with_config(
        context: ActivationHostContext,
        maximum_memory_bytes: usize,
        config: &WasmtimeConfig,
    ) -> Self {
        let logs = InvocationLogBuffer::new(
            context.activation_id.clone(),
            config.invocation_log_maximum_entries,
            config.invocation_log_maximum_bytes,
            context.budget.log_bytes,
        );
        Self {
            context,
            limiter: TrackingLimiter::with_config(maximum_memory_bytes, config),
            logs,
            host_call_timing: HostCallTiming::default(),
        }
    }

    pub(crate) fn host_call_timing(&self) -> HostCallTiming {
        self.host_call_timing
    }

    fn record_host_call(&mut self, started: Instant) {
        self.host_call_timing.calls = self.host_call_timing.calls.saturating_add(1);
        self.host_call_timing.elapsed_micros = self
            .host_call_timing
            .elapsed_micros
            .saturating_add(u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX));
    }
}

impl context::Host for HostState {
    async fn activation_id(&mut self) -> String {
        let started = Instant::now();
        let value = self.context.activation_id.0.clone();
        self.record_host_call(started);
        value
    }

    async fn root_activation_id(&mut self) -> String {
        let started = Instant::now();
        let value = self.context.root_activation_id.0.clone();
        self.record_host_call(started);
        value
    }

    async fn parent_activation_id(&mut self) -> Option<String> {
        let started = Instant::now();
        let value = self
            .context
            .parent_activation_id
            .as_ref()
            .map(|activation_id| activation_id.0.clone());
        self.record_host_call(started);
        value
    }

    async fn principal(&mut self) -> context::InvocationPrincipal {
        let started = Instant::now();
        let value = context::InvocationPrincipal {
            subject: self.context.principal.subject.clone(),
            kind: principal_kind(self.context.principal.kind).to_owned(),
            tenant: self
                .context
                .principal
                .tenant
                .as_ref()
                .map(|tenant| tenant.0.clone()),
            service: self
                .context
                .principal
                .service
                .as_ref()
                .map(|service| service.0.clone()),
            claims: metadata_pairs(&self.context.principal.claims),
        };
        self.record_host_call(started);
        value
    }

    async fn trace(&mut self) -> context::TraceContext {
        let started = Instant::now();
        let value = context::TraceContext {
            trace_id: self.context.trace_id.clone(),
            span_id: self.context.span_id.clone(),
            trace_flags: self.context.trace_flags,
            baggage: metadata_pairs(&self.context.baggage),
        };
        self.record_host_call(started);
        value
    }

    async fn deadline_unix_millis(&mut self) -> Option<u64> {
        let started = Instant::now();
        let value = self.context.deadline_unix_millis;
        self.record_host_call(started);
        value
    }

    async fn remaining_budget(&mut self) -> context::ResourceBudget {
        let started = Instant::now();
        let budget = &self.context.budget;
        let value = context::ResourceBudget {
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
        self.record_host_call(started);
        value
    }

    async fn metadata(&mut self) -> Vec<(String, String)> {
        let started = Instant::now();
        let value = metadata_pairs(&self.context.metadata);
        self.record_host_call(started);
        value
    }
}

impl log::Host for HostState {
    async fn write(
        &mut self,
        level: log::Level,
        message: String,
        fields: Vec<log::Field>,
    ) -> Result<bool, log::LogError> {
        let started = Instant::now();
        let result = self.logs.write(level, message, fields);
        self.record_host_call(started);
        result
    }
}

fn metadata_pairs(metadata: &Metadata) -> Vec<(String, String)> {
    metadata
        .iter()
        .map(|(name, value)| (name.clone(), value.clone()))
        .collect()
}

fn principal_kind(kind: PrincipalKind) -> &'static str {
    match kind {
        PrincipalKind::User => "user",
        PrincipalKind::Service => "service",
        PrincipalKind::Node => "node",
        PrincipalKind::Trigger => "trigger",
        PrincipalKind::Administrator => "administrator",
        PrincipalKind::Anonymous => "anonymous",
        _ => "unknown",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const WASM_PAGE_BYTES: usize = 64 * 1024;

    #[test]
    fn aggregate_memory_budget_counts_all_linear_memories() {
        let mut limiter = TrackingLimiter::new(2 * WASM_PAGE_BYTES);

        assert!(limiter
            .memory_growing(0, WASM_PAGE_BYTES, None)
            .expect("first memory must fit"));
        assert!(limiter
            .memory_growing(0, WASM_PAGE_BYTES, None)
            .expect("second memory must fit exactly"));
        assert_eq!(limiter.current_memory_bytes(), 2 * WASM_PAGE_BYTES);
        assert_eq!(
            limiter.peak_memory_bytes(),
            u64::try_from(2 * WASM_PAGE_BYTES).expect("test value fits u64")
        );

        let error = limiter
            .memory_growing(WASM_PAGE_BYTES, 2 * WASM_PAGE_BYTES, None)
            .expect_err("aggregate growth beyond the activation budget must trap");
        assert!(error
            .to_string()
            .contains("aggregate linear-memory budget exceeded"));
        assert_eq!(limiter.current_memory_bytes(), 2 * WASM_PAGE_BYTES);
        assert_eq!(
            limiter.peak_memory_bytes(),
            u64::try_from(2 * WASM_PAGE_BYTES).expect("test value fits u64")
        );
    }

    #[test]
    fn configured_store_counts_and_table_growth_override_legacy_defaults() {
        let config = WasmtimeConfig {
            maximum_instances_per_store: 3,
            maximum_memories_per_store: 2,
            maximum_tables_per_store: 1,
            maximum_table_elements: 7,
            ..WasmtimeConfig::default()
        };
        let mut limiter = TrackingLimiter::with_config(WASM_PAGE_BYTES, &config);
        assert_eq!(limiter.instances(), 3);
        assert_eq!(limiter.memories(), 2);
        assert_eq!(limiter.tables(), 1);
        assert!(limiter
            .table_growing(0, 7, None)
            .expect("exact table limit"));
        assert!(limiter.table_growing(7, 8, None).is_err());
        assert!(limiter
            .memory_growing(0, WASM_PAGE_BYTES, None)
            .expect("exact memory limit"));
        assert!(limiter
            .memory_growing(WASM_PAGE_BYTES, 2 * WASM_PAGE_BYTES, None)
            .is_err());
    }
}

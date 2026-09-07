use std::sync::Arc;
use std::time::Instant;

use latent_core::{
    ActivationClock, ActivationId, InvocationPrincipal as FabricPrincipal, Metadata,
};
use wasmtime::{ResourceLimiter, StoreLimits, StoreLimitsBuilder};

pub(crate) mod accounting;
mod clock;
mod context;
mod logging;
pub(crate) mod policy;
pub(crate) use logging::InvocationLogBuffer;
pub use logging::{BoundedLogSink, CapturedLog, LogSinkError, StructuredLogSink};

use crate::config::WasmtimeConfig;
use accounting::InvocationAccounting;
use policy::ContextExposurePolicy;

mod request_context;
pub(crate) use request_context::validate_request_context;

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
            metadata,
        }
    }
}

pub(crate) struct HostState {
    context: ActivationHostContext,
    pub(crate) limiter: TrackingLimiter,
    pub(crate) logs: InvocationLogBuffer,
    pub(crate) accounting: InvocationAccounting,
    context_policy: Arc<ContextExposurePolicy>,
    clock: Arc<dyn ActivationClock>,
    clock_origin: Instant,
    last_monotonic_nanos: u64,
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
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn with_config(
        context: ActivationHostContext,
        maximum_memory_bytes: usize,
        config: &WasmtimeConfig,
        accounting: InvocationAccounting,
        context_policy: Arc<ContextExposurePolicy>,
        clock: Arc<dyn ActivationClock>,
        clock_origin: Instant,
        sink: BoundedLogSink,
    ) -> Self {
        let logs = InvocationLogBuffer::new(
            config.invocation_log_maximum_entries,
            config.invocation_log_maximum_bytes,
            accounting.budget().clone(),
            sink,
        );
        Self {
            context,
            limiter: TrackingLimiter::with_config(maximum_memory_bytes, config),
            logs,
            accounting,
            context_policy,
            clock,
            clock_origin,
            last_monotonic_nanos: 0,
            host_call_timing: HostCallTiming::default(),
        }
    }

    fn remaining_budget_snapshot(
        &mut self,
        fuel: u64,
    ) -> wasmtime::Result<crate::bindings::latent::context::context::ResourceBudget> {
        self.accounting
            .observe_runtime(fuel, self.limiter.peak_memory_bytes())
            .map_err(|error| wasmtime::Error::msg(error.message))?;
        let remaining = self
            .accounting
            .remaining_at(
                self.clock.monotonic_now(),
                self.limiter.maximum_memory_bytes as u64,
            )
            .map_err(|error| wasmtime::Error::msg(error.message))?;
        Ok(crate::bindings::latent::context::context::ResourceBudget {
            cpu_fuel: remaining.cpu_fuel,
            memory_bytes: remaining.memory_bytes,
            wall_time_limit_millis: remaining.wall_time_limit_millis,
            child_calls: remaining.child_calls,
            outbound_requests: remaining.outbound_requests,
            state_read_bytes: remaining.state_read_bytes,
            state_write_bytes: remaining.state_write_bytes,
            blob_read_bytes: remaining.blob_read_bytes,
            blob_write_bytes: remaining.blob_write_bytes,
            log_bytes: remaining.log_bytes,
            effect_count: remaining.effect_count,
        })
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

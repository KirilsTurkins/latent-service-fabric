use super::{busy, PlatformError};
use crate::broker::{ActivationCapabilityBroker, Kind};
use latent_core::TenantId;
use std::sync::atomic::Ordering;

/// Instantaneous ownership counters, not a transactionally consistent snapshot
/// or process RSS. Retained results survive the activation's session core.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct TenantUsage {
    pub sessions: usize,
    pub retired_sessions_with_resources: usize,
    pub handles: usize,
    pub calls: usize,
    pub waiting: usize,
    pub results: usize,
    pub reserved_buffer_bytes: usize,
    pub live_children: usize,
    pub delegated_memory_bytes: u64,
    pub ledgers_without_delegation: usize,
}
#[derive(Debug)]
pub struct NodeUsage {
    pub broker: crate::broker::CapabilityBrokerSnapshot,
    pub pools: Option<crate::broker::pools::ProviderPoolSnapshot>,
    pub io: Option<crate::broker::io::IoSnapshot>,
    pub audit_capture_dropped: u64,
    pub audit: Option<latent_audit::AuditSnapshot>,
}
impl ActivationCapabilityBroker {
    pub fn inspect_tenant_usage(&self, tenant: &TenantId) -> Result<TenantUsage, PlatformError> {
        let _metadata = self.inner.counters.acquire(
            Kind::Metadata,
            self.inner.limits.maximum_sessions
                * std::mem::size_of::<crate::broker::session::RegistryEntry>(),
        )?;
        let entries = self.inner.sessions.try_lock().map_err(|_| busy())?.clone();
        let mut total = TenantUsage::default();
        for entry in entries {
            let Some(stats) = entry.stats.upgrade() else {
                continue;
            };
            if stats.tenant != *tenant {
                continue;
            }
            let handles = stats.handles.load(Ordering::Acquire);
            let calls = stats.calls.load(Ordering::Acquire);
            let results = stats.results.load(Ordering::Acquire);
            let bytes = stats.buffer_bytes.load(Ordering::Acquire);
            total.handles += handles;
            total.calls += calls;
            total.results += results;
            total.waiting += stats.waiting.load(Ordering::Acquire);
            total.reserved_buffer_bytes += bytes;
            if stats.closed.load(Ordering::Acquire) && handles + calls + results + bytes != 0 {
                total.retired_sessions_with_resources += 1;
            }
            if let Some(core) = entry.core.upgrade() {
                total.sessions += 1;
                if let Ok(snapshot) = core.budget.descendant_snapshot() {
                    total.live_children += snapshot.live_children;
                    total.delegated_memory_bytes = total
                        .delegated_memory_bytes
                        .saturating_add(snapshot.reserved_memory_bytes);
                } else {
                    total.ledgers_without_delegation += 1;
                }
            }
        }
        Ok(total)
    }
    /// Expose only to a trusted node operator; shared owners span tenants.
    pub fn inspect_node_usage(&self) -> Result<NodeUsage, PlatformError> {
        let owner = self
            .inner
            .pool_diagnostics
            .get()
            .cloned()
            .unwrap_or_default();
        let (pools, io) = crate::broker::pools::diagnostic_snapshot(&owner)?
            .map_or((None, None), |(pools, io)| (Some(pools), Some(io)));
        Ok(NodeUsage {
            broker: self.snapshot(),
            pools,
            io,
            audit_capture_dropped: self
                .inner
                .audit
                .as_ref()
                .map_or(0, |a| a.dropped.load(Ordering::Acquire)),
            audit: self
                .inner
                .audit
                .as_ref()
                .map(|audit| audit.handle.snapshot()),
        })
    }
}

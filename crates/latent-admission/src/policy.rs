use std::collections::{BTreeMap, BTreeSet};

use latent_core::{PlatformError, PlatformErrorCode, PrincipalKind, ResourceBudget, TenantId};
use latent_routing::revision_policy::ThreadingModel;

use crate::{rejection, valid_identifier};

/// Every numeric quota is an exact finite ceiling; zero denies that capacity.
/// CPU and memory are reserved for queued work as well as executing work.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct QuotaLimits {
    pub maximum_concurrent_activations: u32,
    pub maximum_queued_activations: u32,
    pub maximum_reserved_cpu_fuel: u64,
    pub maximum_reserved_memory_bytes: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TenantAdmissionPolicy {
    pub limits: QuotaLimits,
    pub maximum_payload_bytes: u64,
    pub maximum_priority: u8,
    /// Exact authenticated subjects. An empty set grants nobody access.
    pub allowed_subjects: BTreeSet<String>,
    pub allowed_principal_kinds: Vec<PrincipalKind>,
    pub allowed_trust_classes: BTreeSet<String>,
    pub allowed_cell_classes: BTreeSet<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TrustClassPolicy {
    pub limits: QuotaLimits,
    pub allowed_cell_classes: BTreeSet<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct QueueClassPolicy {
    pub minimum_priority: u8,
    pub maximum_priority: u8,
    pub maximum_queued_activations: u32,
}

/// Fixed node-defined class capabilities, not a per-service pool.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CellClassPolicy {
    pub maximum_memory_bytes: u64,
    /// Effective usable class capacity, matching the downstream pool configuration.
    pub parallelism: u32,
    pub threading_models: Vec<ThreadingModel>,
    pub features: BTreeSet<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct OverloadPolicy {
    /// Admission rejects at or above either pressure threshold (0..=1000).
    pub maximum_cpu_pressure_milli: u16,
    pub maximum_memory_pressure_milli: u16,
    pub maximum_sample_age_millis: u64,
}

/// A conservative estimate of the current bounded backlog, not a latency SLA.
/// The scheduler must recheck the original monotonic deadline at cell handoff.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DeadlinePolicy {
    pub estimated_service_time_millis: u64,
    pub minimum_execution_time_millis: u64,
    pub safety_margin_millis: u64,
}

/// Immutable startup policy shared by every controller using a quota ledger.
/// Unknown tenants, subjects, trust classes, priorities, and cells fail closed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NodeAdmissionPolicy {
    pub budget_ceiling: ResourceBudget,
    pub limits: QuotaLimits,
    pub tenants: BTreeMap<TenantId, TenantAdmissionPolicy>,
    pub trust_classes: BTreeMap<String, TrustClassPolicy>,
    pub queue_classes: BTreeMap<String, QueueClassPolicy>,
    pub cell_classes: BTreeMap<String, CellClassPolicy>,
    pub maximum_payload_bytes: u64,
    pub maximum_priority: u8,
    /// Bound for caller-chosen names. Generated revision/release identities use
    /// at least 83 bytes for revision-v1:sha256 identities and are then verified
    /// against the exact trusted catalog tuple.
    pub maximum_identifier_bytes: usize,
    /// Aggregate bound across principal claims and both request/revision metadata maps.
    pub maximum_metadata_entries: usize,
    pub maximum_metadata_bytes: usize,
    pub overload: OverloadPolicy,
    pub deadline: DeadlinePolicy,
    pub architecture: String,
    pub region: Option<String>,
    pub zone: Option<String>,
}

impl NodeAdmissionPolicy {
    pub fn validate(&self) -> Result<(), PlatformError> {
        if self.maximum_identifier_bytes == 0
            || !valid_identifier(&self.architecture, self.maximum_identifier_bytes)
            || self
                .region
                .as_ref()
                .is_some_and(|value| !self.valid_name(value))
            || self
                .zone
                .as_ref()
                .is_some_and(|value| !self.valid_name(value))
        {
            return Err(configuration("invalid-node-identity"));
        }
        if self.budget_ceiling.validate_phase1_request().is_err()
            || !matches!(self.budget_ceiling.wall_time_limit_millis, Some(1..))
        {
            return Err(configuration("invalid-node-budget"));
        }
        if self.overload.maximum_cpu_pressure_milli > 1000
            || self.overload.maximum_memory_pressure_milli > 1000
            || self.overload.maximum_sample_age_millis == 0
        {
            return Err(configuration("invalid-overload-threshold"));
        }
        if self.deadline.estimated_service_time_millis == 0
            || self.deadline.minimum_execution_time_millis == 0
            || self
                .deadline
                .minimum_execution_time_millis
                .checked_add(self.deadline.safety_margin_millis)
                .is_none()
        {
            return Err(configuration("invalid-deadline-policy"));
        }
        if self.cell_classes.is_empty() || self.cell_classes.len() > 5 {
            return Err(configuration("invalid-cell-classes"));
        }
        let mut previous_memory = 0;
        for name in ["tiny", "small", "standard", "large", "extra-large"] {
            if let Some(class) = self.cell_classes.get(name) {
                if class.maximum_memory_bytes == 0
                    || class.maximum_memory_bytes < previous_memory
                    || class.parallelism == 0
                    || class.threading_models.is_empty()
                    || class
                        .features
                        .iter()
                        .any(|feature| !self.valid_name(feature))
                {
                    return Err(configuration("invalid-cell-class"));
                }
                previous_memory = class.maximum_memory_bytes;
            }
        }
        if self
            .cell_classes
            .keys()
            .any(|name| cell_rank(name).is_none())
        {
            return Err(configuration("unknown-cell-class"));
        }
        let mut priorities = [false; 256];
        for (name, queue) in &self.queue_classes {
            if !self.valid_name(name)
                || queue.minimum_priority > queue.maximum_priority
                || queue.maximum_priority > self.maximum_priority
            {
                return Err(configuration("invalid-queue-class"));
            }
            for priority in queue.minimum_priority..=queue.maximum_priority {
                if std::mem::replace(&mut priorities[usize::from(priority)], true) {
                    return Err(configuration("overlapping-priority-ranges"));
                }
            }
        }
        if priorities[..=usize::from(self.maximum_priority)].contains(&false) {
            return Err(configuration("unmapped-priority"));
        }
        for (name, trust) in &self.trust_classes {
            if !self.valid_name(name) || !self.valid_cells(&trust.allowed_cell_classes) {
                return Err(configuration("invalid-trust-class"));
            }
        }
        for (tenant, policy) in &self.tenants {
            if !self.valid_name(&tenant.0)
                || policy
                    .allowed_subjects
                    .iter()
                    .any(|subject| !self.valid_name(subject))
                || policy.maximum_priority > self.maximum_priority
                || !self.valid_cells(&policy.allowed_cell_classes)
                || policy
                    .allowed_trust_classes
                    .iter()
                    .any(|name| !self.trust_classes.contains_key(name))
            {
                return Err(configuration("invalid-tenant-policy"));
            }
        }
        Ok(())
    }

    fn valid_cells(&self, names: &BTreeSet<String>) -> bool {
        names
            .iter()
            .all(|name| self.cell_classes.contains_key(name))
    }

    fn valid_name(&self, name: &str) -> bool {
        valid_identifier(name, self.maximum_identifier_bytes)
    }
}

pub(crate) fn cell_rank(name: &str) -> Option<u8> {
    match name {
        "tiny" => Some(0),
        "small" => Some(1),
        "standard" => Some(2),
        "large" => Some(3),
        "extra-large" => Some(4),
        _ => None,
    }
}

fn configuration(reason: &'static str) -> PlatformError {
    rejection(
        PlatformErrorCode::InvalidArgument,
        "node",
        "configuration",
        reason,
    )
}

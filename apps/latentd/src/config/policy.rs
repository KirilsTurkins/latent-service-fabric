use std::collections::{BTreeMap, BTreeSet};

use latent_admission::{
    CellClassPolicy, DeadlinePolicy, NodeAdmissionPolicy, OverloadPolicy, QueueClassPolicy,
    QuotaLimits, TenantAdmissionPolicy, TrustClassPolicy,
};
use latent_core::{InvocationPrincipal, PlatformError, PrincipalKind, ResourceBudget, TenantId};
use latent_routing::revision_policy::ThreadingModel;

use super::validation::Capacity;
use super::{
    invalid, CredentialConfig, CredentialRole, NodeConfig, CONTEXT_BYTES, IDENTIFIER_BYTES,
    TRUST_CLASS,
};

pub(super) fn admission(
    config: &NodeConfig,
    capacity: &Capacity,
) -> Result<NodeAdmissionPolicy, PlatformError> {
    let limits = quota(config, capacity)?;
    let classes: BTreeSet<_> = config.cells.iter().map(|cell| cell.class.clone()).collect();
    let mut tenants: BTreeMap<TenantId, TenantAdmissionPolicy> = BTreeMap::new();
    for credential in &config.credentials {
        let policy = tenants
            .entry(TenantId(credential.tenant.clone()))
            .or_insert_with(|| TenantAdmissionPolicy {
                limits,
                maximum_payload_bytes: config.limits.maximum_payload_bytes as u64,
                maximum_priority: u8::MAX,
                allowed_subjects: BTreeSet::new(),
                allowed_principal_kinds: Vec::new(),
                allowed_trust_classes: BTreeSet::from([TRUST_CLASS.to_owned()]),
                allowed_cell_classes: classes.clone(),
            });
        policy.allowed_subjects.insert(credential.subject.clone());
        let kind = principal_kind(credential.role);
        if !policy.allowed_principal_kinds.contains(&kind) {
            policy.allowed_principal_kinds.push(kind);
        }
    }
    let policy = NodeAdmissionPolicy {
        budget_ceiling: budget(config, capacity.maximum_memory),
        limits,
        tenants,
        trust_classes: BTreeMap::from([(
            TRUST_CLASS.to_owned(),
            TrustClassPolicy {
                limits,
                allowed_cell_classes: classes,
            },
        )]),
        queue_classes: BTreeMap::from([(
            "default".to_owned(),
            QueueClassPolicy {
                minimum_priority: 0,
                maximum_priority: u8::MAX,
                maximum_queued_activations: capacity.reservations,
            },
        )]),
        cell_classes: config
            .cells
            .iter()
            .map(|cell| {
                (
                    cell.class.clone(),
                    CellClassPolicy {
                        maximum_memory_bytes: cell.maximum_memory_bytes,
                        parallelism: cell.capacity,
                        threading_models: vec![
                            ThreadingModel::SingleThreaded,
                            ThreadingModel::Reentrant,
                        ],
                        features: BTreeSet::new(),
                    },
                )
            })
            .collect(),
        maximum_payload_bytes: config.limits.maximum_payload_bytes as u64,
        maximum_priority: u8::MAX,
        maximum_identifier_bytes: IDENTIFIER_BYTES,
        // Request metadata, the trusted operator claim, and the two packed
        // catalog revision attributes share this aggregate admission bound.
        maximum_metadata_entries: 67,
        maximum_metadata_bytes: CONTEXT_BYTES,
        overload: OverloadPolicy {
            maximum_cpu_pressure_milli: 950,
            maximum_memory_pressure_milli: 950,
            maximum_sample_age_millis: 2000,
        },
        deadline: DeadlinePolicy {
            estimated_service_time_millis: 1,
            minimum_execution_time_millis: 1,
            safety_margin_millis: 0,
        },
        architecture: std::env::consts::ARCH.to_owned(),
        region: None,
        zone: None,
    };
    policy.validate().map_err(|_| invalid("admission"))?;
    Ok(policy)
}

fn quota(config: &NodeConfig, capacity: &Capacity) -> Result<QuotaLimits, PlatformError> {
    let count = u64::from(capacity.reservations);
    Ok(QuotaLimits {
        // Admission's active count includes both queued and executing work.
        // Every request briefly reserves queued capacity, even on idle cells.
        maximum_concurrent_activations: capacity.reservations,
        maximum_queued_activations: capacity.reservations,
        maximum_reserved_cpu_fuel: count
            .checked_mul(config.execution.maximum_cpu_fuel)
            .ok_or_else(|| invalid("execution.maximumCpuFuel"))?,
        maximum_reserved_memory_bytes: count
            .checked_mul(capacity.maximum_memory)
            .ok_or_else(|| invalid("cells.maximumMemoryBytes"))?,
    })
}

fn budget(config: &NodeConfig, memory: u64) -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: config.execution.maximum_cpu_fuel,
        memory_bytes: memory,
        wall_time_limit_millis: Some(config.execution.maximum_wall_time_millis),
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: config.execution.maximum_log_bytes,
        effect_count: 0,
    }
}

pub(super) fn principal(credential: &CredentialConfig) -> InvocationPrincipal {
    InvocationPrincipal {
        subject: credential.subject.clone(),
        kind: principal_kind(credential.role),
        tenant: Some(TenantId(credential.tenant.clone())),
        service: None,
        claims: if credential.role == CredentialRole::Operator {
            BTreeMap::from([("latent.node.operator".to_owned(), "true".to_owned())])
        } else {
            BTreeMap::new()
        },
    }
}

const fn principal_kind(role: CredentialRole) -> PrincipalKind {
    match role {
        CredentialRole::Invoke => PrincipalKind::User,
        CredentialRole::Admin | CredentialRole::Operator => PrincipalKind::Administrator,
    }
}

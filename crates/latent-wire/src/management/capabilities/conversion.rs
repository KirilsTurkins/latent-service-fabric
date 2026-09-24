use super::super::proto;
use latent_capabilities::broker::diagnostics as domain;
use std::collections::HashMap;

pub(super) fn revision(value: &domain::InspectionPlan) -> proto::CapabilityInspectionRevision {
    proto::CapabilityInspectionRevision {
        deployment_id: value.deployment.0.clone(),
        revision_id: value.revision.0.clone(),
        component_digest: value.component.0.clone(),
        publication_id: value.publication.as_ref().map(ToString::to_string),
        route_generation: value.generation.0,
        catalog_transaction: value.catalog_transaction,
    }
}
fn policy(value: domain::Revision) -> proto::CapabilityInspectionPolicy {
    proto::CapabilityInspectionPolicy {
        id: value.id,
        revision: value.revision,
        digest: value.digest,
    }
}
fn binding(value: domain::BindingInspection) -> proto::CapabilityBindingInspection {
    proto::CapabilityBindingInspection {
        definition_digest: value.definition_digest,
        provider_binding: Some(policy(value.binding)),
        policies: value.policies.into_iter().map(policy).collect(),
        provider_profile: value.provider_profile,
        provider_configuration_digest: value.configuration_digest,
        provider_configuration_epoch: value.configuration_epoch,
        state: value.state.code().into(),
    }
}
pub(super) fn descriptor(value: domain::BindingInspection) -> proto::CapabilityDescriptor {
    proto::CapabilityDescriptor {
        id: value.capability.clone(),
        contract: value.capability.clone(),
        provider: value.provider_profile.clone(),
        operations: value.operations.clone(),
        attributes: HashMap::new(),
        inspection: Some(binding(value)),
    }
}
pub(super) fn explanation(
    selected: &domain::InspectionPlan,
    value: Option<domain::GrantExplanation>,
) -> proto::ExplainCapabilityGrantResponse {
    let mut result = proto::ExplainCapabilityGrantResponse {
        revision: Some(revision(selected)),
        reasons: vec!["binding-plan-unavailable".into()],
        obligations: HashMap::from([
            ("live-admission-required".into(), "true".into()),
            ("activation-budget-reserved".into(), "false".into()),
            ("descriptive-only".into(), "true".into()),
        ]),
        ..Default::default()
    };
    if let Some(value) = value {
        result.allowed = value.allowed;
        result.reasons = vec![value.reason.into()];
        result.inspection = value.binding.map(binding);
        result.requires_audit = value.requires_audit;
        result.ceiling = value.ceiling.map(|c| proto::CapabilityInspectionCeiling {
            operations: c.operations,
            input_bytes: c.input_bytes,
            output_bytes: c.output_bytes,
            wall_time_millis: c.wall_time_millis,
        });
        // Legacy singular digest remains empty; the complete policy set is typed.
    }
    result
}
pub(super) fn tenant_usage(value: domain::TenantUsage) -> proto::CapabilityResourceUsage {
    proto::CapabilityResourceUsage {
        scope: "tenant".into(),
        unavailable: Vec::new(),
        counters: HashMap::from([
            ("sessions".into(), value.sessions as u64),
            (
                "retired_sessions_with_resources".into(),
                value.retired_sessions_with_resources as u64,
            ),
            ("handles".into(), value.handles as u64),
            ("calls".into(), value.calls as u64),
            ("waiting".into(), value.waiting as u64),
            ("results".into(), value.results as u64),
            (
                "reserved_buffer_bytes".into(),
                value.reserved_buffer_bytes as u64,
            ),
            ("live_children".into(), value.live_children as u64),
            (
                "delegated_memory_bytes".into(),
                value.delegated_memory_bytes,
            ),
            (
                "ledgers_without_delegation".into(),
                value.ledgers_without_delegation as u64,
            ),
        ]),
    }
}
pub(super) fn node_usage(value: &domain::NodeUsage) -> proto::CapabilityResourceUsage {
    let mut result = proto::CapabilityResourceUsage {
        scope: "node".into(),
        ..Default::default()
    };
    macro_rules! counts { ($prefix:literal, $value:expr, $($field:ident),+ $(,)?) => { $(
        result.counters.insert(concat!($prefix, stringify!($field)).into(), $value.$field as u64);
    )+ }; }
    counts!(
        "broker_",
        value.broker,
        providers,
        plans,
        sessions,
        handles,
        calls,
        results,
        metadata_bytes,
        buffer_bytes
    );
    if let Some(pools) = value.pools {
        result
            .counters
            .insert("pool_closed".into(), u64::from(pools.closed));
        result.counters.insert(
            "pool_control_failed".into(),
            u64::from(pools.control_failed),
        );
        counts!(
            "pool_",
            pools,
            configurations,
            retained_configurations,
            clients,
            connections,
            active_connections,
            connecting_connections,
            retired_connections,
            idle_connections,
            pending_requests,
            running_requests,
            workers,
            cleanup_jobs,
            failed_cleanup,
            metadata_bytes,
            control_owners
        );
    } else {
        result
            .unavailable
            .push("provider-pools-no-retained-owner".into());
    }
    if let Some(io) = value.io {
        counts!(
            "io_",
            io,
            calls,
            occupied_running_slots,
            queued_calls,
            staged_bytes,
            result_bytes,
            buffers,
            streams,
            metadata_bytes
        );
    } else {
        result
            .unavailable
            .push("provider-io-no-retained-pool-owner".into());
    }
    result
        .counters
        .insert("audit_capture_dropped".into(), value.audit_capture_dropped);
    if let Some(audit) = value.audit {
        result
            .counters
            .insert("audit_closed".into(), u64::from(audit.closed));
        result.counters.insert(
            "audit_recovery_pending".into(),
            u64::from(audit.recovery_pending),
        );
        counts!(
            "audit_",
            audit,
            dropped_observations,
            unavailable_events,
            pending_attempts,
            queued_operations,
            queued_bytes,
            reserved_records,
            reserved_bytes,
            query_owners,
            query_bytes,
            stage_bytes
        );
    } else {
        result.unavailable.push("audit-owner-not-configured".into());
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn audit_byte_ownership_and_recovery_remain_visible_after_record_refund() {
        let mut usage = domain::NodeUsage {
            broker: Default::default(),
            pools: None,
            io: None,
            audit_capture_dropped: 0,
            audit: Some(latent_audit::AuditSnapshot {
                queued_bytes: 16 * 1024,
                stage_bytes: 68 * 1024,
                recovery_pending: true,
                ..Default::default()
            }),
        };
        let encoded = node_usage(&usage);
        assert_eq!(encoded.counters["audit_queued_operations"], 0);
        assert_eq!(encoded.counters["audit_reserved_records"], 0);
        assert_eq!(encoded.counters["audit_reserved_bytes"], 0);
        assert_eq!(encoded.counters["audit_queued_bytes"], 16 * 1024);
        assert_eq!(encoded.counters["audit_stage_bytes"], 68 * 1024);
        assert_eq!(encoded.counters["audit_recovery_pending"], 1);
        usage.audit = Some(latent_audit::AuditSnapshot::default());
        let idle = node_usage(&usage);
        for name in [
            "audit_queued_bytes",
            "audit_stage_bytes",
            "audit_recovery_pending",
        ] {
            assert_eq!(idle.counters[name], 0);
        }
        usage.audit = None;
        let unavailable = node_usage(&usage);
        assert!(unavailable
            .unavailable
            .contains(&"audit-owner-not-configured".into()));
        assert!(!unavailable.counters.contains_key("audit_queued_bytes"));
    }
}

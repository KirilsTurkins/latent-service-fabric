use latent_activation::{ActivationEnvelope, TraceContext};
use latent_core::{
    ActivationId, CellId, ContractId, FunctionId, InvocationPrincipal, Metadata, PrincipalKind,
    ReleaseDigest, ResourceBudget, ServiceId, SpanId, TenantId, TraceId,
};
use latent_executor::{ExecutionCell, ExecutionRequest, PreparationKey, PreparedComponent};
use latent_routing::InvocationTarget;

pub(super) fn request() -> ExecutionRequest {
    let budget = ResourceBudget {
        cpu_fuel: 100,
        memory_bytes: 1024,
        wall_time_limit_millis: Some(50),
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 100,
        effect_count: 0,
    };
    let tenant = TenantId("tenant".to_owned());
    ExecutionRequest {
        activation: ActivationEnvelope {
            activation_id: ActivationId("accounting-test".to_owned()),
            root_activation_id: ActivationId("accounting-test".to_owned()),
            parent_activation_id: None,
            principal: InvocationPrincipal {
                subject: "user".to_owned(),
                kind: PrincipalKind::User,
                tenant: Some(tenant.clone()),
                service: None,
                claims: Metadata::new(),
            },
            target: InvocationTarget {
                tenant,
                service: ServiceId("service".to_owned()),
                contract: ContractId("test:service/api@0.1.0".to_owned()),
                function: FunctionId("run".to_owned()),
                route: None,
            },
            resolved_revision: None,
            deadline_unix_millis: Some(1_050),
            priority: 0,
            trace: TraceContext {
                trace_id: TraceId("trace".to_owned()),
                span_id: SpanId("span".to_owned()),
                trace_flags: 1,
                baggage: Metadata::new(),
            },
            idempotency_key: None,
            retry_attempt: 0,
            budget: budget.clone(),
            metadata: Metadata::new(),
            input: b"[]".to_vec(),
            input_media_type: crate::values::MEDIA_TYPE.to_owned(),
        },
        prepared: PreparedComponent {
            key: PreparationKey {
                release: ReleaseDigest("release".to_owned()),
                engine_version: "test".to_owned(),
                engine_configuration_digest: "test".to_owned(),
                target_triple: "test".to_owned(),
                cpu_feature_set: "test".to_owned(),
            },
            backend: "test".to_owned(),
            opaque_handle: "test".to_owned(),
            metadata: Metadata::new(),
        },
        cell: ExecutionCell {
            id: CellId("cell".to_owned()),
            class: "standard".to_owned(),
            maximum_memory_bytes: budget.memory_bytes,
            metadata: Metadata::new(),
        },
        imports: Vec::new(),
        budget,
    }
}

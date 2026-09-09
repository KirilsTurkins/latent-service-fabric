use latent_activation::{ActivationEnvelope, TraceContext};
use latent_core::{
    ActivationId, CellId, ContractId, FunctionId, InvocationPrincipal, Metadata, PrincipalKind,
    ReleaseDigest, ResourceBudget, ServiceId, SpanId, TenantId, TraceId,
};
use latent_executor::{ExecutionCell, ExecutionRequest, PreparationKey, PreparedComponent};
use latent_routing::InvocationTarget;

pub(super) fn request() -> ExecutionRequest {
    let budget = ResourceBudget {
        cpu_fuel: 1000,
        memory_bytes: 64 * 1024,
        wall_time_limit_millis: None,
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 1000,
        effect_count: 0,
    };
    ExecutionRequest {
        activation: ActivationEnvelope {
            activation_id: ActivationId("activation".to_owned()),
            root_activation_id: ActivationId("root".to_owned()),
            parent_activation_id: Some(ActivationId("parent".to_owned())),
            principal: InvocationPrincipal {
                subject: "subject".to_owned(),
                kind: PrincipalKind::Service,
                tenant: Some(TenantId("tenant".to_owned())),
                service: Some(ServiceId("service".to_owned())),
                claims: [("claim".to_owned(), "allowed".to_owned())].into(),
            },
            target: InvocationTarget {
                tenant: TenantId("tenant".to_owned()),
                service: ServiceId("service".to_owned()),
                contract: ContractId("tests:generic/values@0.1.0".to_owned()),
                function: FunctionId("identify".to_owned()),
                route: None,
            },
            resolved_revision: None,
            deadline_unix_millis: Some(123),
            priority: 0,
            trace: TraceContext {
                trace_id: TraceId("trace".to_owned()),
                span_id: SpanId("span".to_owned()),
                trace_flags: 1,
                baggage: [("baggage".to_owned(), "value".to_owned())].into(),
            },
            idempotency_key: None,
            retry_attempt: 0,
            budget: budget.clone(),
            metadata: [("metadata".to_owned(), "value".to_owned())].into(),
            input: b"[]".to_vec(),
            input_media_type: "application/json".to_owned(),
        },
        prepared: PreparedComponent {
            key: PreparationKey {
                release: ReleaseDigest("release".to_owned()),
                engine_version: "version".to_owned(),
                engine_configuration_digest: "config".to_owned(),
                target_triple: "target".to_owned(),
                cpu_feature_set: "cpu".to_owned(),
            },
            backend: "backend".to_owned(),
            opaque_handle: "handle".to_owned(),
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

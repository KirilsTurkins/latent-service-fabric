use latent_core::{
    InvocationPrincipal, Metadata, PrincipalKind, ResourceBudget, ServiceId, SpanId, TenantId,
    TraceId,
};
use latent_routing::InvocationTarget;

use crate::{ActivationRequest, TraceContext};

pub(super) fn request() -> ActivationRequest {
    ActivationRequest {
        activation_id: None,
        root_activation_id: None,
        parent_activation_id: None,
        principal: InvocationPrincipal {
            subject: "caller".to_owned(),
            kind: PrincipalKind::User,
            tenant: Some(TenantId("tenant".to_owned())),
            service: None,
            claims: Metadata::new(),
        },
        target: InvocationTarget {
            tenant: TenantId("tenant".to_owned()),
            service: ServiceId("service".to_owned()),
            contract: latent_core::ContractId("example:values/api@0.1.0".to_owned()),
            function: latent_core::FunctionId("call".to_owned()),
            route: None,
        },
        deadline_unix_millis: None,
        priority: 0,
        trace: TraceContext {
            trace_id: TraceId("trace".to_owned()),
            span_id: SpanId("span".to_owned()),
            trace_flags: 1,
            baggage: Metadata::new(),
        },
        idempotency_key: None,
        retry_attempt: 0,
        budget: ResourceBudget {
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
        },
        metadata: Metadata::new(),
        input: Vec::new(),
        input_media_type: "application/json".to_owned(),
    }
}

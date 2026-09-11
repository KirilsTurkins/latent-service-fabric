use std::collections::HashMap;
use std::sync::atomic::{AtomicUsize, Ordering};

use latent_activation::TraceContext;
use latent_core::{
    InvocationPrincipal, Metadata, PlatformError, PrincipalKind, SpanId, TenantId, TraceId,
};
use tonic::{Code, Status};

use super::super::{proto, InvocationCommand, InvocationLimits, PrincipalPolicy};
use super::*;

struct CountingPolicy(AtomicUsize);
impl PrincipalPolicy for CountingPolicy {
    fn authenticate(&self, _: &InvocationPrincipal) -> Result<(), PlatformError> {
        Ok(())
    }
    fn authorize_target(&self, _: &InvocationPrincipal, _: &str) -> Result<(), PlatformError> {
        self.0.fetch_add(1, Ordering::Relaxed);
        Ok(())
    }
}

fn request() -> proto::InvokeRequest {
    proto::InvokeRequest {
        target: Some(proto::InvocationTarget {
            tenant: "tenant".into(),
            service: "service".into(),
            contract: "contract".into(),
            function: "function".into(),
            route: None,
        }),
        payload: b"payload".to_vec(),
        media_type: "text/plain".into(),
        budget: Some(proto::ResourceBudget {
            cpu_fuel: 100,
            memory_bytes: 4096,
            log_bytes: 10,
            wall_time_limit_millis: Some(500),
            ..Default::default()
        }),
        ..Default::default()
    }
}

fn validate(
    request: proto::InvokeRequest,
    limits: &InvocationLimits,
    policy: &dyn PrincipalPolicy,
) -> Result<InvocationCommand, Status> {
    validate_invoke(
        request,
        InvocationPrincipal {
            subject: "user".into(),
            kind: PrincipalKind::User,
            tenant: Some(TenantId("tenant".into())),
            service: None,
            claims: Metadata::new(),
        },
        TraceContext {
            trace_id: TraceId("trace".into()),
            span_id: SpanId("span".into()),
            trace_flags: 1,
            baggage: Metadata::new(),
        },
        Some(1234),
        limits,
        policy,
    )
}

#[test]
fn absent_identity_is_preserved_and_present_empty_or_unrooted_parent_is_rejected() {
    let policy = CountingPolicy(AtomicUsize::new(0));
    let limits = InvocationLimits::default();
    let valid = validate(request(), &limits, &policy).unwrap();
    assert!(valid.request.requested_activation_id.is_none());
    assert!(valid.request.root_activation_id.is_none());
    assert_eq!(valid.request.deadline_unix_millis, Some(1234));
    assert_eq!(valid.trace.trace_id.0, "trace");
    for field in 0..4 {
        let mut bad = request();
        match field {
            0 => bad.activation_id = Some(String::new()),
            1 => bad.parent_activation_id = Some("parent".into()),
            2 => bad.root_activation_id = Some(String::new()),
            _ => bad.idempotency_key = Some(String::new()),
        }
        assert_eq!(
            validate(bad, &limits, &policy).unwrap_err().code(),
            Code::InvalidArgument
        );
    }
    assert_eq!(policy.0.load(Ordering::Relaxed), 1);
    let mut explicit = request();
    explicit.activation_id = Some("呼出-1".into());
    explicit.parent_activation_id = Some("opaque-parent".into());
    explicit.root_activation_id = Some("opaque-root".into());
    let value = validate(explicit, &limits, &policy).unwrap();
    assert_eq!(value.request.requested_activation_id.unwrap().0, "呼出-1");
    assert_eq!(
        value.request.parent_activation_id.unwrap().0,
        "opaque-parent"
    );
    assert_eq!(value.request.root_activation_id.unwrap().0, "opaque-root");
}

#[test]
fn payload_string_and_sparse_map_allocations_are_rejected_before_policy_or_conversion() {
    let policy = CountingPolicy(AtomicUsize::new(0));
    let limits = InvocationLimits {
        max_payload_bytes: 64,
        max_message_bytes: 4096,
        ..InvocationLimits::default()
    };
    let mut payload = request();
    payload.payload = Vec::with_capacity(65);
    payload.payload.push(1);
    let mut context = request();
    context.media_type = String::with_capacity(5000);
    context.media_type.push_str("text/plain");
    let mut metadata = request();
    metadata.metadata = HashMap::with_capacity(128);
    for request in [payload, context, metadata] {
        assert_eq!(
            validate(request, &limits, &policy).unwrap_err().code(),
            Code::ResourceExhausted
        );
    }
    assert_eq!(policy.0.load(Ordering::Relaxed), 0);
}

#[test]
fn metadata_counts_and_retained_string_bytes_precede_entry_inspection() {
    let policy = CountingPolicy(AtomicUsize::new(0));
    let limits = InvocationLimits {
        max_metadata_entries: 1,
        max_metadata_bytes: 32,
        ..InvocationLimits::default()
    };
    let mut excess = request();
    excess.metadata = HashMap::from([("a".into(), "1".into()), ("\n".into(), "bad".into())]);
    assert_eq!(
        validate(excess, &limits, &policy).unwrap_err().code(),
        Code::ResourceExhausted
    );
    let mut spare = request();
    let mut value = String::with_capacity(512);
    value.push('x');
    spare.metadata.insert("key".into(), value);
    assert_eq!(
        validate(spare, &limits, &policy).unwrap_err().code(),
        Code::ResourceExhausted
    );
    let mut forged = request();
    forged
        .metadata
        .insert("LATENT.Principal.role".into(), "admin".into());
    assert_eq!(
        validate(forged, &limits, &policy).unwrap_err().code(),
        Code::InvalidArgument
    );
    assert_eq!(policy.0.load(Ordering::Relaxed), 0);
}

#[test]
fn unsupported_budgets_and_missing_targets_fail_before_authorization() {
    let policy = CountingPolicy(AtomicUsize::new(0));
    let limits = InvocationLimits::default();
    for field in 0..8 {
        let mut invalid = request();
        let budget = invalid.budget.as_mut().unwrap();
        match field {
            0 => budget.child_calls = 1,
            1 => budget.outbound_requests = 1,
            2 => budget.state_read_bytes = 1,
            3 => budget.state_write_bytes = 1,
            4 => budget.blob_read_bytes = 1,
            5 => budget.blob_write_bytes = 1,
            6 => budget.effect_count = 1,
            _ => invalid.target = None,
        }
        assert_eq!(
            validate(invalid, &limits, &policy).unwrap_err().code(),
            Code::InvalidArgument
        );
    }
    let mut ceiling = request();
    ceiling.budget.as_mut().unwrap().cpu_fuel = limits.max_cpu_fuel + 1;
    assert_eq!(
        validate(ceiling, &limits, &policy).unwrap_err().code(),
        Code::ResourceExhausted
    );
    assert_eq!(policy.0.load(Ordering::Relaxed), 0);
}

#[test]
fn cancel_and_status_queries_enforce_owned_capacity_and_unicode_controls() {
    let limits = InvocationLimits {
        max_message_bytes: 512,
        ..InvocationLimits::default()
    };
    let mut oversized = String::with_capacity(1024);
    oversized.push_str("id");
    assert_eq!(
        validate_status_query(
            proto::GetActivationRequest {
                activation_id: oversized.clone()
            },
            &limits
        )
        .unwrap()
        .0,
        "id"
    );
    assert_eq!(
        validate_status_query(
            proto::GetActivationRequest {
                activation_id: oversized
            },
            &limits
        )
        .unwrap_err()
        .code(),
        Code::ResourceExhausted
    );
    assert_eq!(
        validate_cancel(
            proto::CancelRequest {
                activation_id: "id".into(),
                reason: "bad\u{0085}reason".into()
            },
            &limits
        )
        .unwrap_err()
        .code(),
        Code::InvalidArgument
    );
    assert_eq!(
        validate_status_query(
            proto::GetActivationRequest {
                activation_id: "with space".into()
            },
            &limits
        )
        .unwrap_err()
        .code(),
        Code::InvalidArgument
    );
}

#[test]
fn generated_identity_references_survive_a_short_caller_identity_limit() {
    let policy = CountingPolicy(AtomicUsize::new(0));
    let limits = InvocationLimits {
        max_id_bytes: 16,
        ..InvocationLimits::default()
    };
    let generated = "a".repeat(44);
    let mut chosen = request();
    chosen.activation_id = Some(generated.clone());
    assert_eq!(
        validate(chosen, &limits, &policy).unwrap_err().code(),
        Code::ResourceExhausted
    );
    let mut lineage = request();
    lineage.activation_id = Some("chosen".into());
    lineage.root_activation_id = Some(generated.clone());
    lineage.parent_activation_id = Some(generated.clone());
    let valid = validate(lineage, &limits, &policy).unwrap();
    assert_eq!(valid.request.root_activation_id.unwrap().0, generated);
    assert_eq!(valid.request.parent_activation_id.unwrap().0, generated);
    assert_eq!(
        validate_status_query(
            proto::GetActivationRequest {
                activation_id: generated.clone()
            },
            &limits
        )
        .unwrap()
        .0,
        generated
    );
    assert_eq!(
        validate_cancel(
            proto::CancelRequest {
                activation_id: generated.clone(),
                reason: "stop".into()
            },
            &limits
        )
        .unwrap()
        .activation_id,
        generated
    );
    assert_eq!(policy.0.load(Ordering::Relaxed), 1);
}

#[test]
fn principal_trace_and_payload_metadata_share_one_aggregate_allocation_bound() {
    let policy = CountingPolicy(AtomicUsize::new(0));
    let limits = InvocationLimits {
        max_message_bytes: 12_000,
        ..InvocationLimits::default()
    };
    let principal = InvocationPrincipal {
        subject: "user".into(),
        kind: PrincipalKind::User,
        tenant: Some(TenantId("tenant".into())),
        service: None,
        claims: Metadata::from([("claim".into(), "value".into())]),
    };
    let trace = TraceContext {
        trace_id: TraceId("trace".into()),
        span_id: SpanId("span".into()),
        trace_flags: 0,
        baggage: Metadata::from([("correlation".into(), "value".into())]),
    };
    let mut value = request();
    value.metadata.insert("metadata".into(), "value".into());
    assert_eq!(
        validate_invoke(
            value.clone(),
            principal.clone(),
            trace.clone(),
            None,
            &limits,
            &policy
        )
        .unwrap_err()
        .code(),
        Code::ResourceExhausted
    );
    assert_eq!(policy.0.load(Ordering::Relaxed), 0);
    let trace = TraceContext {
        baggage: Metadata::new(),
        ..trace
    };
    validate_invoke(value, principal, trace, None, &limits, &policy).unwrap();
    assert_eq!(policy.0.load(Ordering::Relaxed), 1);
}

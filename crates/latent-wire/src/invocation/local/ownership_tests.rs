//! Real duplicate protobuf scalars can retain capacity through owned conversion.
use std::sync::Arc;

use latent_activation::{
    ActivationRequestBuilder, ActivationRequestLimits, SystemActivationIdSource, TraceContext,
};
use latent_core::{
    InvocationPrincipal, Metadata, PlatformErrorCode, PrincipalKind, SpanId, TenantId, TraceId,
};
use prost::Message;
use tonic::{Code, Status};

use super::super::{proto, validation, InvocationCommand, InvocationLimits, LocalPrincipalPolicy};

const ID: &str = "owned-explicit";

fn decoded() -> proto::InvokeRequest {
    let mut encoded = proto::InvokeRequest {
        activation_id: Some("x".repeat(4096)),
        ..Default::default()
    }
    .encode_to_vec();
    proto::InvokeRequest {
        activation_id: Some(ID.into()),
        root_activation_id: Some("root".into()),
        target: Some(proto::InvocationTarget {
            tenant: "tenant".into(),
            service: "service".into(),
            contract: "contract".into(),
            function: "function".into(),
            route: None,
        }),
        payload: b"[]".to_vec(),
        media_type: "application/json".into(),
        budget: Some(proto::ResourceBudget {
            cpu_fuel: 100,
            memory_bytes: 4096,
            wall_time_limit_millis: Some(500),
            ..Default::default()
        }),
        ..Default::default()
    }
    .encode(&mut encoded)
    .unwrap();
    let request = proto::InvokeRequest::decode(encoded.as_slice()).unwrap();
    let id = request.activation_id.as_ref().unwrap();
    assert_eq!(id, ID);
    assert!(
        id.capacity() >= 4096,
        "actual Prost merge retained its allocation"
    );
    request
}

fn validate(
    request: proto::InvokeRequest,
    limits: &InvocationLimits,
) -> Result<InvocationCommand, Status> {
    validation::validate_invoke(
        request,
        InvocationPrincipal {
            subject: "caller".into(),
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
        None,
        limits,
        &LocalPrincipalPolicy,
    )
}

fn builder(maximum_context_bytes: usize) -> ActivationRequestBuilder {
    ActivationRequestBuilder::new(
        ActivationRequestLimits {
            maximum_context_bytes,
            ..Default::default()
        },
        Arc::new(SystemActivationIdSource::default()),
    )
    .unwrap()
}

#[test]
fn duplicate_scalar_spare_capacity_reaches_the_activation_envelope_without_copying() {
    let request = decoded();
    let id = request.activation_id.as_ref().unwrap();
    let allocation = (id.as_ptr(), id.capacity());
    assert!(id.len() < InvocationLimits::default().max_id_bytes);
    assert!(id.capacity() > InvocationLimits::default().max_id_bytes);
    let command = validate(request, &InvocationLimits::default()).unwrap();
    let envelope = builder(1024 * 1024)
        .build(super::activation_request(command))
        .unwrap();
    assert_eq!(envelope.activation_id.0, ID);
    assert_eq!(
        (
            envelope.activation_id.0.as_ptr(),
            envelope.activation_id.0.capacity()
        ),
        allocation
    );
}

#[test]
fn duplicate_scalar_aggregate_capacity_is_enforced_despite_legal_final_text() {
    let limits = InvocationLimits {
        max_message_bytes: 4096,
        max_payload_bytes: 64,
        max_metadata_entries: 1,
        max_metadata_bytes: 256,
        max_platform_error_details: 1,
        max_platform_error_fields: 1,
        ..Default::default()
    };
    limits.validate().unwrap();
    let retained = decoded();
    assert!(retained.encoded_len() < limits.max_message_bytes);
    assert_eq!(
        validate(retained, &limits).unwrap_err().code(),
        Code::ResourceExhausted
    );

    let command = validate(decoded(), &InvocationLimits::default()).unwrap();
    assert_eq!(
        builder(4096)
            .build(super::activation_request(command))
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    let mut compact = decoded();
    compact.activation_id = Some(ID.into());
    let command = validate(compact, &limits).unwrap();
    let envelope = builder(4096)
        .build(super::activation_request(command))
        .unwrap();
    assert_eq!(envelope.activation_id.0, ID);
}

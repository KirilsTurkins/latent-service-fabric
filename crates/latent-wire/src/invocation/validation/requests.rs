use latent_activation::TraceContext;
use latent_core::{ActivationId, InvocationPrincipal};
use prost::Message;
use tonic::Status;

use super::super::{
    invocation_request_from_proto, proto, InvocationCommand, InvocationLimits, PrincipalPolicy,
};
use super::fields::{
    exhausted, identifier, media_type, RetainedBytes, GENERATED_ACTIVATION_ID_BYTES,
};

pub(in super::super) fn validate_invoke(
    request: proto::InvokeRequest,
    principal: InvocationPrincipal,
    trace: TraceContext,
    effective_deadline_unix_millis: Option<u64>,
    limits: &InvocationLimits,
    principals: &dyn PrincipalPolicy,
) -> Result<InvocationCommand, Status> {
    validate_request(&request, &principal, &trace, limits)?;
    let target = request.target.as_ref().expect("validated target");
    principals
        .authorize_target(&principal, &target.tenant)
        .map_err(super::super::platform_status)?;
    let mut request = invocation_request_from_proto(request)
        .map_err(|_| Status::invalid_argument("invalid invocation request"))?;
    request.deadline_unix_millis = effective_deadline_unix_millis;
    Ok(InvocationCommand {
        principal,
        trace,
        request,
    })
}

fn validate_request(
    request: &proto::InvokeRequest,
    principal: &InvocationPrincipal,
    trace: &TraceContext,
    limits: &InvocationLimits,
) -> Result<(), Status> {
    let mut bytes = RetainedBytes::new::<proto::InvokeRequest>(limits)?;
    bytes.payload(&request.payload, limits.max_payload_bytes)?;
    bytes.string(&request.media_type, limits.max_string_bytes)?;
    media_type(&request.media_type, limits.max_string_bytes)?;
    bytes.hash_metadata(&request.metadata, limits)?;
    for value in [
        request.activation_id.as_ref(),
        request.idempotency_key.as_ref(),
    ]
    .into_iter()
    .flatten()
    {
        bytes.string(value, limits.max_id_bytes)?;
        identifier(value, limits.max_id_bytes)?;
    }
    for value in [
        request.parent_activation_id.as_ref(),
        request.root_activation_id.as_ref(),
    ]
    .into_iter()
    .flatten()
    {
        let maximum = limits.max_id_bytes.max(GENERATED_ACTIVATION_ID_BYTES);
        bytes.string(value, maximum)?;
        identifier(value, maximum)?;
    }
    if request.parent_activation_id.is_some() && request.root_activation_id.is_none() {
        return Err(Status::invalid_argument(
            "parent activation identity requires root identity",
        ));
    }
    if request.priority > u32::from(u8::MAX) {
        return Err(Status::invalid_argument(
            "priority must fit in an unsigned byte",
        ));
    }
    let target = request
        .target
        .as_ref()
        .ok_or_else(|| Status::invalid_argument("invocation target is required"))?;
    for value in [
        &target.tenant,
        &target.service,
        &target.contract,
        &target.function,
    ]
    .into_iter()
    .chain(target.route.iter())
    {
        bytes.string(value, limits.max_id_bytes)?;
        identifier(value, limits.max_id_bytes)?;
    }
    let budget = request
        .budget
        .as_ref()
        .ok_or_else(|| Status::invalid_argument("resource budget is required"))?;
    validate_budget(budget, limits)?;
    charge_context(&mut bytes, principal, trace, limits)?;
    // encoded_len traverses maps, so call it only after row and byte bounds.
    ensure_message_size(request, limits)
}

fn charge_context(
    bytes: &mut RetainedBytes,
    principal: &InvocationPrincipal,
    trace: &TraceContext,
    limits: &InvocationLimits,
) -> Result<(), Status> {
    // Authentication validates semantics separately. All command allocations
    // still share this aggregate limit before destination maps are allocated.
    bytes.charge(std::mem::size_of::<InvocationCommand>())?;
    for value in [
        Some(&principal.subject),
        principal.tenant.as_ref().map(|id| &id.0),
        principal.service.as_ref().map(|id| &id.0),
    ]
    .into_iter()
    .flatten()
    {
        bytes.string(value, limits.max_id_bytes)?;
    }
    for value in [&trace.trace_id.0, &trace.span_id.0] {
        bytes.string(value, limits.max_id_bytes.max(32))?;
    }
    for metadata in [&principal.claims, &trace.baggage] {
        bytes.metadata(metadata, limits, limits.max_metadata_entries, false)?;
    }
    Ok(())
}

fn validate_budget(
    budget: &proto::ResourceBudget,
    limits: &InvocationLimits,
) -> Result<(), Status> {
    // Raising an RPC ceiling does not enable later-phase runtime capabilities.
    super::super::budget_from_proto(*budget)
        .validate_phase1_request()
        .map_err(|_| {
            Status::invalid_argument("resource budget requests an unsupported Phase 1 dimension")
        })?;
    if budget.cpu_fuel > limits.max_cpu_fuel
        || budget.memory_bytes > limits.max_memory_bytes
        || budget.child_calls > limits.max_child_calls
        || budget.outbound_requests > limits.max_outbound_requests
        || budget.state_read_bytes > limits.max_state_read_bytes
        || budget.state_write_bytes > limits.max_state_write_bytes
        || budget.blob_read_bytes > limits.max_blob_read_bytes
        || budget.blob_write_bytes > limits.max_blob_write_bytes
        || budget.log_bytes > limits.max_log_bytes
        || budget.effect_count > limits.max_effect_count
        || budget
            .wall_time_limit_millis
            .is_some_and(|value| value > limits.max_timeout_millis)
    {
        return Err(exhausted());
    }
    Ok(())
}

pub(in super::super) fn validate_cancel(
    request: proto::CancelRequest,
    limits: &InvocationLimits,
) -> Result<proto::CancelRequest, Status> {
    let mut bytes = RetainedBytes::new::<proto::CancelRequest>(limits)?;
    let maximum = limits.max_id_bytes.max(GENERATED_ACTIVATION_ID_BYTES);
    bytes.string(&request.activation_id, maximum)?;
    bytes.string(&request.reason, limits.max_cancel_reason_bytes)?;
    identifier(&request.activation_id, maximum)?;
    if request.reason.chars().any(char::is_control) {
        return Err(Status::invalid_argument(
            "cancellation reason contains a control character",
        ));
    }
    ensure_message_size(&request, limits)?;
    Ok(request)
}

pub(in super::super) fn validate_status_query(
    request: proto::GetActivationRequest,
    limits: &InvocationLimits,
) -> Result<ActivationId, Status> {
    let mut bytes = RetainedBytes::new::<proto::GetActivationRequest>(limits)?;
    let maximum = limits.max_id_bytes.max(GENERATED_ACTIVATION_ID_BYTES);
    bytes.string(&request.activation_id, maximum)?;
    identifier(&request.activation_id, maximum)?;
    ensure_message_size(&request, limits)?;
    Ok(ActivationId(request.activation_id))
}

fn ensure_message_size(message: &impl Message, limits: &InvocationLimits) -> Result<(), Status> {
    if message.encoded_len() > limits.max_message_bytes {
        Err(exhausted())
    } else {
        Ok(())
    }
}

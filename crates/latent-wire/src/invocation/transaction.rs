//! Reuse ordinary authenticated validation and the already pinned arrival.
use super::{
    authentication, conversion, deadline, local, proto, validation, AuthenticatedInvocationContext,
    InvocationLimits, InvocationResponse, InvocationRevision, PrincipalPolicy,
};
use latent_activation::{ActivationRequest, TraceContext};
use latent_core::{ActivationClock, PlatformError, PlatformErrorCode};
use std::time::Duration;
use tonic::{Request, Status};

pub(crate) fn pin_transaction_arrival<T>(
    request: &Request<T>,
    invocation: &proto::InvokeRequest,
    context: AuthenticatedInvocationContext,
    clock: &dyn ActivationClock,
    limits: &InvocationLimits,
) -> Result<AuthenticatedInvocationContext, Status> {
    let sample = clock.sample();
    let plan = deadline::plan_parts(
        request.metadata(),
        invocation.deadline_unix_millis,
        context.transport_deadline_unix_millis(),
        context.transport_expires_at(),
        sample,
        limits,
    )?;
    let allowance = Duration::from_millis(limits.max_timeout_millis.min(180_000));
    let maximum = sample
        .monotonic()
        .checked_add(allowance)
        .ok_or_else(|| Status::invalid_argument("monotonic deadline overflow"))?;
    let expires_at = plan
        .expires_at
        .map_or(maximum, |expiry| expiry.min(maximum));
    let remaining = expires_at.saturating_duration_since(sample.monotonic());
    let millis = u64::try_from(remaining.as_nanos().div_ceil(1_000_000))
        .map_err(|_| Status::invalid_argument("transport deadline overflow"))?;
    let unix = sample
        .unix_millis()
        .checked_add(millis)
        .ok_or_else(|| Status::invalid_argument("transport deadline overflow"))?;
    Ok(context.with_transport_deadline_at(unix, expires_at))
}

pub(crate) fn transaction_request(
    request: proto::InvokeRequest,
    context: &AuthenticatedInvocationContext,
    trace: TraceContext,
    limits: &InvocationLimits,
    principals: &dyn PrincipalPolicy,
) -> Result<ActivationRequest, PlatformError> {
    authentication::validate_trace(&trace, limits)?;
    let command = validation::validate_invoke(
        request,
        context.principal().clone(),
        trace,
        context.transport_deadline_unix_millis(),
        limits,
        principals,
    )
    .map_err(|status| PlatformError {
        code: match status.code() {
            tonic::Code::PermissionDenied | tonic::Code::Unauthenticated => {
                PlatformErrorCode::PermissionDenied
            }
            tonic::Code::ResourceExhausted => PlatformErrorCode::ResourceExhausted,
            tonic::Code::DeadlineExceeded => PlatformErrorCode::DeadlineExceeded,
            _ => PlatformErrorCode::InvalidArgument,
        },
        message: "invalid transactional invocation".into(),
        retryable: false,
        details: Vec::new(),
    })?;
    Ok(local::activation_request(command))
}

pub(crate) fn transaction_invocation_response(
    receipt: latent_node::ActivationReceipt,
    outcome: latent_activation::ActivationOutcome,
    limits: &InvocationLimits,
) -> proto::InvokeResponse {
    conversion::public_invocation_response_to_proto(
        InvocationResponse {
            receipt: super::InvocationReceipt {
                activation_id: receipt.activation_id,
                resolved_revision: receipt
                    .resolved_revision
                    .map(|resolved| InvocationRevision {
                        revision_id: resolved.revision,
                        release_digest: resolved.release,
                        publication_id: resolved.publication,
                        route_generation: resolved.route_generation,
                    }),
            },
            outcome,
        },
        limits,
    )
}

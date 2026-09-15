use super::{head::Head, Shared};
use latent_activation::{ActivationOutcome, ActivationRequest};
use latent_control_store::http_routes::AcceptedHttpRoute;
use latent_core::{Metadata, PlatformError, PlatformErrorCode};
use latent_ingress::http::{self, Delivery, Invocation, Outcome, TrustedContext};
use latent_node::ActivationReceipt;
use latent_wire::invocation::{
    InvocationTraceSource, LocalPrincipalPolicy, PrincipalPolicy, RetainedActivation,
};
use std::sync::Arc;

pub(super) fn select(head: &Head, shared: &Shared) -> Result<AcceptedHttpRoute, u16> {
    LocalPrincipalPolicy
        .authenticate(&head.principal)
        .map_err(status)?;
    let accepted = shared
        .services
        .deployments
        .select_http(head.collector.target(), head.method())
        .map_err(|e| {
            if e.message == "http-route-not-found" {
                404
            } else {
                status(e)
            }
        })?;
    let revision = accepted.revision();
    LocalPrincipalPolicy
        .authorize_target(&head.principal, &revision.target.tenant.0)
        .map_err(status)?;
    if revision.target.contract.0 != http::CONTRACT || revision.target.function.0 != http::FUNCTION
    {
        return Err(502);
    }
    Ok(accepted)
}
pub(super) struct Retention {
    pub invocation: Invocation,
    pub _route: latent_control_store::http_routes::TriggerReadLease,
}
pub(super) fn begin(
    head: Head,
    accepted: AcceptedHttpRoute,
    shared: &Shared,
) -> Result<RetainedActivation<Retention>, u16> {
    if !shared.handle.accepting() {
        return Err(503);
    }
    let cleanup = shared
        .services
        .cleanup
        .reserve_activation()
        .map_err(status)?;
    let trace = shared.traces.next_trace().map_err(status)?;
    let context = TrustedContext::new(head.principal, trace).map_err(|_| 500u16)?;
    let invocation = head
        .collector
        .finish(context)
        .and_then(http::Request::into_invocation)
        .map_err(|e| e.status().unwrap_or(0))?;
    let (revision, catalog, lease) = accepted.into_parts();
    let request = ActivationRequest {
        activation_id: None,
        parent_activation_id: None,
        root_activation_id: None,
        principal: invocation.context().principal().clone(),
        target: revision.target.clone(),
        deadline_unix_millis: Some(invocation.deadline().unix_millis()),
        priority: 0,
        trace: invocation.context().trace().clone(),
        idempotency_key: None,
        retry_attempt: 0,
        budget: shared.services.budget.clone(),
        metadata: Metadata::new(),
        input: Vec::new(),
        input_media_type: http::VALUE_MEDIA_TYPE.to_owned(),
    };
    let mut reserved = shared
        .services
        .manager
        .reserve_selected_inbound(
            request,
            invocation.input().len(),
            invocation.deadline(),
            revision,
            Arc::new(catalog),
        )
        .map_err(status)?;
    reserved.publication_eligibility().map_err(status)?;
    let length = invocation.input().len();
    reserved.input_buffer().copy_from_slice(invocation.input());
    let handle = reserved.start(length).map_err(status)?;
    Ok(cleanup.own(
        handle,
        Retention {
            invocation,
            _route: lease,
        },
    ))
}
pub(super) fn complete(receipt: ActivationReceipt, retention: Retention) -> Result<Delivery, u16> {
    let outcome = match &receipt.outcome {
        ActivationOutcome::Succeeded(value) => Outcome::Returned {
            bytes: &value.output,
            media_type: &value.output_media_type,
        },
        ActivationOutcome::DeclaredError { .. } => Outcome::DeclaredError,
        ActivationOutcome::Failed { error, .. } => Outcome::Platform(error.code),
    };
    let delivery = retention
        .invocation
        .complete(outcome)
        .map_err(|e| e.status().unwrap_or(0));
    // Only the bounded delivery owner survives into socket writes.
    drop(receipt);
    delivery
}
fn status(error: PlatformError) -> u16 {
    let code = error.code;
    drop(error);
    match code {
        PlatformErrorCode::Unauthenticated => 401,
        PlatformErrorCode::PermissionDenied => 403,
        PlatformErrorCode::InvalidArgument => 400,
        PlatformErrorCode::NotFound => 404,
        PlatformErrorCode::DeadlineExceeded | PlatformErrorCode::Cancelled => 0,
        PlatformErrorCode::IncompatibleContract
        | PlatformErrorCode::CorruptArtifact
        | PlatformErrorCode::GuestTrap => 502,
        _ => 503,
    }
}

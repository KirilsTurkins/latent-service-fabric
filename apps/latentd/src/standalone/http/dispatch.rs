use super::{head::Head, Shared};
use latent_activation::{ActivationOutcome, ActivationRequest};
use latent_control_store::http_routes::AcceptedHttpRoute;
use latent_core::{Metadata, PlatformError, PlatformErrorCode};
use latent_ingress::http::{
    self,
    cache::{CacheLookup, CacheRequest, CacheScope},
    Delivery, Invocation, Outcome, TrustedContext,
};
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
    if let Some(cache) = &shared.handle.0.response_cache {
        let _ = cache.observe_generation(accepted.state_version());
    }
    Ok(accepted)
}
pub(super) struct Retention {
    pub invocation: Invocation,
    pub _route: latent_control_store::http_routes::TriggerReadLease,
    cache: Option<CacheRequest>,
}
pub(super) enum Begun {
    Cached(Delivery),
    Activation(Box<RetainedActivation<Retention>>),
}
pub(super) fn begin(
    head: Head,
    accepted: AcceptedHttpRoute,
    shared: &Shared,
) -> Result<Begun, u16> {
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
    let mapped = head
        .collector
        .finish(context)
        .map_err(|e| e.status().unwrap_or(0))?;
    let cache = cache_request(&mapped, &accepted, shared);
    let invocation = mapped
        .into_invocation()
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
    let eligibility = reserved.publication_eligibility().map_err(status)?;
    let cache = match cache.map(|request| {
        request
            .bind_eligibility(eligibility.cache_digest())
            .lookup()
    }) {
        Some(CacheLookup::Hit(hit)) => {
            let delivery = cached(invocation, hit, &eligibility)?;
            drop(reserved);
            drop(cleanup);
            return Ok(Begun::Cached(delivery));
        }
        Some(CacheLookup::Miss(request)) => Some(request),
        None => None,
    };
    let length = invocation.input().len();
    reserved.input_buffer().copy_from_slice(invocation.input());
    let handle = reserved.start(length).map_err(status)?;
    let activation = cleanup.own(
        handle,
        Retention {
            invocation,
            _route: lease,
            cache,
        },
    );
    // This fixed-size owner allocation is covered by the exchange reservation.
    Ok(Begun::Activation(Box::new(activation)))
}
fn cache_request(
    mapped: &http::Request,
    accepted: &AcceptedHttpRoute,
    shared: &Shared,
) -> Option<CacheRequest> {
    let cache = shared.handle.0.response_cache.as_ref()?;
    let revision = accepted.revision();
    let publication = revision.publication.as_ref()?;
    cache.request(
        mapped,
        &CacheScope {
            tenant: &revision.target.tenant.0,
            publication: publication.as_str(),
            release: &revision.release.0,
            revision: &revision.revision.0,
            renderer_profile: http::PROFILE,
            trigger: &accepted.trigger().0,
            route_generation: revision.route_generation.0,
            state_version: accepted.state_version(),
        },
    )
}
fn cached(
    invocation: Invocation,
    hit: http::cache::CacheHit,
    eligibility: &latent_artifacts::ReleaseUseEligibility,
) -> Result<Delivery, u16> {
    // Linearize use under the live lifecycle/signing authority fence used by
    // execution. A hit still pays normal admission, but no execution cell.
    let mut delivery = None;
    let mut owners = Some((invocation, hit));
    eligibility
        .with_current(&mut |checker| {
            checker.check()?;
            let (invocation, hit) = owners.take().expect("one cache read");
            delivery = Some(invocation.complete_cache_hit(hit));
            Ok(())
        })
        .map_err(status)?;
    delivery
        .expect("guarded cache read")
        .map_err(|e| e.status().unwrap_or(0))
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
        .complete_cached(outcome, retention.cache)
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

use super::{head::Head, Shared};
use latent_activation::{ActivationOutcome, ActivationRequest};
use latent_control_store::http_routes::{AcceptedHttpRoute, AcceptedHttpTarget};
use latent_core::{
    diagnostic::{
        ActivationDiagnostic, ActivationDiagnosticSink, DiagnosticReason, DiagnosticStage,
    },
    PlatformError, PlatformErrorCode, TenantId,
};
use latent_ingress::http::{
    self,
    cache::{CacheLookup, CacheRequest, CacheScope},
    Delivery, DeliveryCause, Invocation, Outcome, TrustedContext,
};
use latent_node::{ActivationReceipt, LocalActivationJournal};
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
                // Only diagnose an owned static profile after the requested
                // method genuinely missed. Never route HEAD through a GET
                // application or replace an explicitly matched application.
                for method in [http::Method::Get, http::Method::Head] {
                    if method == head.method() {
                        continue;
                    }
                    if let Ok(route) = shared
                        .services
                        .deployments
                        .select_http(head.collector.target(), method)
                    {
                        if let AcceptedHttpTarget::StaticWeb { publication, .. } = route.target() {
                            if let Some(tenant) = publication.scope.tenant() {
                                if let Err(error) = LocalPrincipalPolicy
                                    .authorize_target(&head.principal, &tenant.0)
                                {
                                    return status(error);
                                }
                                return 405;
                            }
                        }
                    }
                }
                404
            } else {
                status(e)
            }
        })?;
    match accepted.target() {
        AcceptedHttpTarget::Application { revision, .. } => {
            if head.public_document {
                return Err(403);
            }
            LocalPrincipalPolicy
                .authorize_target(&head.principal, &revision.target.tenant.0)
                .map_err(status)?;
            if accepted.transaction().is_none()
                && (revision.target.contract.0 != http::CONTRACT
                    || revision.target.function.0 != http::FUNCTION)
            {
                return Err(502);
            }
        }
        AcceptedHttpTarget::StaticWeb { publication, .. } => {
            let tenant = publication.scope.tenant().ok_or(403u16)?;
            LocalPrincipalPolicy
                .authorize_target(&head.principal, &tenant.0)
                .map_err(status)?;
        }
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
    journal: LocalActivationJournal,
    tenant: TenantId,
    scheme: http::Scheme,
    transaction: Option<(
        Arc<latent_node::transaction_runtime::NativeTransactionAdmission>,
        Arc<latent_node::transaction_runtime::TransactionInstallation>,
    )>,
    clock: Arc<dyn latent_core::ActivationClock>,
}
pub(super) enum Begun {
    Cached(Delivery),
    Result(latent_core::BoxFuture<'static, Result<Delivery, u16>>),
    Activation(Box<RetainedActivation<Retention>>),
}
#[expect(
    clippy::too_many_lines,
    reason = "Original route, inbound, cleanup and delivery owners transfer in one bounded scope"
)]
pub(super) fn begin(
    head: Head,
    accepted: AcceptedHttpRoute,
    shared: &Shared,
) -> Result<Begun, u16> {
    if !shared.handle.accepting() {
        return Err(503);
    }
    // The static branch is consumed by shared asset delivery before this point.
    // Refuse a misrouted call before reserving cleanup, trace or activation state.
    if !matches!(accepted.target(), AcceptedHttpTarget::Application { .. }) {
        return Err(502);
    }
    let transaction = accepted.transaction().cloned();
    let trace = shared.traces.next_trace().map_err(status)?;
    let context = TrustedContext::new(head.principal, trace).map_err(|_| 500u16)?;
    let mapped = head
        .collector
        .finish(context)
        .map_err(|e| e.status().unwrap_or(0))?;
    let cache = cache_request(&mapped, &accepted, shared);
    let (invocation, facts) = super::transaction::map(mapped, transaction.as_ref())?;
    let (target, lease) = accepted.into_parts();
    let AcceptedHttpTarget::Application { revision, catalog } = target else {
        drop(lease);
        return Err(502);
    };
    if let (Some(route), Some(facts)) = (transaction.as_ref(), facts.as_ref()) {
        if route.mode() == http::transaction::RouteMode::Result {
            return Ok(Begun::Result(super::transaction::recover(
                shared.services.transactions.as_ref().ok_or(503u16)?,
                route,
                facts,
                invocation,
                revision,
                lease,
                shared.services.clock.as_ref(),
            )?));
        }
    }
    let cleanup = shared
        .services
        .cleanup
        .reserve_activation()
        .map_err(status)?;
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
        budget: super::transaction::budget(&shared.services.budget, transaction.as_ref()),
        metadata: facts
            .as_ref()
            .map(super::transaction::business_metadata)
            .unwrap_or_default(),
        input: Vec::new(),
        input_media_type: http::VALUE_MEDIA_TYPE.to_owned(),
    };
    // Diagnostics belong to the admitted target, including principals whose
    // tenant scope is global. Never derive this from a guest header or value.
    let tenant = revision.target.tenant.clone();
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
    let eligibility = match reserved.publication_eligibility() {
        Ok(eligibility) => eligibility,
        Err(error) => return Err(status(reserved.reject(error))),
    };
    let transaction = match (transaction.as_ref(), facts.as_ref()) {
        (Some(route), Some(facts)) => {
            let binding = shared
                .services
                .transactions
                .as_ref()
                .ok_or_else(|| PlatformError {
                    code: PlatformErrorCode::Unavailable,
                    message: "transaction HTTP services unavailable".into(),
                    retryable: false,
                    details: Vec::new(),
                })
                .and_then(|services| {
                    super::transaction::bind(
                        services,
                        route,
                        facts,
                        &mut reserved,
                        invocation.input().len(),
                    )
                });
            match binding {
                Ok(binding) => Some(binding),
                Err(error) => return Err(status(reserved.reject(error))),
            }
        }
        _ => None,
    };
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
            journal: shared.services.manager.journal(),
            tenant,
            scheme: shared.settings.scheme,
            transaction,
            clock: Arc::clone(&shared.services.clock),
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
    if accepted.transaction().is_some() {
        return None;
    }
    let cache = shared.handle.0.response_cache.as_ref()?;
    let AcceptedHttpTarget::Application { revision, .. } = accepted.target() else {
        return None;
    };
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
    if let Some((admission, installation)) = &retention.transaction {
        return super::transaction::complete(
            receipt,
            retention.invocation,
            admission,
            installation,
            retention.clock.as_ref(),
        );
    }
    let outcome = match &receipt.outcome {
        ActivationOutcome::Succeeded(value) => Outcome::Returned {
            bytes: &value.output,
            media_type: &value.output_media_type,
        },
        ActivationOutcome::DeclaredError { .. } => Outcome::DeclaredError,
        ActivationOutcome::Failed { error, .. } => Outcome::Platform(error.code),
    };
    let mut delivery = retention
        .invocation
        .complete_cached(outcome, retention.cache)
        .map_err(|e| e.status().unwrap_or(0))?;
    // Validate while the actual activation ID is still owned. The socket writer
    // also checks the profile; no invalid output can publish a pending cache fill.
    delivery
        .enforce_browser_profile(retention.scheme)
        .map_err(|e| e.status().unwrap_or(0))?;
    if delivery.cause() == DeliveryCause::InvalidGuestResponse {
        retention.journal.record(
            &retention.tenant,
            &receipt.activation_id,
            ActivationDiagnostic::new(
                DiagnosticStage::OutputValidation,
                DiagnosticReason::HttpResponseRejected,
            ),
        );
    }
    // Only the bounded delivery owner survives into socket writes.
    drop(receipt);
    Ok(delivery)
}
pub(super) fn status(error: PlatformError) -> u16 {
    #[cfg(test)]
    eprintln!(
        "HTTP adapter refusal code={:?} reason={}",
        error.code, error.message
    );
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

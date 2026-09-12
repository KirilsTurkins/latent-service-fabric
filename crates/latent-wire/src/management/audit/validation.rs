use super::super::{
    bounds::{exhausted, identifier},
    proto, ManagementLimits, RequestBudget,
};
use latent_audit::AuditScope;
use latent_core::{InvocationPrincipal, TenantId};
use prost::Message;
use std::time::{Duration, Instant};
use tonic::{Request, Status};

pub(super) fn deadline<T>(request: &Request<T>) -> Instant {
    let maximum = Instant::now() + Duration::from_secs(5);
    request
        .extensions()
        .get::<crate::invocation::AuthenticatedInvocationContext>()
        .and_then(crate::invocation::AuthenticatedInvocationContext::transport_expires_at)
        .map_or(maximum, |deadline| deadline.min(maximum))
}
pub(super) fn completed(deadline: Instant) -> Result<(), Status> {
    if Instant::now() >= deadline {
        Err(Status::deadline_exceeded("audit query deadline exceeded"))
    } else {
        Ok(())
    }
}
pub(super) fn encoded<T: Message>(value: &T, maximum: usize) -> Result<(), Status> {
    if value.encoded_len() > maximum {
        Err(exhausted())
    } else {
        Ok(())
    }
}
fn limits(limits: &ManagementLimits) -> ManagementLimits {
    let mut value = limits.clone();
    value.max_request_bytes = value.max_request_bytes.min(super::MAX_REQUEST_BYTES);
    value.max_page_token_bytes = value.max_page_token_bytes.min(1024);
    value
}
fn times(from: Option<u64>, to: Option<u64>) -> Result<(), Status> {
    if from.zip(to).is_some_and(|(from, to)| from > to) {
        Err(Status::invalid_argument("invalid audit time range"))
    } else {
        Ok(())
    }
}
fn text(budget: &mut RequestBudget, value: Option<&String>, maximum: usize) -> Result<(), Status> {
    budget.optional_string(value, maximum)?;
    value.map_or(Ok(()), |value| identifier(value, maximum))
}
fn tenant(principal: &InvocationPrincipal, claimed: Option<&str>) -> Result<AuditScope, Status> {
    let tenant = principal
        .tenant
        .as_ref()
        .ok_or_else(|| Status::permission_denied("audit tenant is required"))?;
    if claimed.is_some_and(|claimed| claimed != tenant.0) {
        return Err(Status::permission_denied(
            "audit tenant does not match authenticated scope",
        ));
    }
    Ok(AuditScope::Tenant(TenantId(tenant.0.as_str().into())))
}
pub(super) fn typed(
    request: &proto::QueryPhase2AuditRequest,
    principal: &InvocationPrincipal,
    configured: &ManagementLimits,
) -> Result<AuditScope, Status> {
    let limits = limits(configured);
    let mut budget = RequestBudget::new::<proto::QueryPhase2AuditRequest>(&limits)?;
    let scope = request
        .scope
        .as_ref()
        .ok_or_else(|| Status::invalid_argument("audit scope is required"))?;
    budget.allocation::<proto::AuditQueryScope>(1)?;
    text(
        &mut budget,
        scope.tenant.as_ref(),
        limits.max_id_bytes.min(512),
    )?;
    if let Some(filter) = &request.filter {
        budget.allocation::<proto::Phase2AuditFilter>(1)?;
        text(
            &mut budget,
            filter.actor_subject.as_ref(),
            limits.max_id_bytes.min(512),
        )?;
        if let Some(kind) = filter.kind {
            super::enums::kind_from_proto(kind)?;
        }
        times(filter.from_unix_millis, filter.to_unix_millis)?;
    }
    budget.page(request.page.as_ref(), &limits)?;
    encoded(request, limits.max_request_bytes)?;
    match proto::AuditScopeKind::try_from(scope.kind) {
        Ok(proto::AuditScopeKind::Tenant) if scope.tenant.is_some() => {
            tenant(principal, scope.tenant.as_deref())
        }
        Ok(proto::AuditScopeKind::Node) if scope.tenant.is_none() => Ok(AuditScope::Node),
        _ => Err(Status::invalid_argument("invalid audit scope")),
    }
}
pub(super) fn legacy(
    request: &proto::QueryAuditRequest,
    principal: &InvocationPrincipal,
    configured: &ManagementLimits,
) -> Result<AuditScope, Status> {
    let limits = limits(configured);
    let mut budget = RequestBudget::new::<proto::QueryAuditRequest>(&limits)?;
    for value in [
        request.tenant.as_ref(),
        request.actor.as_ref(),
        request.action.as_ref(),
        request.resource_prefix.as_ref(),
    ] {
        text(&mut budget, value, limits.max_id_bytes.min(512))?;
    }
    times(request.from_unix_millis, request.to_unix_millis)?;
    budget.page(request.page.as_ref(), &limits)?;
    encoded(request, limits.max_request_bytes)?;
    if request.resource_prefix.is_some() {
        return Err(Status::invalid_argument(
            "resource-prefix audit filtering is unsupported",
        ));
    }
    tenant(principal, request.tenant.as_deref())
}

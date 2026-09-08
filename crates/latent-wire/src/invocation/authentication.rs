use super::{boundary_error, platform_status, InvocationLimits};
use latent_activation::TraceContext;
use latent_core::{
    InvocationPrincipal, Metadata, PlatformError, PlatformErrorCode, PrincipalKind, TenantId,
};
use tonic::{Request, Status};

/// Trusted identity supplied by the embedding listener; invocation metadata
/// never creates or overrides this request extension.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuthenticatedInvocationContext {
    principal: InvocationPrincipal,
    transport_deadline_unix_millis: Option<u64>,
}
impl AuthenticatedInvocationContext {
    #[must_use]
    pub fn new(principal: InvocationPrincipal) -> Self {
        Self {
            principal,
            transport_deadline_unix_millis: None,
        }
    }
    #[must_use]
    pub fn with_transport_deadline(mut self, deadline_unix_millis: u64) -> Self {
        self.transport_deadline_unix_millis = Some(deadline_unix_millis);
        self
    }
    #[must_use]
    pub fn principal(&self) -> &InvocationPrincipal {
        &self.principal
    }
    #[must_use]
    pub const fn transport_deadline_unix_millis(&self) -> Option<u64> {
        self.transport_deadline_unix_millis
    }
    #[must_use]
    pub fn request<T>(&self, message: T) -> Request<T> {
        let mut request = Request::new(message);
        request.extensions_mut().insert(self.clone());
        request
    }
    pub(crate) fn into_principal(self) -> InvocationPrincipal {
        self.principal
    }
}

pub trait PrincipalPolicy: Send + Sync {
    fn authenticate(&self, principal: &InvocationPrincipal) -> Result<(), PlatformError>;
    fn authorize_target(
        &self,
        principal: &InvocationPrincipal,
        target_tenant: &str,
    ) -> Result<(), PlatformError>;
}

/// All local identities, including administrators, are scoped to one tenant.
#[derive(Debug, Clone, Copy, Default)]
pub struct LocalPrincipalPolicy;
impl PrincipalPolicy for LocalPrincipalPolicy {
    fn authenticate(&self, principal: &InvocationPrincipal) -> Result<(), PlatformError> {
        principal_shape(principal)
    }
    fn authorize_target(
        &self,
        principal: &InvocationPrincipal,
        target_tenant: &str,
    ) -> Result<(), PlatformError> {
        self.authenticate(principal)?;
        if principal
            .tenant
            .as_ref()
            .is_some_and(|tenant| tenant.0 == target_tenant)
        {
            Ok(())
        } else {
            Err(boundary_error(
                PlatformErrorCode::PermissionDenied,
                "principal cannot access the target tenant",
            ))
        }
    }
}

pub(crate) fn take_context<T>(
    request: &mut Request<T>,
    limits: &InvocationLimits,
    policy: &dyn PrincipalPolicy,
) -> Result<AuthenticatedInvocationContext, Status> {
    let context = request
        .extensions()
        .get::<AuthenticatedInvocationContext>()
        .ok_or_else(|| Status::unauthenticated("authentication is required"))?;
    validate_principal(context.principal(), limits).map_err(platform_status)?;
    policy
        .authenticate(context.principal())
        .map_err(platform_status)?;
    Ok(request
        .extensions_mut()
        .remove::<AuthenticatedInvocationContext>()
        .expect("validated context"))
}

pub(crate) fn authenticated_tenant<'a>(
    principal: &'a InvocationPrincipal,
    limits: &InvocationLimits,
) -> Result<&'a TenantId, PlatformError> {
    validate_principal(principal, limits)?;
    Ok(principal.tenant.as_ref().expect("validated tenant"))
}

fn principal_shape(principal: &InvocationPrincipal) -> Result<(), PlatformError> {
    if principal.kind == PrincipalKind::Anonymous
        || principal.subject.is_empty()
        || principal.tenant.is_none()
        || (principal.kind == PrincipalKind::Service && principal.service.is_none())
    {
        return Err(boundary_error(
            PlatformErrorCode::Unauthenticated,
            "a scoped authenticated principal is required",
        ));
    }
    Ok(())
}

pub(super) fn validate_principal(
    principal: &InvocationPrincipal,
    limits: &InvocationLimits,
) -> Result<(), PlatformError> {
    principal_shape(principal)?;
    identifier(&principal.subject, limits.max_id_bytes)?;
    for id in [
        principal.tenant.as_ref().map(|id| &id.0),
        principal.service.as_ref().map(|id| &id.0),
    ]
    .into_iter()
    .flatten()
    {
        identifier(id, limits.max_id_bytes)?;
    }
    metadata(&principal.claims, limits)
}

pub(super) fn validate_trace(
    trace: &TraceContext,
    limits: &InvocationLimits,
) -> Result<(), PlatformError> {
    identifier(&trace.trace_id.0, limits.max_id_bytes.max(32))?;
    identifier(&trace.span_id.0, limits.max_id_bytes.max(16))?;
    metadata(&trace.baggage, limits)
}

fn identifier(value: &String, maximum: usize) -> Result<(), PlatformError> {
    if value.capacity() > maximum {
        return Err(too_large());
    }
    if value.is_empty() || value.chars().any(|c| c.is_control() || c.is_whitespace()) {
        return Err(boundary_error(
            PlatformErrorCode::InvalidArgument,
            "invalid principal or trace identifier",
        ));
    }
    Ok(())
}

fn metadata(value: &Metadata, limits: &InvocationLimits) -> Result<(), PlatformError> {
    if value.len() > limits.max_metadata_entries
        || value
            .len()
            .checked_add(1)
            .and_then(|count| count.checked_mul(4096))
            .is_none_or(|cost| cost > limits.max_message_bytes)
    {
        return Err(too_large());
    }
    let mut available = limits.max_metadata_bytes;
    for (key, entry) in value {
        if key.capacity() > limits.max_string_bytes || entry.capacity() > limits.max_string_bytes {
            return Err(too_large());
        }
        available = available
            .checked_sub(key.capacity())
            .and_then(|n| n.checked_sub(entry.capacity()))
            .ok_or_else(too_large)?;
    }
    Ok(())
}
fn too_large() -> PlatformError {
    boundary_error(
        PlatformErrorCode::ResourceExhausted,
        "authentication or trace context exceeds limits",
    )
}

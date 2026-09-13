use super::super::{bounds, proto, ManagementLimits, RequestBudget};
use latent_core::{InvocationPrincipal, PlatformError, PlatformErrorCode, PrincipalKind};
use latent_policy::capability as domain;
use prost::Message;
use std::time::{Duration, Instant};
use tonic::{Request, Status};

pub(super) fn invalid() -> Status {
    Status::invalid_argument("capability-policy-invalid")
}
pub(super) fn platform(error: PlatformError) -> Status {
    let code = error.code;
    drop(error);
    match code {
        PlatformErrorCode::InvalidArgument => invalid(),
        PlatformErrorCode::StateConflict => {
            Status::failed_precondition("capability-policy-conflict")
        }
        PlatformErrorCode::ResourceExhausted => {
            Status::resource_exhausted("capability-policy-capacity")
        }
        PlatformErrorCode::PermissionDenied => {
            Status::permission_denied("capability-policy-denied")
        }
        PlatformErrorCode::DeadlineExceeded => {
            Status::deadline_exceeded("capability-policy-deadline")
        }
        _ => Status::unavailable("capability-policy-unavailable"),
    }
}
pub(super) fn too_large() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::ResourceExhausted,
        message: "capability-policy-response-capacity".into(),
        retryable: false,
        details: Vec::new(),
    }
}
pub(super) fn deadline<T>(request: &Request<T>) -> Instant {
    let maximum = Instant::now() + Duration::from_secs(30);
    request
        .extensions()
        .get::<crate::invocation::AuthenticatedInvocationContext>()
        .and_then(crate::invocation::AuthenticatedInvocationContext::transport_expires_at)
        .map_or(maximum, |value| value.min(maximum))
}
pub(super) fn completed(deadline: Instant) -> Result<(), Status> {
    if Instant::now() >= deadline {
        return Err(Status::deadline_exceeded("capability-policy-deadline"));
    }
    Ok(())
}
pub(super) fn identity(principal: &InvocationPrincipal) -> Result<&str, Status> {
    if principal.kind != PrincipalKind::Administrator {
        return Err(Status::permission_denied("capability-policy-denied"));
    }
    let tenant = principal
        .tenant
        .as_ref()
        .ok_or_else(|| Status::permission_denied("capability-policy-denied"))?;
    bounds::identifier(&tenant.0, 256)?;
    bounds::identifier(&principal.subject, 256)?;
    Ok(&tenant.0)
}
pub(super) fn kind(value: i32) -> Result<domain::RecordKind, Status> {
    match proto::CapabilityPolicyRecordKind::try_from(value) {
        Ok(proto::CapabilityPolicyRecordKind::Policy) => Ok(domain::RecordKind::Policy),
        Ok(proto::CapabilityPolicyRecordKind::ProviderBinding) => {
            Ok(domain::RecordKind::ProviderBinding)
        }
        _ => Err(invalid()),
    }
}
pub(super) fn id(value: &String, budget: &mut RequestBudget) -> Result<(), Status> {
    budget.string(value, 256)?;
    bounds::identifier(value, 256)
}
pub(super) fn encoded(value: &impl Message, limits: &ManagementLimits) -> Result<(), Status> {
    if value.encoded_len() > limits.max_request_bytes.min(super::MAX_REQUEST_BYTES) {
        return Err(bounds::exhausted());
    }
    Ok(())
}
pub(super) fn language(kind: domain::RecordKind) -> &'static str {
    match kind {
        domain::RecordKind::Policy => domain::LANGUAGE,
        domain::RecordKind::ProviderBinding => domain::PROVIDER_BINDING_LANGUAGE,
    }
}
pub(super) fn normalize(
    value: &proto::Policy,
    tenant: &str,
    budget: &mut RequestBudget,
) -> Result<(domain::RecordKind, String), Status> {
    id(&value.id, budget)?;
    budget.string(&value.document, domain::MAX_DOCUMENT_BYTES)?;
    budget.string(&value.language, 64)?;
    budget.string(&value.content_digest, 71)?;
    let kind = kind(value.record_kind)?;
    if value.language != language(kind)
        || value.generation != 0
        || value.revoked
        || !value.content_digest.is_empty()
    {
        return Err(invalid());
    }
    let metadata = value.metadata.as_ref().ok_or_else(invalid)?;
    budget.string(&metadata.name, 256)?;
    budget.optional_string(metadata.tenant.as_ref(), 256)?;
    if metadata.name != value.id
        || metadata.tenant.as_deref() != Some(tenant)
        || metadata.namespace.is_some()
        || !metadata.labels.is_empty()
        || !metadata.annotations.is_empty()
    {
        return Err(invalid());
    }
    let bytes = match kind {
        domain::RecordKind::Policy => domain::CapabilityPolicy::parse(value.document.as_bytes())
            .map_err(platform)?
            .canonical()
            .to_vec(),
        domain::RecordKind::ProviderBinding => {
            domain::ProviderBinding::parse(value.document.as_bytes())
                .map_err(platform)?
                .canonical()
                .to_vec()
        }
    };
    String::from_utf8(bytes)
        .map(|bytes| (kind, bytes))
        .map_err(|_| invalid())
}

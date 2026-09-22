use super::super::{bounds, proto, ManagementLimits, RequestBudget};
use latent_artifacts::{ReleaseActor, ReleaseActorKind};
use latent_control_store::http_routes::{
    TriggerOperationContext, TriggerOperationRequest, TriggerPageRequest, MAX_IDENTIFIER_BYTES,
    MAX_PAGE_SIZE,
};
use latent_core::{InvocationPrincipal, ServiceId, TenantId, TriggerId};
use prost::Message;
use std::{
    collections::HashMap,
    time::{Duration, Instant},
};
use tonic::{Request, Status};

pub(super) fn deadline<T>(request: &Request<T>) -> Instant {
    let maximum = Instant::now() + Duration::from_secs(30);
    request
        .extensions()
        .get::<crate::invocation::AuthenticatedInvocationContext>()
        .and_then(crate::invocation::AuthenticatedInvocationContext::transport_expires_at)
        .map_or(maximum, |d| d.min(maximum))
}
pub(super) fn completed(expires: Instant) -> Result<(), Status> {
    if Instant::now() >= expires {
        Err(Status::deadline_exceeded("HTTP trigger deadline exceeded"))
    } else {
        Ok(())
    }
}
pub(super) fn tenant(principal: &InvocationPrincipal) -> Result<TenantId, Status> {
    let tenant = principal
        .tenant
        .as_ref()
        .ok_or_else(|| Status::permission_denied("trigger tenant is required"))?;
    if tenant.0.capacity() > MAX_IDENTIFIER_BYTES {
        return Err(bounds::exhausted());
    }
    bounds::identifier(&tenant.0, MAX_IDENTIFIER_BYTES)?;
    Ok(tenant.clone())
}
pub(super) fn read_id(id: &String, limits: &ManagementLimits) -> Result<(), Status> {
    let mut budget = RequestBudget::new::<proto::GetTriggerRequest>(limits)?;
    field(
        id,
        &mut budget,
        MAX_IDENTIFIER_BYTES.min(limits.max_id_bytes),
    )
}
fn field(value: &String, budget: &mut RequestBudget, maximum: usize) -> Result<(), Status> {
    budget.string(value, maximum)?;
    bounds::identifier(value, maximum)
}
fn bounded(configured: &ManagementLimits) -> ManagementLimits {
    let mut limits = configured.clone();
    limits.max_request_bytes = limits.max_request_bytes.min(64 * 1024);
    limits
}
fn context(
    principal: InvocationPrincipal,
    operation: proto::TriggerOperationPrecondition,
) -> Result<TriggerOperationContext, Status> {
    let tenant = tenant(&principal)?;
    if principal.subject.capacity() > MAX_IDENTIFIER_BYTES {
        return Err(bounds::exhausted());
    }
    bounds::identifier(&principal.subject, MAX_IDENTIFIER_BYTES)?;
    Ok(TriggerOperationContext {
        tenant,
        actor: ReleaseActor {
            subject: principal.subject,
            kind: ReleaseActorKind::try_from(principal.kind)
                .map_err(|_| Status::permission_denied("unsupported trigger actor"))?,
        },
        operation_id: operation.operation_id,
        expected_state_version: operation
            .expected_state_version
            .ok_or_else(|| Status::invalid_argument("state precondition is required"))?,
    })
}
fn operation(
    op: Option<&proto::TriggerOperationPrecondition>,
    generation: Option<u64>,
    delete: bool,
    budget: &mut RequestBudget,
) -> Result<(), Status> {
    let op = op.ok_or_else(|| Status::invalid_argument("trigger operation is required"))?;
    budget.allocation::<proto::TriggerOperationPrecondition>(1)?;
    field(&op.operation_id, budget, MAX_IDENTIFIER_BYTES)?;
    if op.expected_state_version.is_none()
        || generation.is_none()
        || (delete && generation == Some(0))
    {
        return Err(Status::invalid_argument(
            "explicit trigger CAS preconditions are required",
        ));
    }
    Ok(())
}
pub(super) fn apply(
    value: proto::ApplyTriggerRequest,
    principal: InvocationPrincipal,
    configured: &ManagementLimits,
) -> Result<TriggerOperationRequest, Status> {
    let limits = bounded(configured);
    let mut budget = RequestBudget::new::<proto::ApplyTriggerRequest>(&limits)?;
    operation(
        value.operation.as_ref(),
        value.expected_generation,
        false,
        &mut budget,
    )?;
    let trigger = value
        .trigger
        .as_ref()
        .ok_or_else(|| Status::invalid_argument("trigger is required"))?;
    wire(trigger, &mut budget, &limits)?;
    if value.encoded_len() > limits.max_request_bytes {
        return Err(bounds::exhausted());
    }
    let scope = tenant(&principal)?;
    if trigger.metadata.as_ref().and_then(|m| m.tenant.as_deref()) != Some(&scope.0) {
        return Err(Status::permission_denied(
            "trigger tenant does not match authenticated scope",
        ));
    }
    Ok(TriggerOperationRequest::Apply {
        context: context(principal, value.operation.expect("validated operation"))?,
        manifest: super::conversion::manifest(value.trigger.expect("validated trigger"))?,
        expected_generation: value.expected_generation.expect("validated CAS"),
    })
}
pub(super) fn delete(
    value: proto::DeleteTriggerRequest,
    principal: InvocationPrincipal,
    configured: &ManagementLimits,
) -> Result<TriggerOperationRequest, Status> {
    let limits = bounded(configured);
    let mut budget = RequestBudget::new::<proto::DeleteTriggerRequest>(&limits)?;
    operation(
        value.operation.as_ref(),
        value.expected_generation,
        true,
        &mut budget,
    )?;
    field(
        &value.id,
        &mut budget,
        MAX_IDENTIFIER_BYTES.min(limits.max_id_bytes),
    )?;
    if value.encoded_len() > limits.max_request_bytes {
        return Err(bounds::exhausted());
    }
    Ok(TriggerOperationRequest::Delete {
        context: context(principal, value.operation.expect("validated operation"))?,
        id: TriggerId(value.id),
        expected_generation: value.expected_generation.expect("validated CAS"),
    })
}
fn map(
    values: &HashMap<String, String>,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    if values.len() > 16.min(limits.max_metadata_entries) {
        return Err(bounds::exhausted());
    }
    budget.allocation::<u8>(values.capacity().saturating_mul(128))?;
    let mut remaining = limits.max_metadata_bytes;
    for (k, v) in values {
        field(k, budget, 128.min(limits.max_string_bytes))?;
        budget.string(v, 256.min(limits.max_string_bytes))?;
        remaining = remaining
            .checked_sub(k.len() + v.len())
            .ok_or_else(bounds::exhausted)?;
    }
    Ok(())
}
pub(super) fn wire(
    value: &proto::Trigger,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    budget.allocation::<proto::Trigger>(1)?;
    field(
        &value.id,
        budget,
        MAX_IDENTIFIER_BYTES.min(limits.max_id_bytes),
    )?;
    field(&value.kind, budget, 32)?;
    if value.kind != "HttpTrigger" {
        return Err(Status::invalid_argument(
            "only the HttpTrigger profile is supported",
        ));
    }
    let m = value
        .metadata
        .as_ref()
        .ok_or_else(|| Status::invalid_argument("trigger metadata is required"))?;
    budget.allocation::<proto::ObjectMetadata>(1)?;
    field(
        &m.name,
        budget,
        MAX_IDENTIFIER_BYTES.min(limits.max_id_bytes),
    )?;
    for v in [m.tenant.as_ref(), m.namespace.as_ref()]
        .into_iter()
        .flatten()
    {
        field(v, budget, MAX_IDENTIFIER_BYTES.min(limits.max_id_bytes))?;
    }
    if m.tenant.is_none() || m.name != value.id {
        return Err(Status::invalid_argument(
            "trigger scope and name must be explicit",
        ));
    }
    map(&m.labels, budget, limits)?;
    map(&m.annotations, budget, limits)?;
    let t = value
        .target
        .as_ref()
        .ok_or_else(|| Status::invalid_argument("trigger target is required"))?;
    budget.allocation::<proto::TriggerTarget>(1)?;
    let target_kind = proto::TriggerTargetKind::try_from(t.kind)
        .map_err(|_| Status::invalid_argument("invalid trigger target kind"))?;
    match target_kind {
        proto::TriggerTargetKind::Unspecified | proto::TriggerTargetKind::Application => {
            for v in [&t.service, &t.function] {
                field(v, budget, MAX_IDENTIFIER_BYTES.min(limits.max_id_bytes))?;
            }
            field(&t.contract, budget, 256.min(limits.max_id_bytes))?;
            for v in [t.route.as_ref(), t.revision.as_ref()]
                .into_iter()
                .flatten()
            {
                field(v, budget, MAX_IDENTIFIER_BYTES)?;
            }
        }
        proto::TriggerTargetKind::StaticWeb => {
            if !t.service.is_empty()
                || !t.contract.is_empty()
                || !t.function.is_empty()
                || t.route.is_some()
                || t.revision.is_some()
                || t.deployment_generation.is_some()
            {
                return Err(Status::invalid_argument(
                    "static web target cannot carry application fields",
                ));
            }
        }
    }
    let p = t
        .publication
        .as_ref()
        .ok_or_else(|| Status::invalid_argument("explicit trigger publication is required"))?;
    budget.allocation::<proto::PublicationRef>(1)?;
    field(&p.id, budget, 83)?;
    field(&p.tenant, budget, MAX_IDENTIFIER_BYTES)?;
    if m.tenant.as_ref() != Some(&p.tenant) || p.id.parse::<latent_core::PublicationId>().is_err() {
        return Err(Status::invalid_argument(
            "trigger publication scope does not match",
        ));
    }
    if value.configuration.len() != 6 {
        return Err(Status::invalid_argument(
            "closed HTTP trigger configuration is required",
        ));
    }
    let expected_profile = match target_kind {
        proto::TriggerTargetKind::StaticWeb => "static-site-v1",
        proto::TriggerTargetKind::Unspecified | proto::TriggerTargetKind::Application => {
            "buffered-v1"
        }
    };
    if value.configuration.get("profile").map(String::as_str) != Some(expected_profile) {
        return Err(Status::invalid_argument(
            "HTTP trigger profile does not match target kind",
        ));
    }
    if target_kind == proto::TriggerTargetKind::StaticWeb
        && value
            .configuration
            .get("method")
            .is_none_or(|method| method != "GET" && method != "HEAD")
    {
        return Err(Status::invalid_argument(
            "static web trigger method must be GET or HEAD",
        ));
    }
    budget.allocation::<u8>(value.configuration.capacity().saturating_mul(128))?;
    for (k, v) in &value.configuration {
        field(k, budget, 32)?;
        let maximum = match k.as_str() {
            "path" => 8192,
            "host" => 255,
            _ => 32,
        };
        budget.string(v, maximum.min(limits.max_string_bytes))?;
    }
    Ok(())
}
pub(super) fn page(
    value: proto::ListTriggersRequest,
    tenant: TenantId,
    configured: &ManagementLimits,
) -> Result<TriggerPageRequest, Status> {
    let limits = bounded(configured);
    let mut budget = RequestBudget::new::<proto::ListTriggersRequest>(&limits)?;
    if let Some(kind) = &value.kind {
        field(kind, &mut budget, 32)?;
        if kind != "HttpTrigger" {
            return Err(Status::invalid_argument("unsupported trigger kind"));
        }
    }
    if let Some(service) = &value.target_service {
        field(
            service,
            &mut budget,
            MAX_IDENTIFIER_BYTES.min(limits.max_id_bytes),
        )?;
    }
    if let Some(page) = &value.page {
        budget.allocation::<proto::PageRequest>(1)?;
        budget.optional_string(
            page.page_token.as_ref(),
            128.min(limits.max_page_token_bytes),
        )?;
    }
    if value.encoded_len() > limits.max_request_bytes {
        return Err(bounds::exhausted());
    }
    let page = value.page.unwrap_or_default();
    let size = if page.page_size == 0 {
        limits.default_page_size.min(MAX_PAGE_SIZE)
    } else {
        page.page_size
    };
    if size > MAX_PAGE_SIZE.min(limits.max_page_size) {
        return Err(bounds::exhausted());
    }
    Ok(TriggerPageRequest {
        tenant,
        target_service: value.target_service.map(ServiceId),
        page_size: size,
        page_token: page.page_token,
    })
}

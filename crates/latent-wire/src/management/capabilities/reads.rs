use super::super::{bounds, proto, ManagementOperation, ManagementServiceAdapter, RequestBudget};
use super::{conversion, finish, page, validation, MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES};
use latent_core::{
    DeploymentId, InvocationPrincipal, Metadata, PrincipalKind, ServiceId, TenantId,
};
use prost::Message;
use tonic::{Request, Response, Status};

pub(super) async fn list(
    adapter: &ManagementServiceAdapter,
    mut request: Request<proto::ListCapabilitiesRequest>,
) -> Result<Response<proto::ListCapabilitiesResponse>, Status> {
    let deadline = validation::deadline(&request);
    let operation = if request.get_ref().include_node_usage {
        ManagementOperation::NodeInventory
    } else {
        ManagementOperation::Tenant
    };
    let principal = adapter.authenticate(&mut request, operation)?;
    let tenant = TenantId(validation::identity(&principal)?.into());
    let request = request.into_inner();
    let mut budget = RequestBudget::new::<proto::ListCapabilitiesRequest>(&adapter.limits)?;
    validation::id(&request.deployment_id, &mut budget)?;
    for filter in [&request.contract_prefix, &request.provider]
        .into_iter()
        .flatten()
    {
        budget.string(filter, 128)?;
        if filter.is_empty() || !filter.is_ascii() {
            return Err(validation::invalid());
        }
    }
    page::validate(request.page.as_ref(), &mut budget)?;
    if request.encoded_len() > MAX_REQUEST_BYTES {
        return Err(bounds::exhausted());
    }
    let inspection = adapter.capability_inspection()?;
    let permit = adapter
        .policy_control()?
        .reserve()
        .map_err(validation::platform)?;
    let maximum = adapter.limits.max_response_bytes.min(MAX_RESPONSE_BYTES);
    let read = permit.run(move |store| {
        let lease = store.reserve_inspection()?;
        let selected = inspection
            .source
            .inspect(&tenant, &DeploymentId(request.deployment_id.clone()))?;
        selected.check_owner(&inspection.broker)?;
        let mut bindings = selected
            .plan
            .as_ref()
            .map_or_else(|| Ok(Vec::new()), |p| p.inspect_bindings(&tenant))?;
        bindings.retain(|b| {
            request
                .contract_prefix
                .as_ref()
                .is_none_or(|v| b.capability.starts_with(v))
                && request
                    .provider
                    .as_ref()
                    .is_none_or(|v| &b.provider_profile == v)
        });
        let (range, next) = page::select(&request, &principal, &selected, bindings.len())?;
        let capabilities = bindings
            .into_iter()
            .skip(range.start)
            .take(range.len())
            .map(conversion::descriptor)
            .collect();
        let value = proto::ListCapabilitiesResponse {
            capabilities,
            page: Some(proto::PageResponse {
                next_page_token: next,
            }),
            revision: Some(conversion::revision(&selected)),
            state: if selected.plan.is_some() {
                "compiled-plan"
            } else {
                "binding-plan-unavailable"
            }
            .into(),
            tenant_usage: Some(conversion::tenant_usage(
                inspection.broker.inspect_tenant_usage(&tenant)?,
            )),
            node_usage: if request.include_node_usage {
                Some(conversion::node_usage(
                    &inspection.broker.inspect_node_usage()?,
                ))
            } else {
                None
            },
        };
        preflight(&value, maximum, deadline)?;
        Ok((value, lease))
    });
    let (value, lease) = tokio::time::timeout_at(deadline.into(), read)
        .await
        .map_err(|_| Status::deadline_exceeded("capability-inspection-deadline"))?
        .map_err(validation::platform)?;
    finish(value, lease, maximum, deadline)
}

fn subject(
    mut principal: InvocationPrincipal,
    input: Option<proto::CapabilityInspectionSubject>,
    budget: &mut RequestBudget,
) -> Result<InvocationPrincipal, Status> {
    principal.claims = Metadata::new();
    if let Some(input) = input {
        validation::id(&input.subject, budget)?;
        budget.string(&input.kind, 16)?;
        if let Some(service) = &input.service {
            validation::id(service, budget)?;
        }
        principal.kind = match input.kind.as_str() {
            "user" => PrincipalKind::User,
            "service" => PrincipalKind::Service,
            "node" => PrincipalKind::Node,
            "trigger" => PrincipalKind::Trigger,
            "administrator" => PrincipalKind::Administrator,
            _ => return Err(validation::invalid()),
        };
        principal.subject = input.subject;
        principal.service = input.service.map(ServiceId);
    }
    Ok(principal)
}
pub(super) async fn explain(
    adapter: &ManagementServiceAdapter,
    mut request: Request<proto::ExplainCapabilityGrantRequest>,
) -> Result<Response<proto::ExplainCapabilityGrantResponse>, Status> {
    let deadline = validation::deadline(&request);
    let principal = adapter.authenticate(&mut request, ManagementOperation::Tenant)?;
    let tenant = TenantId(validation::identity(&principal)?.into());
    let mut request = request.into_inner();
    if !request.principal.is_empty() || !request.attributes.is_empty() {
        return Err(validation::invalid());
    }
    let mut budget = RequestBudget::new::<proto::ExplainCapabilityGrantRequest>(&adapter.limits)?;
    validation::id(&request.deployment_id, &mut budget)?;
    for (value, maximum) in [
        (&request.capability_id, 128),
        (&request.operation, 64),
        (&request.resource_document, 4096),
    ] {
        budget.string(value, maximum)?;
    }
    let principal = subject(principal, request.hypothetical_subject.take(), &mut budget)?;
    if request.encoded_len() > MAX_REQUEST_BYTES {
        return Err(bounds::exhausted());
    }
    let inspection = adapter.capability_inspection()?;
    let permit = adapter
        .policy_control()?
        .reserve()
        .map_err(validation::platform)?;
    let maximum = adapter.limits.max_response_bytes.min(MAX_RESPONSE_BYTES);
    let read = permit.run(move |store| {
        let lease = store.reserve_inspection()?;
        let resource =
            super::super::parse_inspection_resource(request.resource_document.as_bytes())?;
        let selected = inspection
            .source
            .inspect(&tenant, &DeploymentId(request.deployment_id))?;
        selected.check_owner(&inspection.broker)?;
        let explanation = selected
            .plan
            .as_ref()
            .map(|plan| {
                plan.explain_grant(
                    &principal,
                    &request.capability_id,
                    &request.operation,
                    resource.target(),
                )
            })
            .transpose()?;
        let value = conversion::explanation(&selected, explanation);
        preflight(&value, maximum, deadline)?;
        Ok((value, lease))
    });
    let (value, lease) = tokio::time::timeout_at(deadline.into(), read)
        .await
        .map_err(|_| Status::deadline_exceeded("capability-inspection-deadline"))?
        .map_err(validation::platform)?;
    finish(value, lease, maximum, deadline)
}

fn preflight(
    value: &impl Message,
    maximum: usize,
    deadline: std::time::Instant,
) -> Result<(), latent_core::PlatformError> {
    if std::time::Instant::now() >= deadline {
        return Err(latent_core::PlatformError {
            code: latent_core::PlatformErrorCode::DeadlineExceeded,
            message: "capability-inspection-deadline".into(),
            retryable: false,
            details: Vec::new(),
        });
    }
    if value.encoded_len() > maximum {
        return Err(validation::too_large());
    }
    Ok(())
}

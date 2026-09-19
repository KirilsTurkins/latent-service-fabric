use super::super::{proto, ManagementOperation, ManagementServiceAdapter, RequestBudget};
use super::{conversion, validation};
use latent_core::{BoxFuture, TenantId};
use latent_policy::capability as domain;
use std::time::Instant;
use tonic::{Request, Response, Status};

async fn run<T: Send + 'static>(
    future: BoxFuture<'static, Result<T, latent_core::PlatformError>>,
    deadline: Instant,
) -> Result<T, Status> {
    tokio::time::timeout_at(deadline.into(), future)
        .await
        .map_err(|_| Status::deadline_exceeded("capability-policy-deadline"))?
        .map_err(validation::platform)
}
pub(super) async fn get(
    adapter: &ManagementServiceAdapter,
    mut request: Request<proto::GetPolicyRequest>,
) -> Result<Response<proto::GetPolicyResponse>, Status> {
    let deadline = validation::deadline(&request);
    let principal = adapter.authenticate(&mut request, ManagementOperation::Tenant)?;
    let tenant = validation::identity(&principal)?.to_owned();
    let request = request.into_inner();
    let mut budget = RequestBudget::new::<proto::GetPolicyRequest>(&adapter.limits)?;
    validation::id(&request.id, &mut budget)?;
    let kind = validation::kind(request.record_kind)?;
    validation::encoded(&request, &adapter.limits)?;
    let maximum = adapter
        .limits
        .max_response_bytes
        .min(super::MAX_RESPONSE_BYTES);
    let permit = adapter
        .policy_control()?
        .reserve()
        .map_err(validation::platform)?;
    let read = run(
        permit.run(move |store| store.get(&tenant, kind, &request.id, maximum, deadline)),
        deadline,
    )
    .await?;
    let (value, lease) = read.into_parts();
    conversion::finish(
        proto::GetPolicyResponse {
            policy: value.map(conversion::record),
        },
        lease,
        maximum,
        deadline,
    )
}
pub(super) async fn outcome(
    adapter: &ManagementServiceAdapter,
    mut request: Request<proto::GetPolicyOperationRequest>,
) -> Result<Response<proto::GetPolicyOperationResponse>, Status> {
    let deadline = validation::deadline(&request);
    let principal = adapter.authenticate(&mut request, ManagementOperation::Tenant)?;
    let tenant = validation::identity(&principal)?.to_owned();
    let request = request.into_inner();
    let mut budget = RequestBudget::new::<proto::GetPolicyOperationRequest>(&adapter.limits)?;
    validation::id(&request.operation_id, &mut budget)?;
    validation::encoded(&request, &adapter.limits)?;
    let permit = adapter
        .policy_control()?
        .reserve()
        .map_err(validation::platform)?;
    let read = run(
        permit.run(move |store| store.outcome(&tenant, &request.operation_id, deadline)),
        deadline,
    )
    .await?;
    let (value, lease) = read.into_parts();
    conversion::finish(
        proto::GetPolicyOperationResponse {
            receipt: value.as_ref().map(conversion::operation),
        },
        lease,
        adapter.limits.max_response_bytes,
        deadline,
    )
}
pub(super) async fn list(
    adapter: &ManagementServiceAdapter,
    mut request: Request<proto::ListPoliciesRequest>,
) -> Result<Response<proto::ListPoliciesResponse>, Status> {
    let deadline = validation::deadline(&request);
    let principal = adapter.authenticate(&mut request, ManagementOperation::Tenant)?;
    let tenant = validation::identity(&principal)?.to_owned();
    let request = request.into_inner();
    let mut budget = RequestBudget::new::<proto::ListPoliciesRequest>(&adapter.limits)?;
    let kind = validation::kind(request.record_kind)?;
    let page = request.page.as_ref().ok_or_else(validation::invalid)?;
    budget.optional_string(page.page_token.as_ref(), 117)?;
    let count = usize::try_from(page.page_size).map_err(|_| validation::invalid())?;
    let owner = adapter.policy_control()?;
    if count == 0
        || count
            > adapter.limits.max_page_size.min(
                u32::try_from(owner.store().limits().maximum_page_records)
                    .map_err(|_| validation::invalid())?,
            ) as usize
    {
        return Err(validation::invalid());
    }
    validation::encoded(&request, &adapter.limits)?;
    let maximum = adapter
        .limits
        .max_response_bytes
        .min(super::MAX_RESPONSE_BYTES);
    let permit = owner.reserve().map_err(validation::platform)?;
    let token = page.page_token.clone();
    let read = run(
        permit.run(move |store| {
            store.list(&domain::PolicyPageRequest {
                tenant: &tenant,
                kind,
                cursor: token.as_deref(),
                limit: count,
                maximum_bytes: maximum,
                deadline,
            })
        }),
        deadline,
    )
    .await?;
    let (value, lease) = read.into_parts();
    conversion::finish(
        proto::ListPoliciesResponse {
            policies: value.records.into_iter().map(conversion::record).collect(),
            catalog_generation: value.generation,
            page: Some(proto::PageResponse {
                next_page_token: value.next_cursor,
            }),
        },
        lease,
        maximum,
        deadline,
    )
}
pub(super) async fn explain(
    adapter: &ManagementServiceAdapter,
    mut request: Request<proto::EvaluatePolicyRequest>,
) -> Result<Response<proto::EvaluatePolicyResponse>, Status> {
    let deadline = validation::deadline(&request);
    let principal = adapter.authenticate(&mut request, ManagementOperation::Tenant)?;
    let tenant = TenantId(validation::identity(&principal)?.to_owned());
    let request = request.into_inner();
    let mut budget = RequestBudget::new::<proto::EvaluatePolicyRequest>(&adapter.limits)?;
    for id in [
        &request.policy_id,
        &request.service,
        &request.publication_id,
        &request.capability,
        &request.operation,
        &request.provider_binding_id,
    ] {
        validation::id(id, &mut budget)?;
    }
    if !request.action.is_empty()
        || !request.subject.is_empty()
        || !request.resource.is_empty()
        || !request.attributes.is_empty()
    {
        return Err(validation::invalid());
    }
    budget.sequence(&request.additional_policy_ids, 7)?;
    for id in &request.additional_policy_ids {
        validation::id(id, &mut budget)?;
    }
    budget.string(&request.resource_document, 4096)?;
    validation::encoded(&request, &adapter.limits)?;
    let permit = adapter
        .policy_control()?
        .reserve()
        .map_err(validation::platform)?;
    let resource = super::super::parse_inspection_resource(request.resource_document.as_bytes())
        .map_err(validation::platform)?;
    let read = run(
        permit.run(move |store| {
            let mut policies = vec![request.policy_id];
            policies.extend(request.additional_policy_ids);
            let snapshot =
                store.snapshot(&tenant, &policies, &request.provider_binding_id, deadline)?;
            Ok(snapshot.into_explanation(&domain::EvaluationInput {
                principal: &principal,
                service: &request.service,
                publication: &request.publication_id,
                capability: &request.capability,
                operation: &request.operation,
                resource: resource.target(),
            }))
        }),
        deadline,
    )
    .await?;
    let (explanation, lease) = read.into_parts();
    let (decision, code) = match explanation {
        domain::Explanation::Allow => ("allow", "policy-rules-match"),
        domain::Explanation::Deny => ("deny", "policy-rules-deny"),
        domain::Explanation::Indeterminate => ("indeterminate", "policy-authority-unavailable"),
    };
    conversion::finish(
        proto::EvaluatePolicyResponse {
            decision: decision.into(),
            reasons: vec![proto::PolicyReason {
                code: code.into(),
                message: "Read-only policy observation; not execution permission".into(),
                attributes: std::collections::HashMap::new(),
            }],
            obligations: std::collections::HashMap::new(),
            policy_version: domain::LANGUAGE.into(),
        },
        lease,
        adapter.limits.max_response_bytes,
        deadline,
    )
}

use super::super::{control_audit, errors::platform_status, RequestBudget};
use super::{
    conversion, enums, proto, response, validation, ManagementOperation, ManagementServiceAdapter,
};
use latent_control_store::rollouts as domain;
use latent_core::ServiceId;
use tonic::{Request, Response, Status};

pub(super) async fn get(
    adapter: &ManagementServiceAdapter,
    mut request: Request<proto::GetRolloutRequest>,
) -> Result<Response<proto::GetRolloutResponse>, Status> {
    let deadline = validation::deadline(&request);
    let principal = adapter.authenticate(&mut request, ManagementOperation::Tenant)?;
    let tenant = validation::tenant(&principal)?;
    let limits = validation::limits(&adapter.limits, true);
    let mut budget = RequestBudget::new::<proto::GetRolloutRequest>(&limits)?;
    validation::id(
        &request.get_ref().id,
        &mut budget,
        limits.max_id_bytes.min(128),
    )?;
    validation::encoded(request.get_ref(), &limits)?;
    let handle = adapter.rollout_handle()?;
    validation::completed(deadline)?;
    let id = domain::RolloutId(request.into_inner().id);
    let result = handle
        .get(tenant.clone(), id.clone(), deadline)
        .map_err(|error| platform_status(error, &limits))?
        .wait()
        .await
        .map_err(|failure| {
            control_audit::status(platform_status(failure.error, &limits), failure.audit_ack)
        })?;
    if result
        .value()
        .as_ref()
        .is_some_and(|value| value.tenant != tenant || value.id != id)
    {
        return Err(Status::internal("rollout response scope mismatch"));
    }
    let (value, lease) = result.into_parts();
    let output = proto::GetRolloutResponse {
        status: value.map(conversion::status),
    };
    response::finish(output, lease, &limits, deadline)
}

pub(super) async fn list(
    adapter: &ManagementServiceAdapter,
    mut request: Request<proto::ListRolloutsRequest>,
) -> Result<Response<proto::ListRolloutsResponse>, Status> {
    let deadline = validation::deadline(&request);
    let principal = adapter.authenticate(&mut request, ManagementOperation::Tenant)?;
    let tenant = validation::tenant(&principal)?;
    let limits = validation::limits(&adapter.limits, true);
    let mut budget = RequestBudget::new::<proto::ListRolloutsRequest>(&limits)?;
    if let Some(service) = &request.get_ref().service {
        validation::id(service, &mut budget, limits.max_id_bytes.min(256))?;
    }
    let state = request
        .get_ref()
        .state
        .map(enums::state_input)
        .transpose()?;
    let count = budget.page(request.get_ref().page.as_ref(), &limits)?;
    validation::encoded(request.get_ref(), &limits)?;
    let handle = adapter.rollout_handle()?;
    validation::completed(deadline)?;
    // The owner charges the complete domain/wire graph; keep bounded space for
    // the protobuf envelope and next cursor outside the storage page allowance.
    let maximum_bytes = limits
        .max_response_bytes
        .checked_sub(1024)
        .filter(|n| *n >= 4096)
        .ok_or_else(super::super::bounds::exhausted)?;
    let value = request.into_inner();
    let result = handle
        .list(
            domain::RolloutPageRequest {
                tenant: tenant.clone(),
                service: value.service.map(ServiceId),
                state,
                cursor: value.page.and_then(|page| page.page_token),
                limit: count as usize,
                maximum_bytes,
            },
            deadline,
        )
        .map_err(|error| platform_status(error, &limits))?
        .wait()
        .await
        .map_err(|failure| {
            control_audit::status(platform_status(failure.error, &limits), failure.audit_ack)
        })?;
    if result
        .value()
        .rollouts
        .iter()
        .any(|value| value.tenant != tenant)
    {
        return Err(Status::internal("rollout response scope mismatch"));
    }
    let (value, lease) = result.into_parts();
    let output = proto::ListRolloutsResponse {
        rollouts: value.rollouts.into_iter().map(conversion::status).collect(),
        page: Some(proto::PageResponse {
            next_page_token: value.next_cursor,
        }),
        state_version: value.state_version,
    };
    response::finish(output, lease, &limits, deadline)
}

pub(super) async fn operation(
    adapter: &ManagementServiceAdapter,
    mut request: Request<proto::GetRolloutOperationRequest>,
) -> Result<Response<proto::GetRolloutOperationResponse>, Status> {
    let deadline = validation::deadline(&request);
    let principal = adapter.authenticate(&mut request, ManagementOperation::Tenant)?;
    let tenant = validation::tenant(&principal)?;
    let limits = validation::limits(&adapter.limits, true);
    let mut budget = RequestBudget::new::<proto::GetRolloutOperationRequest>(&limits)?;
    validation::id(
        &request.get_ref().id,
        &mut budget,
        limits.max_id_bytes.min(128),
    )?;
    validation::id(
        &request.get_ref().operation_id,
        &mut budget,
        limits.max_id_bytes.min(128),
    )?;
    validation::encoded(request.get_ref(), &limits)?;
    let handle = adapter.rollout_handle()?;
    validation::completed(deadline)?;
    let value = request.into_inner();
    let result = handle
        .operation(
            tenant.clone(),
            domain::RolloutId(value.id.clone()),
            value.operation_id.clone(),
            deadline,
        )
        .map_err(|error| platform_status(error, &limits))?
        .wait()
        .await
        .map_err(|failure| {
            control_audit::status(platform_status(failure.error, &limits), failure.audit_ack)
        })?;
    if let domain::RolloutOperationLookup::Found(receipt) = result.value() {
        response::scope(receipt, &tenant)?;
        if receipt.rollout_id.0 != value.id || receipt.operation_id != value.operation_id {
            return Err(Status::internal("rollout operation mismatch"));
        }
    }
    let (lookup, lease) = result.into_parts();
    let (disposition, receipt) = match lookup {
        domain::RolloutOperationLookup::Found(receipt) => (
            proto::RolloutOperationLookupDisposition::Found,
            Some(conversion::receipt(receipt)),
        ),
        domain::RolloutOperationLookup::Unknown => {
            (proto::RolloutOperationLookupDisposition::Unknown, None)
        }
        domain::RolloutOperationLookup::Uncertain => {
            (proto::RolloutOperationLookupDisposition::Uncertain, None)
        }
    };
    response::finish(
        proto::GetRolloutOperationResponse {
            disposition: disposition as i32,
            receipt,
        },
        lease,
        &limits,
        deadline,
    )
}

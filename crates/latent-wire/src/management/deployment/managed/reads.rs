use super::super::super::{
    errors::platform_status, proto, ManagementServiceAdapter, RequestBudget,
};
use super::{response, validation};
use latent_control_store::deployment_operations::DeploymentOperationLookup;
use latent_core::{DeploymentId, InvocationPrincipal, TenantId};
use std::time::Instant;
use tonic::{Response, Status};

pub(in crate::management::deployment) async fn get(
    adapter: &ManagementServiceAdapter,
    tenant: TenantId,
    id: DeploymentId,
    deadline: Instant,
) -> Result<Response<proto::GetDeploymentResponse>, Status> {
    validation::completed(deadline)?;
    let store = adapter.services.deployments.as_ref();
    let result =
        tokio::time::timeout_at(deadline.into(), store.get_operation_snapshot(&tenant, &id))
            .await
            .map_err(|_| validation::expired())?;
    let result = result.map_err(|error| platform_status(error, &adapter.limits))?;
    if result
        .value()
        .deployment
        .as_ref()
        .is_some_and(|value| value.manifest.id != id)
    {
        return Err(Status::internal("deployment snapshot identity changed"));
    }
    let mut output =
        super::super::response::get(result.value().deployment.as_ref(), &tenant, &adapter.limits)?;
    output.state_version = Some(result.value().state_version);
    output.route_generation = Some(result.value().route_generation.0);
    output.durability = Some(response::durability(result.value().confirmed));
    let (value, lease) = result.into_parts();
    drop(value);
    response::finish(output, lease, &adapter.limits, deadline)
}

pub(in crate::management::deployment) async fn lookup(
    adapter: &ManagementServiceAdapter,
    value: proto::GetDeploymentOperationRequest,
    principal: InvocationPrincipal,
    deadline: Instant,
) -> Result<Response<proto::GetDeploymentOperationResponse>, Status> {
    let tenant = principal.tenant.expect("authenticated tenant");
    let mut budget = RequestBudget::new::<proto::GetDeploymentOperationRequest>(&adapter.limits)?;
    super::super::validation::id(&value.operation_id, &mut budget, 128)?;
    adapter.check_encoded(&value)?;
    validation::completed(deadline)?;
    let result = tokio::time::timeout_at(
        deadline.into(),
        adapter
            .services
            .deployments
            .get_operation(&tenant, &value.operation_id),
    )
    .await
    .map_err(|_| validation::expired())?
    .map_err(|error| platform_status(error, &adapter.limits))?;
    if let DeploymentOperationLookup::Found(receipt) = result.value() {
        let mut budget =
            RequestBudget::for_response::<proto::GetDeploymentOperationResponse>(&adapter.limits)?;
        response::charge(receipt, &tenant, &mut budget, &adapter.limits)?;
        if receipt.operation_id != value.operation_id {
            return Err(Status::internal("deployment operation identity changed"));
        }
    }
    let (value, lease) = result.into_parts();
    let output = match value {
        DeploymentOperationLookup::Found(receipt) => proto::GetDeploymentOperationResponse {
            disposition: proto::DeploymentOperationLookupDisposition::Found as i32,
            receipt: Some(response::receipt(receipt)),
            durability: Some(response::durability(true)),
            retained_floor: 0,
            high_watermark: 0,
        },
        DeploymentOperationLookup::Unknown {
            retained_floor,
            high_watermark,
        } => proto::GetDeploymentOperationResponse {
            disposition: proto::DeploymentOperationLookupDisposition::Unknown as i32,
            receipt: None,
            durability: None,
            retained_floor,
            high_watermark,
        },
        DeploymentOperationLookup::Uncertain => proto::GetDeploymentOperationResponse {
            disposition: proto::DeploymentOperationLookupDisposition::Uncertain as i32,
            receipt: None,
            durability: Some(response::durability(false)),
            retained_floor: 0,
            high_watermark: 0,
        },
    };
    response::finish(output, lease, &adapter.limits, deadline)
}

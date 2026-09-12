use latent_control_store::{DeploymentPage, VersionedDeployment};
use latent_core::TenantId;
use tonic::Status;

use super::super::{proto, ManagementLimits, RequestBudget};
use super::{deployment_to_proto, validation};

pub(super) fn apply(
    deployment: &VersionedDeployment,
    tenant: &TenantId,
    limits: &ManagementLimits,
) -> Result<proto::ApplyDeploymentResponse, Status> {
    let mut budget = RequestBudget::for_response::<proto::ApplyDeploymentResponse>(limits)?;
    validation::domain(deployment, tenant, &mut budget, limits)?;
    Ok(proto::ApplyDeploymentResponse {
        deployment: Some(convert(deployment)?),
        warnings: Vec::new(),
        audit_ack: None,
    })
}

pub(super) fn get(
    deployment: Option<&VersionedDeployment>,
    tenant: &TenantId,
    limits: &ManagementLimits,
) -> Result<proto::GetDeploymentResponse, Status> {
    let mut budget = RequestBudget::for_response::<proto::GetDeploymentResponse>(limits)?;
    let deployment = if let Some(deployment) = deployment {
        validation::domain(deployment, tenant, &mut budget, limits)?;
        Some(convert(deployment)?)
    } else {
        None
    };
    Ok(proto::GetDeploymentResponse { deployment })
}

pub(super) fn page(
    page: &DeploymentPage,
    tenant: &TenantId,
    page_size: u32,
    limits: &ManagementLimits,
) -> Result<proto::ListDeploymentsResponse, Status> {
    let mut budget = RequestBudget::for_response::<proto::ListDeploymentsResponse>(limits)?;
    budget.sequence(&page.deployments, page_size as usize)?;
    budget.allocation::<proto::Deployment>(page.deployments.len())?;
    budget.optional_string(page.next_page_token.as_ref(), limits.max_page_token_bytes)?;
    if let Some(token) = &page.next_page_token {
        super::super::identifier(token, limits.max_page_token_bytes)?;
    }
    // Validate the entire borrowed page before allocating response records.
    for deployment in &page.deployments {
        validation::domain(deployment, tenant, &mut budget, limits)?;
    }
    Ok(proto::ListDeploymentsResponse {
        deployments: page
            .deployments
            .iter()
            .map(convert)
            .collect::<Result<_, _>>()?,
        page: Some(proto::PageResponse {
            next_page_token: page.next_page_token.clone(),
        }),
    })
}

fn convert(deployment: &VersionedDeployment) -> Result<proto::Deployment, Status> {
    deployment_to_proto(deployment)
        .map_err(|_| Status::internal("deployment repository returned an invalid representation"))
}

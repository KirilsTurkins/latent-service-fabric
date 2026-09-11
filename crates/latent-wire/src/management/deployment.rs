mod budget;
mod conversion;
mod response;
mod validation;

#[cfg(test)]
mod tests;

use latent_control_store::{DeploymentPageRequest, VersionedDeployment};
use latent_core::{DeploymentId, ServiceId};
use latent_manifest::{ManifestValidator, Phase1ManifestValidator};
use tonic::{Request, Response, Status};

use super::errors::platform_status;
use super::{proto, ManagementOperation, ManagementServiceAdapter, RequestBudget};

pub use budget::{control_budget_from_proto, control_budget_to_proto};
pub use conversion::{deployment_from_proto, deployment_manifest_from_proto, deployment_to_proto};

#[tonic::async_trait]
impl proto::deployment_service_server::DeploymentService for ManagementServiceAdapter {
    async fn apply_deployment(
        &self,
        mut request: Request<proto::ApplyDeploymentRequest>,
    ) -> Result<Response<proto::ApplyDeploymentResponse>, Status> {
        let tenant = self
            .authenticate(&mut request, ManagementOperation::Tenant)?
            .tenant
            .expect("authenticated tenant");
        let mut budget = RequestBudget::new::<proto::ApplyDeploymentRequest>(&self.limits)?;
        let deployment = request
            .get_ref()
            .deployment
            .as_ref()
            .ok_or_else(|| Status::invalid_argument("deployment is required"))?;
        validation::wire(deployment, &mut budget, &self.limits)?;
        self.check_encoded(request.get_ref())?;
        if deployment
            .metadata
            .as_ref()
            .and_then(|metadata| metadata.tenant.as_deref())
            != Some(tenant.0.as_str())
        {
            return Err(Status::permission_denied(
                "deployment tenant does not match authenticated scope",
            ));
        }
        let request = request.into_inner();
        let manifest =
            deployment_manifest_from_proto(request.deployment.expect("validated deployment"))
                .map_err(|_| Status::invalid_argument("invalid deployment representation"))?;
        Phase1ManifestValidator
            .validate_deployment(&manifest)
            .map_err(|_| Status::invalid_argument("invalid Phase 1 deployment"))?;
        // Reject an unreturnable ordinary receipt before a durable mutation. The
        // catalog normalizes existing fields and assigns at most a u64 stamp.
        let desired = VersionedDeployment {
            manifest,
            generation: u64::MAX,
        };
        let preflight = response::apply(&desired, &tenant, &self.limits)?;
        self.response(preflight)?;
        let receipt = self
            .services
            .deployments
            .apply_versioned(&tenant, desired.manifest, request.expected_generation)
            .await
            .map_err(|error| platform_status(error, &self.limits))?;
        self.response(response::apply(&receipt.deployment, &tenant, &self.limits)?)
    }

    async fn get_deployment(
        &self,
        mut request: Request<proto::GetDeploymentRequest>,
    ) -> Result<Response<proto::GetDeploymentResponse>, Status> {
        let tenant = self
            .authenticate(&mut request, ManagementOperation::Tenant)?
            .tenant
            .expect("authenticated tenant");
        let mut budget = RequestBudget::new::<proto::GetDeploymentRequest>(&self.limits)?;
        validation::id(&request.get_ref().id, &mut budget, self.limits.max_id_bytes)?;
        self.check_encoded(request.get_ref())?;
        let id = DeploymentId(request.into_inner().id);
        let deployment = self
            .services
            .deployments
            .get_versioned(&tenant, &id)
            .await
            .map_err(|error| platform_status(error, &self.limits))?;
        self.response(response::get(deployment.as_ref(), &tenant, &self.limits)?)
    }

    async fn list_deployments(
        &self,
        mut request: Request<proto::ListDeploymentsRequest>,
    ) -> Result<Response<proto::ListDeploymentsResponse>, Status> {
        let tenant = self
            .authenticate(&mut request, ManagementOperation::Tenant)?
            .tenant
            .expect("authenticated tenant");
        let mut budget = RequestBudget::new::<proto::ListDeploymentsRequest>(&self.limits)?;
        if let Some(service) = &request.get_ref().service {
            validation::id(service, &mut budget, self.limits.max_id_bytes)?;
        }
        let page_size = budget.page(request.get_ref().page.as_ref(), &self.limits)?;
        self.check_encoded(request.get_ref())?;
        let request = request.into_inner();
        let page = self
            .services
            .deployments
            .list_page(DeploymentPageRequest {
                tenant: tenant.clone(),
                service: request.service.map(ServiceId),
                page_size,
                page_token: request.page.and_then(|page| page.page_token),
            })
            .await
            .map_err(|error| platform_status(error, &self.limits))?;
        self.response(response::page(&page, &tenant, page_size, &self.limits)?)
    }

    async fn delete_deployment(
        &self,
        mut request: Request<proto::DeleteDeploymentRequest>,
    ) -> Result<Response<proto::Empty>, Status> {
        let tenant = self
            .authenticate(&mut request, ManagementOperation::Tenant)?
            .tenant
            .expect("authenticated tenant");
        let mut budget = RequestBudget::new::<proto::DeleteDeploymentRequest>(&self.limits)?;
        validation::id(&request.get_ref().id, &mut budget, self.limits.max_id_bytes)?;
        self.check_encoded(request.get_ref())?;
        let request = request.into_inner();
        self.services
            .deployments
            .delete_versioned(
                &tenant,
                &DeploymentId(request.id),
                request.expected_generation,
            )
            .await
            .map_err(|error| platform_status(error, &self.limits))?;
        self.response(proto::Empty {})
    }

    type WatchDeploymentStream = tonic::codegen::BoxStream<proto::DeploymentEvent>;

    async fn watch_deployment(
        &self,
        _request: Request<proto::WatchDeploymentRequest>,
    ) -> Result<Response<Self::WatchDeploymentStream>, Status> {
        Err(Status::unimplemented(
            "deployment watches require a later phase",
        ))
    }
}

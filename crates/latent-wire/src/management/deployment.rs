mod audit;
mod budget;
mod conversion;
mod managed;
mod response;
pub(super) mod validation;

#[cfg(test)]
mod tests;

use latent_control_store::{DeploymentPageRequest, VersionedDeployment};
use latent_core::{DeploymentId, ServiceId};
use latent_manifest::{ManifestValidator, Phase1ManifestValidator};
use tonic::{Request, Response, Status};

use super::errors::platform_status;
use super::{control_audit, proto, ManagementOperation, ManagementServiceAdapter, RequestBudget};

pub use budget::{control_budget_from_proto, control_budget_to_proto};
pub use conversion::{deployment_from_proto, deployment_manifest_from_proto, deployment_to_proto};
pub use managed::DeploymentResponseService;

#[tonic::async_trait]
impl proto::deployment_service_server::DeploymentService for ManagementServiceAdapter {
    async fn apply_deployment(
        &self,
        mut request: Request<proto::ApplyDeploymentRequest>,
    ) -> Result<Response<proto::ApplyDeploymentResponse>, Status> {
        let deadline = managed::deadline(&request);
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        if request.get_ref().operation.is_some() {
            return managed::apply(self, request.into_inner(), principal, deadline).await;
        }
        let tenant = principal.tenant.clone().expect("authenticated tenant");
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
        let mut manifest =
            deployment_manifest_from_proto(request.deployment.expect("validated deployment"))
                .map_err(|_| Status::invalid_argument("invalid deployment representation"))?;
        Phase1ManifestValidator
            .validate_deployment(&manifest)
            .map_err(|_| Status::invalid_argument("invalid Phase 1 deployment"))?;
        // Use the catalog codec's exact normalization before binding an audit
        // attempt. This preserves accepted uppercase digests and unordered sets.
        manifest.normalize_storage_fields();
        // Reject an unreturnable ordinary receipt before a durable mutation. The
        // catalog normalizes existing fields and assigns at most a u64 stamp.
        let desired = VersionedDeployment {
            manifest,
            generation: u64::MAX,
        };
        let preflight = audit::response(
            &desired,
            &tenant,
            &self.limits,
            self.services.audit.is_some(),
        )?;
        self.response(preflight)?;
        let audit = audit::DeploymentAudit::apply(
            self.services.audit.as_ref(),
            &principal,
            &desired.manifest,
            request.expected_generation,
            &self.limits,
        )
        .await?;
        let result = self
            .services
            .deployments
            .apply_versioned(&tenant, desired.manifest, request.expected_generation)
            .await;
        let output = result
            .as_ref()
            .ok()
            .map(|receipt| {
                let response = audit::response(
                    &receipt.deployment,
                    &tenant,
                    &self.limits,
                    self.services.audit.is_some(),
                )?;
                if !audit.matches(&receipt.deployment, receipt.catalog_generation) {
                    return Err(Status::internal(
                        "deployment receipt changed the audited request",
                    ));
                }
                Ok(response)
            })
            .transpose();
        let ack = audit
            .finish(
                result
                    .as_ref()
                    .ok()
                    .filter(|_| output.is_ok())
                    .map(|receipt| (&receipt.deployment, receipt.catalog_generation)),
            )
            .await;
        result.map_err(|error| control_audit::status(platform_status(error, &self.limits), ack))?;
        let mut output = output
            .map_err(|error| control_audit::status(error, ack))?
            .expect("successful deployment response");
        output.audit_ack = self
            .services
            .audit
            .as_ref()
            .map(|_| control_audit::wire(ack));
        self.response(output)
    }

    async fn get_deployment(
        &self,
        mut request: Request<proto::GetDeploymentRequest>,
    ) -> Result<Response<proto::GetDeploymentResponse>, Status> {
        let deadline = managed::deadline(&request);
        let tenant = self
            .authenticate(&mut request, ManagementOperation::Tenant)?
            .tenant
            .expect("authenticated tenant");
        let mut budget = RequestBudget::new::<proto::GetDeploymentRequest>(&self.limits)?;
        validation::id(&request.get_ref().id, &mut budget, self.limits.max_id_bytes)?;
        self.check_encoded(request.get_ref())?;
        let request = request.into_inner();
        let id = DeploymentId(request.id);
        if request.include_operation_snapshot {
            managed::get(self, tenant, id, deadline).await
        } else {
            let value = self
                .services
                .deployments
                .get_versioned(&tenant, &id)
                .await
                .map_err(|error| platform_status(error, &self.limits))?;
            self.response(response::get(value.as_ref(), &tenant, &self.limits)?)
        }
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
        let deadline = managed::deadline(&request);
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        if request.get_ref().operation.is_some() {
            return managed::delete(self, request.into_inner(), principal, deadline).await;
        }
        let tenant = principal.tenant.clone().expect("authenticated tenant");
        let mut budget = RequestBudget::new::<proto::DeleteDeploymentRequest>(&self.limits)?;
        validation::id(&request.get_ref().id, &mut budget, self.limits.max_id_bytes)?;
        self.check_encoded(request.get_ref())?;
        let request = request.into_inner();
        let id = DeploymentId(request.id);
        let mut response_budget = RequestBudget::for_response::<proto::Empty>(&self.limits)?;
        if self.services.audit.is_some() {
            control_audit::charge(&mut response_budget)?;
        }
        self.response(proto::Empty {})?;
        let audit = audit::DeploymentAudit::delete(
            self.services.audit.as_ref(),
            &principal,
            &id,
            request.expected_generation,
            &self.limits,
        )
        .await?;
        let result = self
            .services
            .deployments
            .delete_versioned(&tenant, &id, request.expected_generation)
            .await;
        let valid = result
            .as_ref()
            .ok()
            .map(|receipt| {
                let mut budget = RequestBudget::for_response::<proto::Empty>(&self.limits)?;
                validation::domain(&receipt.deleted, &tenant, &mut budget, &self.limits)?;
                if !audit.matches(&receipt.deleted, receipt.catalog_generation) {
                    return Err(Status::internal(
                        "deployment deletion receipt changed the audited request",
                    ));
                }
                Ok(())
            })
            .transpose();
        let ack = audit
            .finish(
                result
                    .as_ref()
                    .ok()
                    .filter(|_| valid.is_ok())
                    .map(|receipt| (&receipt.deleted, receipt.catalog_generation)),
            )
            .await;
        result.map_err(|error| control_audit::status(platform_status(error, &self.limits), ack))?;
        valid.map_err(|error| control_audit::status(error, ack))?;
        Ok(control_audit::response(
            self.response(proto::Empty {})?,
            ack,
        ))
    }

    async fn get_deployment_operation(
        &self,
        mut request: Request<proto::GetDeploymentOperationRequest>,
    ) -> Result<Response<proto::GetDeploymentOperationResponse>, Status> {
        let deadline = managed::deadline(&request);
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        managed::lookup(self, request.into_inner(), principal, deadline).await
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

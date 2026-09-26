mod conversion;
mod mutation;
mod preparation;
#[cfg(test)]
mod tests;
mod validation;

use super::super::{
    errors::platform_status, proto, ManagementOperation, ManagementServiceAdapter, RequestBudget,
};
use latent_artifacts::{ArtifactRepository, DirectoryArtifactRepository, LifecycleScope};
use latent_core::{PlatformError, PlatformErrorCode};
use std::sync::Arc;
use tonic::{Request, Response, Status};

pub const MAX_WEB_PREPARATION_WAIT_MILLIS: u64 = 300_000;
pub const MAX_WEB_MUTATION_WAIT_MILLIS: u64 = 30_000;
pub const WEB_PREPARATION_RPC_PATH: &str =
    "/latent.control.v1.ReleaseService/PrepareWebPublication";
pub const WEB_PUBLICATION_RPC_PATH: &str = "/latent.control.v1.ReleaseService/PublishWebPackage";
pub const WEB_EVIDENCE_RPC_PATH: &str = "/latent.control.v1.ReleaseService/RenewWebEvidence";

impl ManagementServiceAdapter {
    pub fn with_web_catalog(
        mut self,
        catalog: Arc<DirectoryArtifactRepository>,
    ) -> Result<Self, PlatformError> {
        let artifacts: Arc<dyn ArtifactRepository> = catalog.clone();
        if self.web.is_some() || !Arc::ptr_eq(&artifacts, &self.services.artifacts) {
            return Err(PlatformError {
                code: PlatformErrorCode::InvalidArgument,
                message: "web-management-catalog-owner-mismatch".into(),
                retryable: false,
                details: Vec::new(),
            });
        }
        self.web = Some(catalog);
        Ok(self)
    }

    fn web_catalog(&self) -> Result<&DirectoryArtifactRepository, Status> {
        self.web
            .as_deref()
            .ok_or_else(|| Status::unimplemented("web publication management is not configured"))
    }

    pub(super) fn web_get(
        &self,
        mut request: Request<proto::GetWebPublicationRequest>,
    ) -> Result<Response<proto::GetWebPublicationResponse>, Status> {
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        let tenant = principal.tenant.expect("authenticated tenant");
        let mut budget = RequestBudget::new::<proto::GetWebPublicationRequest>(&self.limits)?;
        let reference = validation::publication(
            request.get_ref().publication.as_ref(),
            &tenant,
            &mut budget,
            &self.limits,
        )?;
        self.check_encoded(request.get_ref())?;
        let status = self
            .web_catalog()?
            .web_publication_status(&reference)
            .map_err(|failure| platform_status(failure, &self.limits))?;
        self.response(conversion::status(&status, &tenant, &self.limits)?)
    }

    pub(super) fn web_operation(
        &self,
        mut request: Request<proto::GetWebOperationRequest>,
    ) -> Result<Response<proto::GetWebOperationResponse>, Status> {
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        let tenant = principal.tenant.expect("authenticated tenant");
        let mut budget = RequestBudget::new::<proto::GetWebOperationRequest>(&self.limits)?;
        validation::operation_id(&request.get_ref().operation_id, &mut budget, &self.limits)?;
        self.check_encoded(request.get_ref())?;
        let operation = match self.web_catalog()?.web_operation_status(
            &LifecycleScope::Tenant(tenant.clone()),
            &request.get_ref().operation_id,
        ) {
            Ok(operation) => operation,
            Err(failure) if failure.code == PlatformErrorCode::Unavailable => {
                return self.response(proto::GetWebOperationResponse {
                    disposition: proto::ReleaseOperationLookupDisposition::Uncertain as i32,
                    operation: None,
                    tenant: tenant.0,
                });
            }
            Err(failure) => return Err(platform_status(failure, &self.limits)),
        };
        let mut response_budget =
            RequestBudget::for_response::<proto::GetWebOperationResponse>(&self.limits)?;
        response_budget.string(&tenant.0, self.limits.max_id_bytes)?;
        let operation = operation
            .as_ref()
            .map(|receipt| {
                conversion::receipt(receipt, true, &tenant, &mut response_budget, &self.limits)
            })
            .transpose()?;
        self.response(proto::GetWebOperationResponse {
            disposition: if operation.is_some() {
                proto::ReleaseOperationLookupDisposition::Found
            } else {
                proto::ReleaseOperationLookupDisposition::Unknown
            } as i32,
            operation,
            tenant: tenant.0,
        })
    }
}

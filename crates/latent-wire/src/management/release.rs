mod conversion;
mod lifecycle;
mod package;
#[cfg(test)]
mod package_tests;
mod publication;
#[cfg(test)]
mod tests;
mod validation;

use latent_artifacts::ArtifactCatalogPageRequest;
use latent_core::{ReleaseDigest, ServiceId};
use tonic::{Request, Response, Status};

use super::{
    errors::platform_status, proto, ManagementOperation, ManagementServiceAdapter, RequestBudget,
};

pub use conversion::{release_descriptor_from_proto, release_descriptor_to_proto};

#[tonic::async_trait]
impl proto::release_service_server::ReleaseService for ManagementServiceAdapter {
    async fn publish_release(
        &self,
        mut request: Request<proto::PublishReleaseRequest>,
    ) -> Result<Response<proto::PublishReleaseResponse>, Status> {
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        validation::publish(request.get_ref(), &self.limits)?;
        self.check_encoded(request.get_ref())?;
        self.publish_managed_release(principal, request.into_inner())
            .await
    }

    async fn get_release_lifecycle(
        &self,
        request: Request<proto::GetReleaseLifecycleRequest>,
    ) -> Result<Response<proto::GetReleaseLifecycleResponse>, Status> {
        self.lifecycle_status(request).await
    }
    async fn get_release_operation(
        &self,
        request: Request<proto::GetReleaseOperationRequest>,
    ) -> Result<Response<proto::GetReleaseOperationResponse>, Status> {
        self.lifecycle_operation(request).await
    }
    async fn change_release_lifecycle(
        &self,
        request: Request<proto::ChangeReleaseLifecycleRequest>,
    ) -> Result<Response<proto::ChangeReleaseLifecycleResponse>, Status> {
        self.lifecycle_change(request).await
    }
    async fn renew_release_evidence(
        &self,
        request: Request<proto::RenewReleaseEvidenceRequest>,
    ) -> Result<Response<proto::RenewReleaseEvidenceResponse>, Status> {
        self.lifecycle_renew(request).await
    }

    async fn get_release(
        &self,
        mut request: Request<proto::GetReleaseRequest>,
    ) -> Result<Response<proto::GetReleaseResponse>, Status> {
        let tenant = self
            .authenticate(&mut request, ManagementOperation::Tenant)?
            .tenant
            .expect("authenticated tenant");
        let mut budget = RequestBudget::new::<proto::GetReleaseRequest>(&self.limits)?;
        validation::digest(&request.get_ref().digest, &mut budget, &self.limits)?;
        self.check_encoded(request.get_ref())?;
        let digest = ReleaseDigest(request.into_inner().digest);
        let entry = self
            .services
            .artifacts
            .get_catalog_entry(&tenant, &digest)
            .await
            .map_err(|error| platform_status(error, &self.limits))?;
        let mut budget = RequestBudget::for_response::<proto::GetReleaseResponse>(&self.limits)?;
        let release = entry
            .map(|entry| {
                validation::entry(&entry, &tenant, &mut budget, &self.limits)?;
                if entry.descriptor.release_digest != digest {
                    return Err(Status::internal(
                        "artifact repository returned a different release",
                    ));
                }
                release_descriptor_to_proto(entry)
                    .map_err(|_| Status::internal("invalid release receipt"))
            })
            .transpose()?;
        self.response(proto::GetReleaseResponse { release })
    }

    async fn list_releases(
        &self,
        mut request: Request<proto::ListReleasesRequest>,
    ) -> Result<Response<proto::ListReleasesResponse>, Status> {
        let tenant = self
            .authenticate(&mut request, ManagementOperation::Tenant)?
            .tenant
            .expect("authenticated tenant");
        let mut budget = RequestBudget::new::<proto::ListReleasesRequest>(&self.limits)?;
        if let Some(service) = &request.get_ref().service {
            budget.string(service, self.limits.max_id_bytes)?;
            super::identifier(service, self.limits.max_id_bytes)?;
        }
        let page_size = budget.page(request.get_ref().page.as_ref(), &self.limits)?;
        self.check_encoded(request.get_ref())?;
        let request = request.into_inner();
        let query = ArtifactCatalogPageRequest {
            tenant: tenant.clone(),
            service: request.service.map(ServiceId),
            page_size,
            page_token: request.page.and_then(|page| page.page_token),
        };
        let page = self
            .services
            .artifacts
            .list_catalog_entries(&query)
            .await
            .map_err(|error| platform_status(error, &self.limits))?;
        let mut budget = RequestBudget::for_response::<proto::ListReleasesResponse>(&self.limits)?;
        budget.sequence(&page.entries, page_size as usize)?;
        // Conversion may allocate a differently sized wire DTO vector while the
        // source vector is still retained. Reserve both sets of slots up front.
        budget.allocation::<proto::ReleaseDescriptor>(page.entries.len())?;
        budget.optional_string(
            page.next_page_token.as_ref(),
            self.limits.max_page_token_bytes,
        )?;
        let mut previous = None;
        for entry in &page.entries {
            validation::entry(entry, &tenant, &mut budget, &self.limits)?;
            if query
                .service
                .as_ref()
                .is_some_and(|service| service != &entry.service)
                || previous.is_some_and(|digest| digest >= &entry.descriptor.release_digest)
            {
                return Err(Status::internal(
                    "artifact repository returned an invalid page",
                ));
            }
            previous = Some(&entry.descriptor.release_digest);
        }
        if page.entries.is_empty() && page.next_page_token.is_some() {
            return Err(Status::internal(
                "artifact repository returned a non-progressing page",
            ));
        }
        let mut releases = Vec::new();
        releases
            .try_reserve_exact(page.entries.len())
            .map_err(|_| super::bounds::exhausted())?;
        for entry in page.entries {
            releases.push(
                release_descriptor_to_proto(entry)
                    .map_err(|_| Status::internal("invalid release receipt"))?,
            );
        }
        self.response(proto::ListReleasesResponse {
            releases,
            page: Some(proto::PageResponse {
                next_page_token: page.next_page_token,
            }),
        })
    }
}

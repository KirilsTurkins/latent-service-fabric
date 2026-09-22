mod conversion;
mod lifecycle;
mod package;
#[cfg(test)]
mod package_tests;
mod publication;
mod selector;
#[cfg(test)]
mod tests;
mod validation;
mod web;

use latent_artifacts::{ArtifactCatalogPageRequest, LifecycleScope};
use latent_core::ServiceId;
use tonic::{Request, Response, Status};

use super::{
    errors::platform_status, proto, ManagementOperation, ManagementServiceAdapter, RequestBudget,
};

pub use conversion::{release_descriptor_from_proto, release_descriptor_to_proto};
pub use web::{
    MAX_WEB_MUTATION_WAIT_MILLIS, MAX_WEB_PREPARATION_WAIT_MILLIS, WEB_EVIDENCE_RPC_PATH,
    WEB_PREPARATION_RPC_PATH, WEB_PUBLICATION_RPC_PATH,
};

#[tonic::async_trait]
impl proto::release_service_server::ReleaseService for ManagementServiceAdapter {
    async fn prepare_web_publication(
        &self,
        request: Request<proto::PrepareWebPublicationRequest>,
    ) -> Result<Response<proto::PrepareWebPublicationResponse>, Status> {
        self.web_prepare(request).await
    }
    async fn publish_web_package(
        &self,
        request: Request<proto::PublishWebPackageRequest>,
    ) -> Result<Response<proto::PublishWebPackageResponse>, Status> {
        self.web_publish(request).await.map(|response| {
            response.map(|value| proto::PublishWebPackageResponse {
                operation: value.operation,
                audit_ack: value.audit_ack,
            })
        })
    }
    async fn get_web_publication(
        &self,
        request: Request<proto::GetWebPublicationRequest>,
    ) -> Result<Response<proto::GetWebPublicationResponse>, Status> {
        self.web_get(request)
    }
    async fn get_web_operation(
        &self,
        request: Request<proto::GetWebOperationRequest>,
    ) -> Result<Response<proto::GetWebOperationResponse>, Status> {
        self.web_operation(request)
    }
    async fn change_web_lifecycle(
        &self,
        request: Request<proto::ChangeWebLifecycleRequest>,
    ) -> Result<Response<proto::ChangeWebLifecycleResponse>, Status> {
        self.web_change(request).await.map(|response| {
            response.map(|value| proto::ChangeWebLifecycleResponse {
                operation: value.operation,
                audit_ack: value.audit_ack,
            })
        })
    }
    async fn renew_web_evidence(
        &self,
        request: Request<proto::RenewWebEvidenceRequest>,
    ) -> Result<Response<proto::RenewWebEvidenceResponse>, Status> {
        self.web_renew(request).await.map(|response| {
            response.map(|value| proto::RenewWebEvidenceResponse {
                operation: value.operation,
                audit_ack: value.audit_ack,
            })
        })
    }
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
        let selector = selector::request(
            request.get_ref().publication.as_ref(),
            &tenant,
            &mut budget,
            &self.limits,
        )?;
        self.check_encoded(request.get_ref())?;
        drop(request);
        let entry = self
            .services
            .artifacts
            .get_selected_catalog_entry(
                &LifecycleScope::Tenant(tenant.clone()),
                &latent_artifacts::PublicationSelector::Publication(selector.clone()),
            )
            .await
            .map_err(|error| platform_status(error, &self.limits))?;
        if entry.is_none() {
            return Err(Status::not_found("publication not found"));
        }
        let mut budget = RequestBudget::for_response::<proto::GetReleaseResponse>(&self.limits)?;
        let release = entry
            .map(|entry| {
                validation::entry(&entry, &tenant, &mut budget, &self.limits)?;
                if !selector::matches(&selector, entry.publication.as_ref()) {
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
        // Components may repeat. Explicit publication IDs carry the ordering
        // contract; legacy third-party repositories can omit these new fields.
        let mut previous = None;
        for entry in &page.entries {
            validation::entry(entry, &tenant, &mut budget, &self.limits)?;
            if let Some(id) = entry.publication.as_ref() {
                if previous.is_some_and(|previous| previous >= id) {
                    return Err(Status::internal(
                        "artifact repository returned an unordered publication page",
                    ));
                }
                previous = Some(id);
            }
            if query
                .service
                .as_ref()
                .is_some_and(|service| service != &entry.service)
            {
                return Err(Status::internal(
                    "artifact repository returned an invalid page",
                ));
            }
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

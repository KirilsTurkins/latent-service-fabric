use latent_artifacts::ArtifactCatalogEntry;
use latent_core::{PlatformError, PlatformErrorCode, TenantId};
use tonic::{Response, Status};

use super::super::{errors::platform_status, proto, ManagementServiceAdapter, RequestBudget};
use super::{package, release_descriptor_to_proto, validation};

impl ManagementServiceAdapter {
    pub(super) async fn publish_package(
        &self,
        tenant: &TenantId,
        upload: proto::PackageAdmissionUpload,
    ) -> Result<Response<proto::PublishReleaseResponse>, Status> {
        let upload = package::into_upload(upload)?;
        let mut response = None;
        let mut rejected = None;
        let result = {
            let mut preflight = |entry: &ArtifactCatalogEntry| {
                let prepared = if response.is_some() || rejected.is_some() {
                    Err(Status::internal("package publication preflight repeated"))
                } else {
                    self.package_response(entry, tenant)
                };
                match prepared {
                    Ok(prepared) => {
                        response = Some(prepared);
                        Ok(())
                    }
                    Err(status) => {
                        rejected = Some(status);
                        Err(PlatformError {
                            code: PlatformErrorCode::ResourceExhausted,
                            message: "package-publication-response-rejected".to_owned(),
                            retryable: false,
                            details: Vec::new(),
                        })
                    }
                }
            };
            self.services
                .artifacts
                .admit_package(tenant, upload, &mut preflight)
                .await
        };
        if let Some(status) = rejected {
            return Err(status);
        }
        let actual = result.map_err(|error| platform_status(error, &self.limits))?;
        let response =
            response.ok_or_else(|| Status::internal("package publication omitted preflight"))?;
        let mut budget =
            RequestBudget::for_response::<proto::PublishReleaseResponse>(&self.limits)?;
        validation::entry(&actual, tenant, &mut budget, &self.limits)?;
        let actual = release_descriptor_to_proto(actual)
            .map_err(|_| Status::internal("invalid package publication receipt"))?;
        if response.get_ref().release.as_ref() != Some(&actual) {
            return Err(Status::internal(
                "package publication receipt changed after preflight",
            ));
        }
        Ok(response)
    }

    fn package_response(
        &self,
        entry: &ArtifactCatalogEntry,
        tenant: &TenantId,
    ) -> Result<Response<proto::PublishReleaseResponse>, Status> {
        if entry.descriptor.publisher.is_none() {
            return Err(Status::internal(
                "package admission omitted verified publisher",
            ));
        }
        let mut budget =
            RequestBudget::for_response::<proto::PublishReleaseResponse>(&self.limits)?;
        // Validate and charge both retained source and prospective wire copy
        // before cloning any untrusted repository string/map capacities.
        validation::entry(entry, tenant, &mut budget, &self.limits)?;
        validation::entry(entry, tenant, &mut budget, &self.limits)?;
        budget.allocation::<proto::ReleaseDescriptor>(1)?;
        let release = release_descriptor_to_proto(entry.clone())
            .map_err(|_| Status::internal("invalid package admission descriptor"))?;
        self.response(proto::PublishReleaseResponse {
            release: Some(release),
            admission_warnings: Vec::new(),
        })
    }
}

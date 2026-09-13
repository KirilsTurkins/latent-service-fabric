use latent_artifacts::{
    ManagedPublicationUpload, ReleaseAuditGuard, ReleaseLifecycleAction, ReleaseOperationPreview,
};
use latent_core::{InvocationPrincipal, TenantId};
use tonic::{Response, Status};

use super::super::super::{control_audit, errors::platform_status, RequestBudget};
use super::super::{package, publication, release_descriptor_to_proto, validation};
use super::{
    preflight_rejection, proto, publication_context, response, ManagementServiceAdapter, Preflight,
};

impl ManagementServiceAdapter {
    pub(in super::super) async fn publish_managed_release(
        &self,
        principal: InvocationPrincipal,
        mut request: proto::PublishReleaseRequest,
    ) -> Result<Response<proto::PublishReleaseResponse>, Status> {
        let context = publication_context(principal, request.operation.take())?;
        let tenant = context
            .scope
            .tenant()
            .expect("authenticated tenant")
            .clone();
        let (upload, expected_release, expected_package) =
            if let Some(upload) = request.package.take() {
                let expected = latent_artifacts::package::package_digest(&upload.manifest);
                (
                    ManagedPublicationUpload::Package(package::into_upload(upload)?),
                    None,
                    Some(expected),
                )
            } else {
                let (artifact, summary) = publication::prepare(request, &tenant, &self.limits)?;
                (
                    ManagedPublicationUpload::Local(artifact),
                    Some(summary.descriptor.release_digest),
                    None,
                )
            };
        let mut preflight = Preflight::new(
            &tenant,
            &self.limits,
            &context,
            expected_release.as_ref(),
            ReleaseLifecycleAction::Publish,
        );
        preflight.audit_enabled = self.services.audit.is_some();
        let mut audit = ReleaseAuditGuard::new(
            self.services.audit.as_ref(),
            ReleaseLifecycleAction::Publish,
        );
        let mut prepared = None;
        let result = {
            let mut callback = |preview: ReleaseOperationPreview<'_>| {
                (|| {
                    preflight.preview(ReleaseOperationPreview {
                        replay: preview.replay,
                        receipt: preview.receipt,
                        release: preview.release,
                        failure: preview.failure,
                    })?;
                    if preview.failure.is_some() {
                        return audit.preview(preview);
                    }
                    let output = (|| {
                        if preview
                            .receipt
                            .record
                            .as_ref()
                            .and_then(|v| v.package.as_ref())
                            != expected_package.as_ref()
                        {
                            return Err(Status::internal(
                                "publication returned another package identity",
                            ));
                        }
                        self.managed_publication_response(
                            preview,
                            &tenant,
                            preflight.response.as_ref().expect("preflight receipt"),
                        )
                    })();
                    match output {
                        Ok(value) => {
                            prepared = Some(value);
                            audit.preview(preview)
                        }
                        Err(status) => {
                            preflight.rejected = Some(status);
                            Err(preflight_rejection())
                        }
                    }
                })()
            };
            self.services
                .artifacts
                .publish_managed(context, upload, &mut callback)
                .await
        };
        let ack = audit
            .finish(
                self.services.artifacts.as_ref(),
                result.as_ref().ok().map(|value| &value.operation),
            )
            .await;
        if let Some(status) = preflight.rejected.take() {
            return Err(control_audit::status(status, ack));
        }
        let actual = result
            .map_err(|error| control_audit::status(platform_status(error, &self.limits), ack))?;
        preflight
            .finish(Ok(actual.operation))
            .map_err(|error| control_audit::status(error, ack))?;
        let mut expected =
            prepared.ok_or_else(|| Status::internal("publication omitted release preflight"))?;
        let mut budget =
            RequestBudget::for_response::<proto::PublishReleaseResponse>(&self.limits)?;
        validation::entry(&actual.release, &tenant, &mut budget, &self.limits)?;
        let actual = release_descriptor_to_proto(actual.release)
            .map_err(|_| Status::internal("invalid publication receipt"))?;
        if expected.get_ref().release.as_ref() != Some(&actual) {
            return Err(Status::internal(
                "publication release changed after preflight",
            ));
        }
        expected.get_mut().audit_ack = self
            .services
            .audit
            .as_ref()
            .map(|_| control_audit::wire(ack));
        Ok(expected)
    }

    fn managed_publication_response(
        &self,
        preview: ReleaseOperationPreview<'_>,
        tenant: &TenantId,
        operation: &proto::ReleaseOperationReceipt,
    ) -> Result<Response<proto::PublishReleaseResponse>, Status> {
        let release = preview
            .release
            .ok_or_else(|| Status::internal("publication omitted release summary"))?;
        if preview
            .receipt
            .record
            .as_ref()
            .is_some_and(|record| record.package.is_some())
            && release.descriptor.publisher.is_none()
        {
            return Err(Status::internal(
                "package admission omitted verified publisher",
            ));
        }
        let mut budget =
            RequestBudget::for_response::<proto::PublishReleaseResponse>(&self.limits)?;
        if self.services.audit.is_some() {
            control_audit::charge(&mut budget)?;
        }
        validation::entry(release, tenant, &mut budget, &self.limits)?;
        validation::entry(release, tenant, &mut budget, &self.limits)?;
        response::charge_operation(preview.receipt, tenant, &mut budget, &self.limits)?;
        if preview.receipt.component_digest.as_ref() != Some(&release.descriptor.release_digest) {
            return Err(Status::internal(
                "publication operation does not bind release summary",
            ));
        }
        self.response(proto::PublishReleaseResponse {
            release: Some(
                release_descriptor_to_proto(release.clone())
                    .map_err(|_| Status::internal("invalid publication summary"))?,
            ),
            admission_warnings: Vec::new(),
            operation: Some(operation.clone()),
            audit_ack: self
                .services
                .audit
                .as_ref()
                .map(|_| control_audit::maximum()),
        })
    }
}

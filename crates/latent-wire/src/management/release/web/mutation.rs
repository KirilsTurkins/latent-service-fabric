use super::super::{lifecycle, package};
use super::{conversion, validation, ManagementServiceAdapter, RequestBudget};
use crate::management::{control_audit, errors::platform_status, proto, ManagementOperation};
use latent_artifacts::{
    PackageAdmissionUpload, PublicationRef, ReleaseEvidenceUpload, ReleaseLifecycleAction,
    ReleaseLifecycleReason, ReleaseMutationContext, WebAuditGuard,
};
use latent_core::{PlatformError, PlatformErrorCode};
use prost::Message;
use tonic::{Request, Response, Status};

enum Mutation {
    Publish(Box<PackageAdmissionUpload>),
    Change(ReleaseLifecycleAction, ReleaseLifecycleReason),
    Renew(ReleaseEvidenceUpload),
}

impl Mutation {
    fn action(&self) -> ReleaseLifecycleAction {
        match self {
            Self::Publish(_) => ReleaseLifecycleAction::Publish,
            Self::Change(action, _) => *action,
            Self::Renew(_) => ReleaseLifecycleAction::RenewEvidence,
        }
    }
    fn reason(&self) -> ReleaseLifecycleReason {
        match self {
            Self::Publish(_) => ReleaseLifecycleReason::Admitted,
            Self::Change(_, reason) => *reason,
            Self::Renew(_) => ReleaseLifecycleReason::EvidenceRenewed,
        }
    }
}

impl ManagementServiceAdapter {
    pub(in crate::management::release) async fn web_publish(
        &self,
        mut request: Request<proto::PublishWebPackageRequest>,
    ) -> Result<Response<proto::WebMutationResponse>, Status> {
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        let mut budget = RequestBudget::new::<proto::PublishWebPackageRequest>(&self.limits)?;
        validation::operation(
            request.get_ref().operation.as_ref(),
            &mut budget,
            &self.limits,
            true,
        )?;
        let upload = request
            .get_ref()
            .package
            .as_ref()
            .ok_or_else(|| Status::invalid_argument("web package is required"))?;
        package::validate(upload, &mut budget, &self.limits)?;
        self.check_encoded(request.get_ref())?;
        let request = request.into_inner();
        let context = lifecycle::publication_context(principal, request.operation)?;
        let upload = package::into_upload(request.package.expect("validated web package"))?;
        let reference = PublicationRef::package(
            context.scope.clone(),
            &latent_artifacts::package::package_digest(&upload.manifest),
        )
        .map_err(|failure| platform_status(failure, &self.limits))?;
        self.web_mutation(context, reference, Mutation::Publish(Box::new(upload)))
            .await
    }

    pub(in crate::management::release) async fn web_change(
        &self,
        mut request: Request<proto::ChangeWebLifecycleRequest>,
    ) -> Result<Response<proto::WebMutationResponse>, Status> {
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        let mut budget = RequestBudget::new::<proto::ChangeWebLifecycleRequest>(&self.limits)?;
        let reference = validation::publication(
            request.get_ref().publication.as_ref(),
            principal.tenant.as_ref().expect("authenticated tenant"),
            &mut budget,
            &self.limits,
        )?;
        validation::operation(
            request.get_ref().operation.as_ref(),
            &mut budget,
            &self.limits,
            false,
        )?;
        let (action, reason) =
            lifecycle::conversion::change(request.get_ref().action, request.get_ref().reason)?;
        self.check_encoded(request.get_ref())?;
        let context = lifecycle::publication_context(principal, request.into_inner().operation)?;
        self.web_mutation(context, reference, Mutation::Change(action, reason))
            .await
    }

    pub(in crate::management::release) async fn web_renew(
        &self,
        mut request: Request<proto::RenewWebEvidenceRequest>,
    ) -> Result<Response<proto::WebMutationResponse>, Status> {
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        let mut budget = RequestBudget::new::<proto::RenewWebEvidenceRequest>(&self.limits)?;
        let reference = validation::publication(
            request.get_ref().publication.as_ref(),
            principal.tenant.as_ref().expect("authenticated tenant"),
            &mut budget,
            &self.limits,
        )?;
        validation::operation(
            request.get_ref().operation.as_ref(),
            &mut budget,
            &self.limits,
            false,
        )?;
        let evidence = request
            .get_ref()
            .evidence
            .as_ref()
            .ok_or_else(|| Status::invalid_argument("web evidence is required"))?;
        package::validate_evidence(
            &evidence.signatures,
            &evidence.provenance,
            &evidence.sboms,
            &mut budget,
            &self.limits,
            true,
        )?;
        self.check_encoded(request.get_ref())?;
        let request = request.into_inner();
        let context = lifecycle::publication_context(principal, request.operation)?;
        let evidence =
            package::into_evidence_upload(request.evidence.expect("validated web evidence"))?;
        self.web_mutation(context, reference, Mutation::Renew(evidence))
            .await
    }

    async fn web_mutation(
        &self,
        context: ReleaseMutationContext,
        reference: PublicationRef,
        mutation: Mutation,
    ) -> Result<Response<proto::WebMutationResponse>, Status> {
        let catalog = self.web_catalog()?;
        let action = mutation.action();
        let reason = mutation.reason();
        let tenant = context
            .scope
            .tenant()
            .expect("authenticated tenant")
            .clone();
        let mut audit = WebAuditGuard::new(self.services.audit.as_ref(), action);
        let mut prepared = None;
        let mut rejected = None;
        let expected = context.clone();
        let selected = reference.clone();
        let result = {
            let mut preflight = |preview: &latent_artifacts::web::WebMutationResult| {
                let output = (|| {
                    if prepared.is_some()
                        || preview.receipt.publication != selected
                        || preview.receipt.actor != expected.actor
                        || preview.receipt.action != action
                        || preview.receipt.reason != reason
                        || expected.operation.as_ref().is_none_or(|operation| {
                            operation.operation_id != preview.receipt.operation_id
                                || operation.expected_generation
                                    != preview.receipt.expected_generation
                        })
                    {
                        return Err(Status::internal("web operation preview identity mismatch"));
                    }
                    let output = conversion::mutation(
                        preview,
                        &tenant,
                        &self.limits,
                        self.services.audit.is_some(),
                    )?;
                    if output.encoded_len() > self.limits.max_response_bytes {
                        return Err(crate::management::bounds::exhausted());
                    }
                    Ok(output)
                })();
                match output {
                    Ok(output) => {
                        prepared = Some((preview.clone(), output));
                        audit.preview(preview)
                    }
                    Err(failure) => {
                        rejected = Some(failure);
                        Err(PlatformError {
                            code: PlatformErrorCode::ResourceExhausted,
                            message: "web-response-preflight-rejected".into(),
                            retryable: false,
                            details: Vec::new(),
                        })
                    }
                }
            };
            match mutation {
                Mutation::Publish(upload) => {
                    catalog.publish_web_package(context, *upload, &mut preflight)
                }
                Mutation::Change(action, reason) => catalog.transition_web_publication(
                    context,
                    &reference,
                    action,
                    reason,
                    &mut preflight,
                ),
                Mutation::Renew(evidence) => {
                    catalog.renew_web_evidence(context, &reference, evidence, &mut preflight)
                }
            }
        };
        let ack = audit.finish(catalog).await;
        if let Some(rejected) = rejected {
            return Err(control_audit::status(rejected, ack));
        }
        let actual = result.map_err(|failure| {
            control_audit::status(platform_status(failure, &self.limits), ack)
        })?;
        let (preview, mut output) =
            prepared.ok_or_else(|| Status::internal("web operation omitted response preflight"))?;
        if actual != preview {
            return Err(control_audit::status(
                Status::internal("web operation outcome differs from preflight"),
                ack,
            ));
        }
        output.audit_ack = self
            .services
            .audit
            .as_ref()
            .map(|_| control_audit::wire(ack));
        self.response(output)
            .map(|response| control_audit::response(response, ack))
    }
}

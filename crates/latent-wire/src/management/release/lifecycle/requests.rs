use super::super::super::{
    errors::platform_status, identifier, ManagementOperation, RequestBudget,
};
use super::super::{package, validation};
use super::{conversion, proto, response, ManagementLimits, ManagementServiceAdapter, Preflight};
use latent_artifacts::{
    LifecycleScope, ReleaseActor, ReleaseActorKind, ReleaseLifecycleAction, ReleaseMutationContext,
    ReleaseOperationLookup, ReleaseOperationPrecondition,
};
use latent_core::{InvocationPrincipal, PackageDigest, ReleaseDigest, TenantId};
use tonic::{Request, Response, Status};

pub(in super::super) fn operation(
    value: Option<&proto::ReleaseOperationPrecondition>,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
    publish: bool,
) -> Result<(), Status> {
    let Some(value) = value else {
        return if publish {
            Ok(())
        } else {
            Err(Status::invalid_argument("release operation is required"))
        };
    };
    budget.allocation::<proto::ReleaseOperationPrecondition>(1)?;
    budget.string(&value.operation_id, 128.min(limits.max_id_bytes))?;
    identifier(&value.operation_id, 128.min(limits.max_id_bytes))?;
    let generation = value
        .expected_generation
        .ok_or_else(|| Status::invalid_argument("release generation is required"))?;
    if (publish && generation != 0) || (!publish && generation == 0) {
        return Err(Status::invalid_argument(
            "invalid release lifecycle generation",
        ));
    }
    Ok(())
}

pub(in super::super) fn publication_context(
    principal: InvocationPrincipal,
    operation: Option<proto::ReleaseOperationPrecondition>,
) -> Result<ReleaseMutationContext, Status> {
    let tenant = principal.tenant.as_ref().expect("authenticated tenant");
    Ok(ReleaseMutationContext {
        scope: LifecycleScope::Tenant(TenantId(tenant.0.clone())),
        actor: ReleaseActor {
            subject: principal.subject.clone(),
            kind: ReleaseActorKind::try_from(principal.kind)
                .map_err(|_| Status::permission_denied("unsupported release actor"))?,
        },
        operation: operation.map(|value| ReleaseOperationPrecondition {
            operation_id: value.operation_id,
            expected_generation: value
                .expected_generation
                .expect("validated release generation"),
        }),
    })
}

impl ManagementServiceAdapter {
    pub(in super::super) async fn lifecycle_status(
        &self,
        mut request: Request<proto::GetReleaseLifecycleRequest>,
    ) -> Result<Response<proto::GetReleaseLifecycleResponse>, Status> {
        let tenant = self
            .authenticate(&mut request, ManagementOperation::Tenant)?
            .tenant
            .expect("authenticated tenant");
        let mut budget = RequestBudget::new::<proto::GetReleaseLifecycleRequest>(&self.limits)?;
        validation::digest(&request.get_ref().digest, &mut budget, &self.limits)?;
        self.check_encoded(request.get_ref())?;
        let digest = ReleaseDigest(request.into_inner().digest);
        let value = self
            .services
            .artifacts
            .get_release_lifecycle(&LifecycleScope::Tenant(tenant.clone()), &digest)
            .await
            .map_err(|error| platform_status(error, &self.limits))?;
        let status = value
            .as_ref()
            .map(|value| {
                if value.record.release != digest {
                    return Err(Status::internal("lifecycle query returned another release"));
                }
                response::status(value, &tenant, &self.limits)
            })
            .transpose()?;
        self.response(proto::GetReleaseLifecycleResponse { status })
    }

    pub(in super::super) async fn lifecycle_operation(
        &self,
        mut request: Request<proto::GetReleaseOperationRequest>,
    ) -> Result<Response<proto::GetReleaseOperationResponse>, Status> {
        let tenant = self
            .authenticate(&mut request, ManagementOperation::Tenant)?
            .tenant
            .expect("authenticated tenant");
        let mut budget = RequestBudget::new::<proto::GetReleaseOperationRequest>(&self.limits)?;
        budget.string(
            &request.get_ref().operation_id,
            128.min(self.limits.max_id_bytes),
        )?;
        identifier(
            &request.get_ref().operation_id,
            128.min(self.limits.max_id_bytes),
        )?;
        self.check_encoded(request.get_ref())?;
        let id = request.into_inner().operation_id;
        let value = self
            .services
            .artifacts
            .get_release_operation(&LifecycleScope::Tenant(tenant.clone()), &id)
            .await
            .map_err(|error| platform_status(error, &self.limits))?;
        use proto::ReleaseOperationLookupDisposition as D;
        let (lookup, receipt) = match value {
            ReleaseOperationLookup::Found(value) => {
                if value.operation_id != id {
                    return Err(Status::internal(
                        "operation query returned another operation",
                    ));
                }
                (
                    D::Found,
                    Some(response::operation(&value, &tenant, &self.limits)?),
                )
            }
            ReleaseOperationLookup::Unknown => (D::Unknown, None),
            ReleaseOperationLookup::Uncertain => (D::Uncertain, None),
        };
        self.response(proto::GetReleaseOperationResponse {
            lookup: lookup as i32,
            receipt,
        })
    }

    pub(in super::super) async fn lifecycle_change(
        &self,
        mut request: Request<proto::ChangeReleaseLifecycleRequest>,
    ) -> Result<Response<proto::ChangeReleaseLifecycleResponse>, Status> {
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        let mut budget = RequestBudget::new::<proto::ChangeReleaseLifecycleRequest>(&self.limits)?;
        validation::digest(&request.get_ref().digest, &mut budget, &self.limits)?;
        operation(
            request.get_ref().operation.as_ref(),
            &mut budget,
            &self.limits,
            false,
        )?;
        let (action, reason) =
            conversion::change(request.get_ref().action, request.get_ref().reason)?;
        self.check_encoded(request.get_ref())?;
        let request = request.into_inner();
        let context = publication_context(principal, request.operation)?;
        let tenant = context
            .scope
            .tenant()
            .expect("authenticated tenant")
            .clone();
        let release = ReleaseDigest(request.digest);
        let mut preflight = Preflight::new(&tenant, &self.limits, &context, Some(&release), action);
        preflight.reason = Some(reason);
        let result = {
            let mut callback =
                |preview: latent_artifacts::ReleaseOperationPreview<'_>| preflight.preview(preview);
            self.services
                .artifacts
                .change_release_lifecycle(context, &release, action, reason, &mut callback)
                .await
        };
        self.response(proto::ChangeReleaseLifecycleResponse {
            operation: Some(preflight.finish(result)?),
        })
    }

    pub(in super::super) async fn lifecycle_renew(
        &self,
        mut request: Request<proto::RenewReleaseEvidenceRequest>,
    ) -> Result<Response<proto::RenewReleaseEvidenceResponse>, Status> {
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        let mut budget = RequestBudget::new::<proto::RenewReleaseEvidenceRequest>(&self.limits)?;
        validation::digest(&request.get_ref().digest, &mut budget, &self.limits)?;
        validation::digest(&request.get_ref().package_digest, &mut budget, &self.limits)?;
        operation(
            request.get_ref().operation.as_ref(),
            &mut budget,
            &self.limits,
            false,
        )?;
        let evidence = request
            .get_ref()
            .evidence
            .as_ref()
            .ok_or_else(|| Status::invalid_argument("release evidence is required"))?;
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
        let context = publication_context(principal, request.operation)?;
        let tenant = context
            .scope
            .tenant()
            .expect("authenticated tenant")
            .clone();
        let release = ReleaseDigest(request.digest);
        let package = request
            .package_digest
            .parse::<PackageDigest>()
            .map_err(|_| Status::invalid_argument("invalid package digest"))?;
        let evidence =
            package::into_evidence_upload(request.evidence.expect("validated evidence"))?;
        let mut preflight = Preflight::new(
            &tenant,
            &self.limits,
            &context,
            Some(&release),
            ReleaseLifecycleAction::RenewEvidence,
        );
        preflight.package = Some(package.clone());
        let result = {
            let mut callback =
                |preview: latent_artifacts::ReleaseOperationPreview<'_>| preflight.preview(preview);
            self.services
                .artifacts
                .renew_release_evidence(context, &release, &package, evidence, &mut callback)
                .await
        };
        self.response(proto::RenewReleaseEvidenceResponse {
            operation: Some(preflight.finish(result)?),
        })
    }
}

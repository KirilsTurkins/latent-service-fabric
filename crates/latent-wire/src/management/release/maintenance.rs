//! Authenticated, bounded publication maintenance on the existing control owner.
mod conversion;
#[cfg(test)]
mod tests;
mod validation;

use crate::management::{
    bounds, control_audit, errors::platform_status, proto, ManagementOperation,
    ManagementServiceAdapter, RequestBudget,
};
use latent_artifacts::{
    DirectoryArtifactRepository, LifecycleScope, PublicationDeletionLookup,
    PublicationMaintenanceReceipt as Receipt, PublicationMaintenanceRequest as Command,
    PublicationReclamationLookup, PublicationRetentionLookup,
};
use latent_core::{InvocationPrincipal, PlatformError, PlatformErrorCode};
use prost::Message;
use std::time::{Duration, Instant};
use tonic::{Request, Response, Status};

impl ManagementServiceAdapter {
    fn maintenance_catalog(&self) -> Result<&DirectoryArtifactRepository, Status> {
        // with_web_catalog already verifies pointer equality with the installed
        // artifacts owner. No request may substitute a catalog or reference list.
        self.web.as_deref().ok_or_else(|| {
            Status::unimplemented("native publication maintenance is not configured")
        })
    }

    pub(super) fn retention_snapshot(
        &self,
        mut request: Request<proto::GetPublicationRetentionRequest>,
    ) -> Result<Response<proto::GetPublicationRetentionResponse>, Status> {
        let expires = deadline(&request, request.get_ref().maximum_wait_millis)?;
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        let tenant = principal.tenant.expect("authenticated tenant");
        self.check_encoded(request.get_ref())?;
        let mut budget = RequestBudget::new::<proto::GetPublicationRetentionRequest>(&self.limits)?;
        let publications = validation::publications(
            &request.get_ref().publications,
            &tenant,
            &mut budget,
            &self.limits,
        )?;
        let value = self
            .maintenance_catalog()?
            .publication_retention_snapshot(
                &LifecycleScope::Tenant(tenant.clone()),
                &publications,
                remaining(expires)?,
            )
            .map_err(|e| platform_status(e, &self.limits))?;
        let output = conversion::snapshot(&value, &tenant, &self.limits)?;
        self.response(output)
    }

    pub(super) fn publication_maintenance(
        &self,
        mut request: Request<proto::MaintainPublicationsRequest>,
    ) -> Result<Response<proto::MaintainPublicationsResponse>, Status> {
        let expires = deadline(&request, request.get_ref().maximum_wait_millis)?;
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        self.check_encoded(request.get_ref())?;
        let mut budget = RequestBudget::new::<proto::MaintainPublicationsRequest>(&self.limits)?;
        let command = validation::command(
            request.get_ref().command.as_ref(),
            &principal,
            &mut budget,
            &self.limits,
        )?;
        let catalog = self.maintenance_catalog()?;
        // Destructive maintenance is never silently unaudited, even in an
        // embedding where older release operations permit disabled audit.
        let audit = self.services.audit.as_ref().ok_or_else(|| {
            Status::failed_precondition("publication-maintenance-requires-durable-audit")
        })?;
        let tenant = principal.tenant.as_ref().expect("authenticated tenant");
        let mut prepared = None;
        let mut rejected = None;
        let outcome = catalog.audited_publication_maintenance(
            audit,
            &command,
            remaining(expires)?,
            &mut |preview| {
                let result = (|| {
                    remaining(expires)?;
                    self.services
                        .authorization
                        .authorize(&principal, ManagementOperation::Tenant)
                        .map_err(|e| platform_status(e, &self.limits))?;
                    if prepared.is_some() {
                        return Err(Status::internal("duplicate publication preflight"));
                    }
                    let output = proto::MaintainPublicationsResponse {
                        receipt: Some(conversion::receipt(&preview.receipt, tenant, &self.limits)?),
                        replay: preview.replay,
                        audit_ack: Some(control_audit::maximum()),
                    };
                    let mut budget = RequestBudget::for_response::<
                        proto::MaintainPublicationsResponse,
                    >(&self.limits)?;
                    control_audit::charge(&mut budget)?;
                    // The complete projected receipt and maximum acknowledgement
                    // must fit BEFORE any audit attempt or native mutation.
                    budget.allocation::<u8>(output.encoded_len())?;
                    self.check_response_encoded(&output)?;
                    Ok(output)
                })();
                match result {
                    Ok(output) => {
                        prepared = Some((preview.clone(), output));
                        Ok(())
                    }
                    Err(failure) => {
                        rejected = Some(failure);
                        Err(PlatformError {
                            code: PlatformErrorCode::ResourceExhausted,
                            message: "publication-maintenance-response-preflight-rejected".into(),
                            retryable: false,
                            details: Vec::new(),
                        })
                    }
                }
            },
        );
        if let Some(error) = rejected {
            return Err(control_audit::status(error, outcome.audit));
        }
        let actual = outcome
            .result
            .map_err(|e| control_audit::status(platform_status(e, &self.limits), outcome.audit))?;
        let (preview, mut output) = prepared.ok_or_else(|| {
            control_audit::status(
                Status::internal("publication maintenance omitted preflight"),
                outcome.audit,
            )
        })?;
        if actual != preview {
            return Err(control_audit::status(
                Status::internal("publication maintenance result differs from preflight"),
                outcome.audit,
            ));
        }
        output.audit_ack = Some(control_audit::wire(outcome.audit));
        self.response(output)
            .map(|r| control_audit::response(r, outcome.audit))
    }

    pub(super) fn reclamation_assessment(
        &self,
        mut request: Request<proto::AssessPublicationReclamationRequest>,
    ) -> Result<Response<proto::AssessPublicationReclamationResponse>, Status> {
        let expires = deadline(&request, request.get_ref().maximum_wait_millis)?;
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        self.check_encoded(request.get_ref())?;
        let mut budget =
            RequestBudget::new::<proto::AssessPublicationReclamationRequest>(&self.limits)?;
        let selected = validation::selection(
            request.get_ref().deletion.as_ref(),
            &principal,
            &mut budget,
            &self.limits,
        )?;
        let limits = validation::work(
            request.get_ref().maximum_files,
            request.get_ref().maximum_bytes_hashed,
        )?;
        let value = self
            .maintenance_catalog()?
            .inspect_publication_reclamation(&selected, limits, remaining(expires)?)
            .map_err(|e| platform_status(e, &self.limits))?;
        let tenant = principal.tenant.as_ref().expect("authenticated tenant");
        let mut output_budget = RequestBudget::for_response::<
            proto::AssessPublicationReclamationResponse,
        >(&self.limits)?;
        conversion::selection_budget(&value.deletion, tenant, &mut output_budget, &self.limits)?;
        output_budget.allocation::<proto::PublicationReclamationAccounting>(1)?;
        self.response(proto::AssessPublicationReclamationResponse {
            tenant: tenant.0.clone(),
            deletion: Some(conversion::selection(&value.deletion)),
            catalog_fence: value.catalog_fence.as_bytes().to_vec(),
            reference_revision: value.reference_revision,
            potential: Some(conversion::content(value.content)?),
        })
    }

    pub(super) fn maintenance_operation(
        &self,
        mut request: Request<proto::GetPublicationMaintenanceOperationRequest>,
    ) -> Result<Response<proto::GetPublicationMaintenanceOperationResponse>, Status> {
        let tenant = self
            .authenticate(&mut request, ManagementOperation::Tenant)?
            .tenant
            .expect("authenticated tenant");
        self.check_encoded(request.get_ref())?;
        let mut budget =
            RequestBudget::new::<proto::GetPublicationMaintenanceOperationRequest>(&self.limits)?;
        validation::operation(&request.get_ref().operation_id, &mut budget, &self.limits)?;
        let kind = validation::kind(request.get_ref().kind)?;
        let scope = LifecycleScope::Tenant(tenant.clone());
        let id = &request.get_ref().operation_id;
        let catalog = self.maintenance_catalog()?;
        use proto::{PublicationMaintenanceKind as K, ReleaseOperationLookupDisposition as D};
        let (receipt, disposition) = match kind {
            K::Pin | K::Unpin => match catalog
                .publication_retention_operation(&scope, id)
                .map_err(|e| platform_status(e, &self.limits))?
            {
                PublicationRetentionLookup::Found(r)
                    if (r.request.action == latent_artifacts::PublicationRetentionAction::Pin)
                        == (kind == K::Pin) =>
                {
                    (Some(Receipt::Retention(r)), D::Found)
                }
                PublicationRetentionLookup::Uncertain => (None, D::Uncertain),
                _ => (None, D::Unknown),
            },
            K::Delete => match catalog
                .publication_deletion_operation(&scope, id)
                .map_err(|e| platform_status(e, &self.limits))?
            {
                PublicationDeletionLookup::Found(r) => (Some(Receipt::Deletion(r)), D::Found),
                PublicationDeletionLookup::Unknown => (None, D::Unknown),
                PublicationDeletionLookup::Uncertain => (None, D::Uncertain),
            },
            K::Reclaim => match catalog
                .publication_reclamation_operation(&scope, id)
                .map_err(|e| platform_status(e, &self.limits))?
            {
                PublicationReclamationLookup::Found(r) => (Some(Receipt::Reclamation(r)), D::Found),
                PublicationReclamationLookup::Unknown => (None, D::Unknown),
                PublicationReclamationLookup::Uncertain => (None, D::Uncertain),
            },
            K::Unspecified => unreachable!("validated maintenance kind"),
        };
        let receipt = receipt
            .as_ref()
            .map(|r| conversion::receipt(r, &tenant, &self.limits))
            .transpose()?;
        self.response(proto::GetPublicationMaintenanceOperationResponse {
            tenant: tenant.0,
            disposition: disposition as i32,
            receipt,
        })
    }

    fn check_response_encoded(&self, value: &impl Message) -> Result<(), Status> {
        if value.encoded_len() > self.limits.max_response_bytes {
            Err(bounds::exhausted())
        } else {
            Ok(())
        }
    }
}

fn deadline<T>(request: &Request<T>, millis: u64) -> Result<Instant, Status> {
    if !(1..=30_000).contains(&millis) {
        return Err(Status::invalid_argument(
            "publication-maintenance-wait-must-be-1-to-30000-ms",
        ));
    }
    let maximum = Instant::now() + Duration::from_millis(millis);
    Ok(request
        .extensions()
        .get::<crate::invocation::AuthenticatedInvocationContext>()
        .and_then(crate::invocation::AuthenticatedInvocationContext::transport_expires_at)
        .map_or(maximum, |expires| expires.min(maximum)))
}
fn remaining(expires: Instant) -> Result<Duration, Status> {
    expires
        .checked_duration_since(Instant::now())
        .filter(|v| !v.is_zero())
        .ok_or_else(|| Status::deadline_exceeded("publication-maintenance-original-deadline"))
}

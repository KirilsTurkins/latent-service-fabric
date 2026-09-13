mod conversion;
mod publication;
mod requests;
mod response;
#[cfg(test)]
mod tests;

pub(super) use requests::{operation, publication_context};

use latent_artifacts::{
    ReleaseActor, ReleaseLifecycleAction, ReleaseLifecycleReason, ReleaseMutationContext,
    ReleaseOperationPreview, ReleaseOperationReceipt,
};
use latent_core::{PackageDigest, PlatformError, PlatformErrorCode, ReleaseDigest, TenantId};
use tonic::Status;

use super::super::{errors::platform_status, proto, ManagementLimits, ManagementServiceAdapter};

/// Captures an immutable, fully budgeted response before either a successful
/// mutation or a rejected-operation receipt may be persisted.
struct Preflight<'a> {
    audit_enabled: bool,
    tenant: &'a TenantId,
    limits: &'a ManagementLimits,
    response: Option<proto::ReleaseOperationReceipt>,
    failure: Option<Status>,
    rejected: Option<Status>,
    actor: ReleaseActor,
    action: ReleaseLifecycleAction,
    operation_id: Option<String>,
    expected_generation: Option<u64>,
    release: Option<ReleaseDigest>,
    package: Option<PackageDigest>,
    reason: Option<ReleaseLifecycleReason>,
}

impl<'a> Preflight<'a> {
    fn new(
        tenant: &'a TenantId,
        limits: &'a ManagementLimits,
        context: &ReleaseMutationContext,
        release: Option<&ReleaseDigest>,
        action: ReleaseLifecycleAction,
    ) -> Self {
        Self {
            audit_enabled: false,
            tenant,
            limits,
            response: None,
            failure: None,
            rejected: None,
            actor: context.actor.clone(),
            action,
            release: release.cloned(),
            package: None,
            reason: None,
            operation_id: context.operation.as_ref().map(|v| v.operation_id.clone()),
            expected_generation: context.operation.as_ref().map(|v| v.expected_generation),
        }
    }

    fn preview(&mut self, preview: ReleaseOperationPreview<'_>) -> Result<(), PlatformError> {
        let result = if self.response.is_some() || self.rejected.is_some() {
            Err(Status::internal("release operation preflight repeated"))
        } else {
            self.operation_response(preview.receipt).and_then(|value| {
                if preview.receipt.actor != self.actor
                    || preview.receipt.action != self.action
                    || self
                        .operation_id
                        .as_ref()
                        .is_some_and(|v| v != &preview.receipt.operation_id)
                    || (self.operation_id.is_some()
                        && preview.receipt.expected_generation != self.expected_generation)
                    || self
                        .release
                        .as_ref()
                        .is_some_and(|v| preview.receipt.component_digest.as_ref() != Some(v))
                {
                    return Err(Status::internal(
                        "release operation preview changed the request identity",
                    ));
                }
                if let Some(failure) = preview.failure {
                    if preview.receipt.disposition
                        != latent_artifacts::ReleaseOperationDisposition::Rejected
                    {
                        return Err(Status::internal("release failure preview is not rejected"));
                    }
                    self.failure = Some(response::failure(
                        failure,
                        &value,
                        &self.response_limits()?,
                    )?);
                } else if preview.receipt.disposition
                    != latent_artifacts::ReleaseOperationDisposition::Committed
                {
                    return Err(Status::internal("release success preview is not committed"));
                }
                if preview.failure.is_none()
                    && (self.package.as_ref().is_some_and(|package| {
                        preview
                            .receipt
                            .record
                            .as_ref()
                            .and_then(|record| record.package.as_ref())
                            != Some(package)
                    }) || self
                        .reason
                        .is_some_and(|reason| preview.receipt.reason != reason))
                {
                    return Err(Status::internal(
                        "release operation preview changed the requested transition",
                    ));
                }
                Ok(value)
            })
        };
        match result {
            Ok(value) => {
                self.response = Some(value);
                Ok(())
            }
            Err(status) => {
                self.rejected = Some(status);
                Err(preflight_rejection())
            }
        }
    }

    fn operation_response(
        &self,
        receipt: &ReleaseOperationReceipt,
    ) -> Result<proto::ReleaseOperationReceipt, Status> {
        let limits = self.response_limits()?;
        let value = response::operation(receipt, self.tenant, &limits)?;
        if self.audit_enabled && self.action != ReleaseLifecycleAction::Publish {
            super::super::control_audit::operation_preflight(&value, self.limits)?;
        }
        Ok(value)
    }

    fn response_limits(&self) -> Result<ManagementLimits, Status> {
        let mut limits = self.limits.clone();
        if self.audit_enabled {
            limits.max_response_bytes = limits
                .max_response_bytes
                .checked_sub(128 + std::mem::size_of::<proto::AuditAck>())
                .ok_or_else(super::super::bounds::exhausted)?;
        }
        Ok(limits)
    }

    fn finish(
        self,
        result: Result<ReleaseOperationReceipt, PlatformError>,
    ) -> Result<proto::ReleaseOperationReceipt, Status> {
        if let Some(status) = self.rejected {
            return Err(status);
        }
        let actual = result.map_err(|error| platform_status(error, self.limits))?;
        if self.failure.is_some() {
            return Err(Status::internal(
                "release operation returned success after rejection",
            ));
        }
        let expected = self
            .response
            .ok_or_else(|| Status::internal("release operation omitted preflight"))?;
        let actual = response::operation(&actual, self.tenant, self.limits)?;
        if actual != expected {
            return Err(Status::internal(
                "release operation receipt changed after preflight",
            ));
        }
        Ok(expected)
    }
}

fn preflight_rejection() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::ResourceExhausted,
        message: "release-operation-response-rejected".to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

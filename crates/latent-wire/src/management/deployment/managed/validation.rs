use super::super::super::{bounds, proto, ManagementLimits, RequestBudget};
use super::super::{deployment_manifest_from_proto, validation};
use latent_artifacts::{ReleaseActor, ReleaseActorKind};
use latent_control_store::deployment_operations::{
    DeploymentOperationContext, DeploymentOperationRequest, MAX_REQUEST_BYTES,
};
use latent_core::{DeploymentId, InvocationPrincipal};
use latent_manifest::{ManifestValidator, Phase1ManifestValidator};
use prost::Message;
use std::time::{Duration, Instant};
use tonic::{Request, Status};

#[cfg(test)]
mod tests;

pub(in crate::management::deployment) fn deadline<T>(request: &Request<T>) -> Instant {
    let maximum = Instant::now() + Duration::from_secs(30);
    request
        .extensions()
        .get::<crate::invocation::AuthenticatedInvocationContext>()
        .and_then(crate::invocation::AuthenticatedInvocationContext::transport_expires_at)
        .map_or(maximum, |deadline| deadline.min(maximum))
}
pub(super) fn expired() -> Status {
    Status::deadline_exceeded("managed deployment deadline exceeded")
}
pub(super) fn completed(deadline: Instant) -> Result<(), Status> {
    if Instant::now() >= deadline {
        Err(expired())
    } else {
        Ok(())
    }
}
fn limits(limits: &ManagementLimits) -> ManagementLimits {
    let mut bounded = limits.clone();
    bounded.max_request_bytes = bounded.max_request_bytes.min(MAX_REQUEST_BYTES);
    bounded
}
fn encoded<T: Message>(value: &T, limits: &ManagementLimits) -> Result<(), Status> {
    if value.encoded_len() > limits.max_request_bytes {
        Err(bounds::exhausted())
    } else {
        Ok(())
    }
}
fn operation(
    value: Option<&proto::DeploymentOperationPrecondition>,
    expected: Option<u64>,
    delete: bool,
    budget: &mut RequestBudget,
) -> Result<(), Status> {
    let value =
        value.ok_or_else(|| Status::invalid_argument("deployment operation is required"))?;
    budget.allocation::<proto::DeploymentOperationPrecondition>(1)?;
    validation::id(&value.operation_id, budget, 128)?;
    if value.expected_state_version.is_none()
        || expected.is_none()
        || (delete && expected == Some(0))
    {
        return Err(Status::invalid_argument(
            "managed deployment preconditions are required",
        ));
    }
    Ok(())
}
fn context(
    principal: InvocationPrincipal,
    operation: proto::DeploymentOperationPrecondition,
) -> Result<DeploymentOperationContext, Status> {
    let tenant = principal
        .tenant
        .ok_or_else(|| Status::permission_denied("deployment tenant is required"))?;
    bounds::identifier(&tenant.0, 256)?;
    bounds::identifier(&principal.subject, 512)?;
    let kind = ReleaseActorKind::try_from(principal.kind)
        .map_err(|_| Status::permission_denied("deployment actor is not supported"))?;
    Ok(DeploymentOperationContext {
        tenant,
        actor: ReleaseActor {
            subject: principal.subject,
            kind,
        },
        operation_id: operation.operation_id,
        expected_state_version: operation
            .expected_state_version
            .expect("validated state version"),
    })
}
pub(super) fn apply(
    value: proto::ApplyDeploymentRequest,
    principal: InvocationPrincipal,
    configured: &ManagementLimits,
) -> Result<DeploymentOperationRequest, Status> {
    let limits = limits(configured);
    let mut budget = RequestBudget::new::<proto::ApplyDeploymentRequest>(&limits)?;
    operation(
        value.operation.as_ref(),
        value.expected_generation,
        false,
        &mut budget,
    )?;
    let deployment = value
        .deployment
        .as_ref()
        .ok_or_else(|| Status::invalid_argument("deployment is required"))?;
    validation::wire(deployment, &mut budget, &limits)?;
    encoded(&value, &limits)?;
    if deployment
        .metadata
        .as_ref()
        .and_then(|metadata| metadata.tenant.as_deref())
        != principal.tenant.as_ref().map(|tenant| tenant.0.as_str())
    {
        return Err(Status::permission_denied(
            "deployment tenant does not match authenticated scope",
        ));
    }
    let context = context(principal, value.operation.expect("validated operation"))?;
    let mut manifest =
        deployment_manifest_from_proto(value.deployment.expect("validated deployment"))
            .map_err(|_| Status::invalid_argument("invalid deployment representation"))?;
    Phase1ManifestValidator
        .validate_deployment(&manifest)
        .map_err(|_| Status::invalid_argument("invalid deployment"))?;
    manifest.normalize_storage_fields();
    Ok(DeploymentOperationRequest::Apply {
        context,
        manifest,
        expected_generation: value
            .expected_generation
            .expect("validated object generation"),
    })
}
pub(super) fn delete(
    value: proto::DeleteDeploymentRequest,
    principal: InvocationPrincipal,
    configured: &ManagementLimits,
) -> Result<DeploymentOperationRequest, Status> {
    let limits = limits(configured);
    let mut budget = RequestBudget::new::<proto::DeleteDeploymentRequest>(&limits)?;
    operation(
        value.operation.as_ref(),
        value.expected_generation,
        true,
        &mut budget,
    )?;
    validation::id(&value.id, &mut budget, limits.max_id_bytes)?;
    encoded(&value, &limits)?;
    Ok(DeploymentOperationRequest::Delete {
        context: context(principal, value.operation.expect("validated operation"))?,
        id: DeploymentId(value.id),
        expected_generation: value
            .expected_generation
            .expect("validated object generation"),
    })
}

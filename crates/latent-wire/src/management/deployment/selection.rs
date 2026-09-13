//! Resolve explicit input authority before compiling a normalized deployment.
use latent_artifacts::{ArtifactRepository, LifecycleScope, PublicationRef, PublicationSelector};
use latent_core::{ArtifactBlobDigest, TenantId};
use prost::Message;
use tonic::Status;

use super::super::{errors::platform_status, proto, ManagementLimits, RequestBudget};

pub(in crate::management) async fn input(
    mut value: proto::ApplyDeploymentRequest,
    tenant: &TenantId,
    repository: &dyn ArtifactRepository,
    configured: &ManagementLimits,
) -> Result<proto::ApplyDeploymentRequest, Status> {
    let mut limits = configured.clone();
    if value.operation.is_some() {
        limits.max_request_bytes = limits
            .max_request_bytes
            .min(latent_control_store::deployment_operations::MAX_REQUEST_BYTES);
    }
    let mut budget = RequestBudget::new::<proto::ApplyDeploymentRequest>(&limits)?;
    let deployment = value
        .deployment
        .as_ref()
        .ok_or_else(|| invalid("deployment is required"))?;
    super::validation::wire(deployment, &mut budget, &limits)?;
    if let Some(expected) = &value.expected_component_digest {
        budget.string(expected, 71)?;
        expected
            .parse::<ArtifactBlobDigest>()
            .map_err(|_| invalid("invalid expected component digest"))?;
    }
    if value.encoded_len() > limits.max_request_bytes {
        return Err(super::super::bounds::exhausted());
    }
    if deployment
        .metadata
        .as_ref()
        .and_then(|metadata| metadata.tenant.as_deref())
        != Some(&tenant.0)
    {
        return Err(Status::permission_denied(
            "deployment tenant does not match authenticated scope",
        ));
    }
    if deployment.requested_publication.is_some() {
        return Err(invalid("requested_publication is output-only"));
    }
    let Some(selected) = &deployment.publication else {
        if value.expected_component_digest.is_some() {
            return Err(invalid(
                "a component assertion requires an explicit publication",
            ));
        }
        return Ok(value);
    };
    if !deployment.release_digest.is_empty() {
        return Err(invalid("exactly one publication selector is required"));
    }
    // Fixed additional ownership for the resolved component before the read.
    budget.allocation::<u8>(71)?;
    let scope = LifecycleScope::Tenant(tenant.clone());
    let reference = PublicationRef {
        id: selected
            .id
            .parse()
            .map_err(|_| invalid("invalid publication identity"))?,
        scope: scope.clone(),
    };
    let entry = repository
        .get_selected_catalog_entry(&scope, &PublicationSelector::Publication(reference.clone()))
        .await
        .map_err(|error| platform_status(error, &limits))?
        .ok_or_else(|| Status::not_found("publication not found"))?;
    if entry.tenant.as_ref() != Some(tenant)
        || entry.publication.as_ref() != Some(&reference.id)
        || entry
            .descriptor
            .release_digest
            .0
            .parse::<ArtifactBlobDigest>()
            .is_err()
    {
        return Err(Status::internal(
            "invalid deployment publication association",
        ));
    }
    if value
        .expected_component_digest
        .as_ref()
        .is_some_and(|expected| expected != &entry.descriptor.release_digest.0)
    {
        return Err(invalid(
            "publication does not match expected component digest",
        ));
    }
    value
        .deployment
        .as_mut()
        .expect("validated deployment")
        .release_digest = entry.descriptor.release_digest.0;
    Ok(value)
}

fn invalid(message: &'static str) -> Status {
    Status::invalid_argument(message)
}

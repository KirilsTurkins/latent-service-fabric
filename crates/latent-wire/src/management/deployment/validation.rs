use latent_control_store::VersionedDeployment;
use latent_core::TenantId;
use latent_manifest::{ManifestValidator, Phase1ManifestValidator};
use tonic::Status;

use super::super::{identifier, proto, ManagementLimits, RequestBudget};

pub(in crate::management) fn wire(
    deployment: &proto::Deployment,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    for value in [&deployment.id, &deployment.service] {
        id(value, budget, limits.max_id_bytes)?;
    }
    if !deployment.release_digest.is_empty() || deployment.publication.is_none() {
        id(
            &deployment.release_digest,
            budget,
            limits.max_id_bytes.max(71),
        )?;
    } else {
        budget.string(&deployment.release_digest, limits.max_id_bytes.max(71))?;
    }
    let metadata = deployment
        .metadata
        .as_ref()
        .ok_or_else(|| invalid("deployment metadata is required"))?;
    for reference in [&deployment.publication, &deployment.requested_publication]
        .into_iter()
        .flatten()
    {
        budget.allocation::<proto::PublicationRef>(1)?;
        id(
            &reference.id,
            budget,
            latent_core::PublicationId::TEXT_BYTES,
        )?;
        id(&reference.tenant, budget, limits.max_id_bytes)?;
        if metadata.tenant.as_deref() != Some(reference.tenant.as_str())
            || reference.id.parse::<latent_core::PublicationId>().is_err()
        {
            return Err(invalid("invalid deployment publication reference"));
        }
    }
    id(&metadata.name, budget, limits.max_id_bytes)?;
    for value in [metadata.tenant.as_ref(), metadata.namespace.as_ref()]
        .into_iter()
        .flatten()
    {
        id(value, budget, limits.max_id_bytes)?;
    }
    budget.metadata(&metadata.labels, limits)?;
    budget.metadata(&metadata.annotations, limits)?;
    budget.sequence(&deployment.grants, limits.max_collection_entries)?;
    for grant in &deployment.grants {
        id(&grant.capability, budget, limits.max_id_bytes)?;
        id(&grant.policy, budget, limits.max_id_bytes)?;
        strings(&grant.operations, budget, limits)?;
        budget.metadata(&grant.constraints, limits)?;
    }
    let placement = deployment
        .placement
        .as_ref()
        .ok_or_else(|| invalid("deployment placement is required"))?;
    id(&placement.trust_class, budget, limits.max_id_bytes)?;
    for values in [
        &placement.architectures,
        &placement.regions,
        &placement.zones,
        &placement.required_features,
    ] {
        strings(values, budget, limits)?;
    }
    if deployment.resources.is_none() || deployment.availability.is_none() {
        return Err(invalid(
            "deployment resources and availability are required",
        ));
    }
    Ok(())
}

/// Validate borrowed repository data before cloning it into a public response.
pub(super) fn domain(
    deployment: &VersionedDeployment,
    tenant: &TenantId,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    let manifest = &deployment.manifest;
    if manifest.publication.as_ref().is_some_and(|id| {
        Some(id)
            != deployment
                .publication
                .as_ref()
                .map(|reference| &reference.id)
    }) {
        return Err(Status::internal(
            "deployment publication association mismatch",
        ));
    }
    if let Some(reference) = &deployment.publication {
        if reference
            .scope
            .tenant()
            .is_some_and(|scope| scope != tenant)
            || (manifest.publication.is_some() && reference.scope.tenant().is_none())
        {
            return Err(Status::internal("deployment publication scope mismatch"));
        }
        budget.allocation::<u8>(reference.id.as_str().len())?;
        if let Some(scope) = reference.scope.tenant() {
            budget.allocation::<proto::PublicationRef>(1)?;
            budget.string(&scope.0, limits.max_id_bytes)?;
        }
    }
    if let Some(id) = &manifest.publication {
        budget.allocation::<proto::PublicationRef>(1)?;
        budget.allocation::<u8>(id.as_str().len())?;
        budget.string(&tenant.0, limits.max_id_bytes)?;
    }
    if manifest.metadata.tenant.as_ref() != Some(tenant) {
        return Err(Status::internal(
            "deployment repository returned an invalid scope",
        ));
    }
    budget.string(&manifest.api_version, limits.max_string_bytes)?;
    for value in [&manifest.id.0, &manifest.metadata.name, &manifest.service.0] {
        budget.string(value, limits.max_id_bytes)?;
    }
    budget.string(&manifest.release.0, limits.max_id_bytes.max(71))?;
    budget.optional_string(
        manifest.metadata.tenant.as_ref().map(|tenant| &tenant.0),
        limits.max_id_bytes,
    )?;
    budget.optional_string(manifest.metadata.namespace.as_ref(), limits.max_id_bytes)?;
    budget.btree_metadata(&manifest.metadata.labels, limits)?;
    budget.btree_metadata(&manifest.metadata.annotations, limits)?;
    budget.sequence(&manifest.grants, limits.max_collection_entries)?;
    for grant in &manifest.grants {
        budget.string(&grant.capability.0, limits.max_id_bytes)?;
        budget.string(&grant.policy.0, limits.max_id_bytes)?;
        bounded_strings(&grant.operations, budget, limits)?;
        budget.btree_metadata(&grant.constraints, limits)?;
    }
    budget.string(&manifest.placement.trust_class, limits.max_id_bytes)?;
    for values in [
        &manifest.placement.architectures,
        &manifest.placement.regions,
        &manifest.placement.zones,
        &manifest.placement.required_features,
    ] {
        bounded_strings(values, budget, limits)?;
    }
    Phase1ManifestValidator
        .validate_deployment(manifest)
        .map_err(|_| Status::internal("deployment repository returned an invalid manifest"))
}

pub(super) fn id(value: &String, budget: &mut RequestBudget, maximum: usize) -> Result<(), Status> {
    budget.string(value, maximum)?;
    identifier(value, maximum)
}

fn strings(
    values: &Vec<String>,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    bounded_strings(values, budget, limits)?;
    for value in values {
        identifier(value, limits.max_id_bytes)?;
    }
    Ok(())
}

fn bounded_strings(
    values: &Vec<String>,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    budget.sequence(values, limits.max_collection_entries)?;
    for value in values {
        budget.string(value, limits.max_id_bytes)?;
    }
    Ok(())
}

fn invalid(message: &'static str) -> Status {
    Status::invalid_argument(message)
}

use latent_control_store::VersionedDeployment;
use latent_core::{CapabilityId, DeploymentId, PolicyId, ReleaseDigest, ServiceId, TenantId};
use latent_manifest::{
    AvailabilityPolicy, CapabilityGrantSpec, DeploymentManifest, ObjectMetadata, PlacementPolicy,
    MANIFEST_API_VERSION,
};

use super::super::{proto, ManagementConversionError};
use super::budget::{control_budget_from_proto, control_budget_to_proto};

/// Lossless conversion of supported deployment fields, including object version.
/// Transport callers validate allocation and semantic limits before conversion.
pub fn deployment_from_proto(
    deployment: proto::Deployment,
) -> Result<VersionedDeployment, ManagementConversionError> {
    let metadata = deployment.metadata.ok_or_else(|| missing("metadata"))?;
    if deployment.id != metadata.name {
        return Err(ManagementConversionError::new(
            "id",
            "must equal metadata.name",
        ));
    }
    let resources = deployment.resources.ok_or_else(|| missing("resources"))?;
    let availability = deployment
        .availability
        .ok_or_else(|| missing("availability"))?;
    let placement = deployment.placement.ok_or_else(|| missing("placement"))?;
    let route_weight = u16::try_from(deployment.route_weight)
        .map_err(|_| ManagementConversionError::new("route_weight", "exceeds u16"))?;
    Ok(VersionedDeployment {
        generation: deployment.generation,
        manifest: DeploymentManifest {
            api_version: MANIFEST_API_VERSION.to_owned(),
            id: DeploymentId(deployment.id),
            metadata: ObjectMetadata {
                name: metadata.name,
                tenant: metadata.tenant.map(TenantId),
                namespace: metadata.namespace,
                labels: metadata.labels.into_iter().collect(),
                annotations: metadata.annotations.into_iter().collect(),
            },
            service: ServiceId(deployment.service),
            release: ReleaseDigest(deployment.release_digest),
            route_weight,
            grants: deployment
                .grants
                .into_iter()
                .map(|grant| CapabilityGrantSpec {
                    capability: CapabilityId(grant.capability),
                    policy: PolicyId(grant.policy),
                    operations: grant.operations,
                    constraints: grant.constraints.into_iter().collect(),
                })
                .collect(),
            resources: control_budget_from_proto(&resources),
            availability: AvailabilityPolicy {
                minimum_cached_copies: availability.minimum_cached_copies,
                minimum_zones: availability.minimum_zones,
            },
            placement: PlacementPolicy {
                trust_class: placement.trust_class,
                architectures: placement.architectures,
                regions: placement.regions,
                zones: placement.zones,
                required_features: placement.required_features,
            },
        },
    })
}

/// Apply input ignores the output-only generation; the request's independent
/// `expected_generation` is the sole caller version precondition.
pub fn deployment_manifest_from_proto(
    deployment: proto::Deployment,
) -> Result<DeploymentManifest, ManagementConversionError> {
    deployment_from_proto(deployment).map(|value| value.manifest)
}

/// Converts a bounded, supported manifest without erasing an unsupported API version.
pub fn deployment_to_proto(
    deployment: &VersionedDeployment,
) -> Result<proto::Deployment, ManagementConversionError> {
    let manifest = &deployment.manifest;
    if manifest.api_version != MANIFEST_API_VERSION {
        return Err(ManagementConversionError::new(
            "api_version",
            "unsupported version",
        ));
    }
    if manifest.id.0 != manifest.metadata.name {
        return Err(ManagementConversionError::new(
            "id",
            "must equal metadata.name",
        ));
    }
    Ok(proto::Deployment {
        id: manifest.id.0.clone(),
        metadata: Some(proto::ObjectMetadata {
            name: manifest.metadata.name.clone(),
            tenant: manifest
                .metadata
                .tenant
                .as_ref()
                .map(|tenant| tenant.0.clone()),
            namespace: manifest.metadata.namespace.clone(),
            labels: manifest
                .metadata
                .labels
                .iter()
                .map(|(key, value)| (key.clone(), value.clone()))
                .collect(),
            annotations: manifest
                .metadata
                .annotations
                .iter()
                .map(|(key, value)| (key.clone(), value.clone()))
                .collect(),
        }),
        service: manifest.service.0.clone(),
        release_digest: manifest.release.0.clone(),
        route_weight: u32::from(manifest.route_weight),
        grants: manifest
            .grants
            .iter()
            .map(|grant| proto::CapabilityGrant {
                capability: grant.capability.0.clone(),
                policy: grant.policy.0.clone(),
                operations: grant.operations.clone(),
                constraints: grant
                    .constraints
                    .iter()
                    .map(|(key, value)| (key.clone(), value.clone()))
                    .collect(),
            })
            .collect(),
        resources: Some(control_budget_to_proto(&manifest.resources)),
        availability: Some(proto::AvailabilityPolicy {
            minimum_cached_copies: manifest.availability.minimum_cached_copies,
            minimum_zones: manifest.availability.minimum_zones,
        }),
        placement: Some(proto::PlacementPolicy {
            trust_class: manifest.placement.trust_class.clone(),
            architectures: manifest.placement.architectures.clone(),
            regions: manifest.placement.regions.clone(),
            zones: manifest.placement.zones.clone(),
            required_features: manifest.placement.required_features.clone(),
        }),
        generation: deployment.generation,
    })
}

fn missing(field: &'static str) -> ManagementConversionError {
    ManagementConversionError::new(field, "required field is absent")
}

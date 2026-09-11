use latent_artifacts::{ArtifactCatalogEntry, ArtifactDescriptor};
use latent_core::{ArtifactReference, ContractId, PublisherId, ReleaseDigest, ServiceId, TenantId};

use super::super::{proto, ManagementConversionError};

/// Converts the Phase 1 catalog summary without inventing publication timestamps.
pub fn release_descriptor_to_proto(
    entry: ArtifactCatalogEntry,
) -> Result<proto::ReleaseDescriptor, ManagementConversionError> {
    if !entry.descriptor.layers.is_empty() {
        return Err(ManagementConversionError::new(
            "release.layers",
            "layered releases are outside Phase 1",
        ));
    }
    if entry
        .descriptor
        .publisher
        .as_ref()
        .is_some_and(|publisher| publisher.0.is_empty())
    {
        return Err(ManagementConversionError::new(
            "release.publisher",
            "present empty publisher is unrepresentable",
        ));
    }
    Ok(proto::ReleaseDescriptor {
        digest: entry.descriptor.release_digest.0,
        artifact_reference: entry.descriptor.reference.0,
        service: entry.service.0,
        semantic_version: entry.semantic_version,
        world: entry.world.0,
        publisher: entry
            .descriptor
            .publisher
            .map_or_else(String::new, |id| id.0),
        media_type: entry.descriptor.media_type,
        size_bytes: entry.descriptor.size_bytes,
        created_at_unix_millis: 0,
        admitted: true,
        annotations: entry.descriptor.annotations.into_iter().collect(),
        tenant: entry.tenant.map(|tenant| tenant.0),
    })
}

pub fn release_descriptor_from_proto(
    value: proto::ReleaseDescriptor,
) -> Result<ArtifactCatalogEntry, ManagementConversionError> {
    if value.created_at_unix_millis != 0 || !value.admitted {
        return Err(ManagementConversionError::new(
            "release",
            "unrepresentable Phase 1 receipt state",
        ));
    }
    Ok(ArtifactCatalogEntry {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference(value.artifact_reference),
            release_digest: ReleaseDigest(value.digest),
            media_type: value.media_type,
            size_bytes: value.size_bytes,
            publisher: (!value.publisher.is_empty()).then_some(PublisherId(value.publisher)),
            layers: Vec::new(),
            annotations: value.annotations.into_iter().collect(),
        },
        tenant: value.tenant.map(TenantId),
        service: ServiceId(value.service),
        semantic_version: value.semantic_version,
        world: ContractId(value.world),
    })
}

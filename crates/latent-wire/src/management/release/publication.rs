use std::collections::BTreeSet;

use latent_artifacts::{
    content_digest, decode_contract_metadata, ArtifactCatalogEntry, ArtifactDescriptor,
    CapsuleArtifact, ContractMetadataLimits,
};
use latent_core::{ArtifactReference, Metadata, ServiceId, TenantId};
use latent_manifest::{
    JsonManifestCodec, ManifestCodec, ManifestLimits, ManifestValidator, Phase1ManifestValidator,
};
use tonic::Status;

use super::super::{errors::platform_status, proto, ManagementLimits};

pub(super) fn prepare(
    request: proto::PublishReleaseRequest,
    tenant: &TenantId,
    limits: &ManagementLimits,
) -> Result<(CapsuleArtifact, ArtifactCatalogEntry), Status> {
    let upload = request.artifact.expect("validated upload");
    let codec = JsonManifestCodec::new(ManifestLimits {
        max_document_bytes: limits.max_manifest_bytes,
        max_string_bytes: limits.max_string_bytes,
        max_collection_entries: limits.max_collection_entries,
        ..ManifestLimits::default()
    });
    let manifest = codec
        .decode_capsule(&upload.capsule_manifest_json)
        .map_err(|_| Status::invalid_argument("invalid capsule manifest"))?;
    Phase1ManifestValidator
        .validate_capsule(&manifest)
        .map_err(|_| Status::invalid_argument("invalid Phase 1 capsule"))?;
    if manifest.metadata.tenant.as_ref() != Some(tenant) {
        return Err(Status::permission_denied(
            "capsule tenant does not match authenticated scope",
        ));
    }
    super::super::identifier(&manifest.metadata.name, limits.max_id_bytes)?;
    if upload.component_digest != manifest.component_digest.0 {
        return Err(Status::invalid_argument(
            "component and manifest digests disagree",
        ));
    }
    let contracts = decode_contract_metadata(
        &upload.contract_metadata_json,
        ContractMetadataLimits {
            max_document_bytes: limits.max_contract_metadata_bytes,
            max_retained_bytes: limits.max_request_bytes,
            max_string_bytes: limits.max_string_bytes,
            ..ContractMetadataLimits::default()
        },
    )
    .map_err(|error| platform_status(error, limits))?;
    if contracts.len() > limits.max_collection_entries {
        return Err(super::super::bounds::exhausted());
    }
    let mut ids = BTreeSet::new();
    for contract in &contracts {
        super::super::identifier(&contract.id.0, limits.max_string_bytes)?;
        if !ids.insert(&contract.id) {
            return Err(Status::invalid_argument("duplicate contract descriptor"));
        }
    }
    if manifest
        .exports
        .iter()
        .any(|export| !ids.contains(&export.contract))
    {
        return Err(Status::invalid_argument(
            "export contract metadata is required",
        ));
    }
    let annotations = annotations(request.release, &upload, &manifest, tenant)?;
    let digest = content_digest(&upload.component_bytes);
    if digest.0 != upload.component_digest {
        return Err(Status::data_loss("component content digest mismatch"));
    }
    let descriptor = ArtifactDescriptor {
        reference: ArtifactReference(format!("local:release:{}", digest.0)),
        release_digest: digest,
        media_type: upload.component_media_type,
        size_bytes: upload.component_bytes.len() as u64,
        publisher: None,
        layers: Vec::new(),
        annotations,
    };
    let summary = ArtifactCatalogEntry {
        descriptor: descriptor.clone(),
        tenant: manifest.metadata.tenant.clone(),
        service: ServiceId(manifest.metadata.name.clone()),
        semantic_version: manifest.semantic_version.clone(),
        world: manifest.world.clone(),
    };
    Ok((
        CapsuleArtifact {
            descriptor,
            manifest,
            contracts,
            component_bytes: upload.component_bytes,
        },
        summary,
    ))
}

fn annotations(
    claims: Option<proto::ReleaseDescriptor>,
    upload: &proto::CapsuleArtifactUpload,
    manifest: &latent_manifest::CapsuleManifest,
    tenant: &TenantId,
) -> Result<Metadata, Status> {
    Ok(if let Some(claims) = claims {
        let mismatch = [
            (&claims.digest, &upload.component_digest),
            (&claims.service, &manifest.metadata.name),
            (&claims.semantic_version, &manifest.semantic_version),
            (&claims.world, &manifest.world.0),
            (&claims.media_type, &upload.component_media_type),
        ]
        .into_iter()
        .any(|(claim, actual)| !claim.is_empty() && claim != actual)
            || (claims.size_bytes != 0 && claims.size_bytes != upload.component_bytes.len() as u64)
            || claims
                .tenant
                .as_ref()
                .is_some_and(|scope| scope != &tenant.0);
        if mismatch {
            return Err(Status::invalid_argument(
                "release claims disagree with the capsule",
            ));
        }
        claims.annotations.into_iter().collect()
    } else {
        Metadata::new()
    })
}

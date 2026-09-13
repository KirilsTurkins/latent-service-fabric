use latent_artifacts::{ArtifactCatalogEntry, ArtifactDescriptor};
use latent_core::TenantId;
use tonic::Status;

use super::super::{identifier, proto, ManagementLimits, RequestBudget};

pub(super) fn digest(
    value: &String,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    budget.string(value, limits.max_id_bytes.max(71))?;
    let valid = value.strip_prefix("sha256:").is_some_and(|hex| {
        hex.len() == 64
            && hex
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    });
    if !valid {
        return Err(Status::invalid_argument("invalid release digest"));
    }
    Ok(())
}

pub(super) fn publish(
    value: &proto::PublishReleaseRequest,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    let mut budget = RequestBudget::new::<proto::PublishReleaseRequest>(limits)?;
    super::lifecycle::operation(value.operation.as_ref(), &mut budget, limits, true)?;
    match (&value.artifact, &value.package) {
        (None, Some(package)) => {
            if value.release.is_some() {
                return Err(Status::invalid_argument(
                    "package admission forbids caller release claims",
                ));
            }
            return super::package::validate(package, &mut budget, limits);
        }
        (Some(_), None) => {}
        _ => {
            return Err(Status::invalid_argument(
                "exactly one release upload is required",
            ))
        }
    }
    let upload = value
        .artifact
        .as_ref()
        .ok_or_else(|| Status::invalid_argument("capsule upload is required"))?;
    budget.bytes(&upload.component_bytes, limits.max_component_bytes)?;
    budget.bytes(&upload.capsule_manifest_json, limits.max_manifest_bytes)?;
    budget.bytes(
        &upload.contract_metadata_json,
        limits.max_contract_metadata_bytes,
    )?;
    digest(&upload.component_digest, &mut budget, limits)?;
    budget.string(&upload.component_media_type, limits.max_string_bytes)?;
    if !matches!(
        upload.component_media_type.as_str(),
        "application/vnd.wasm.component.v1+wasm" | "application/wasm"
    ) {
        return Err(Status::invalid_argument("unsupported component media type"));
    }
    if upload.component_bytes.is_empty()
        || upload.capsule_manifest_json.is_empty()
        || upload.contract_metadata_json.is_empty()
    {
        return Err(Status::invalid_argument(
            "manifest, component, and contract metadata are required",
        ));
    }
    if let Some(release) = &value.release {
        for field in [
            &release.digest,
            &release.artifact_reference,
            &release.service,
            &release.semantic_version,
            &release.world,
            &release.publisher,
            &release.media_type,
        ] {
            budget.string(field, limits.max_string_bytes.max(85))?;
        }
        budget.optional_string(release.tenant.as_ref(), limits.max_id_bytes)?;
        budget.metadata(&release.annotations, limits)?;
        if !release.artifact_reference.is_empty()
            || !release.publisher.is_empty()
            || release.created_at_unix_millis != 0
            || release.admitted
        {
            return Err(Status::invalid_argument(
                "release authority fields are output-only",
            ));
        }
    }
    Ok(())
}

pub(super) fn entry(
    entry: &ArtifactCatalogEntry,
    tenant: &TenantId,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    if entry.tenant.as_ref() != Some(tenant) {
        return Err(Status::internal(
            "artifact repository returned a foreign release",
        ));
    }
    budget.string(
        &entry.tenant.as_ref().expect("matching tenant").0,
        limits.max_id_bytes,
    )?;
    for value in [&entry.semantic_version, &entry.world.0] {
        budget.string(value, limits.max_string_bytes.max(85))?;
        identifier(value, limits.max_string_bytes.max(85))?;
    }
    budget.string(&entry.service.0, limits.max_id_bytes)?;
    identifier(&entry.service.0, limits.max_id_bytes)?;
    descriptor(&entry.descriptor, budget, limits)
}

pub(super) fn descriptor(
    descriptor: &ArtifactDescriptor,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    digest(&descriptor.release_digest.0, budget, limits)?;
    for value in [&descriptor.reference.0, &descriptor.media_type] {
        budget.string(value, limits.max_string_bytes.max(85))?;
        identifier(value, limits.max_string_bytes.max(85))?;
    }
    if let Some(publisher) = &descriptor.publisher {
        budget.string(&publisher.0, limits.max_id_bytes)?;
        identifier(&publisher.0, limits.max_id_bytes)?;
    }
    if !descriptor.layers.is_empty() {
        return Err(Status::internal("layered release outside Phase 1"));
    }
    budget.allocation::<latent_artifacts::ArtifactLayer>(descriptor.layers.capacity())?;
    budget.btree_metadata(&descriptor.annotations, limits)
}

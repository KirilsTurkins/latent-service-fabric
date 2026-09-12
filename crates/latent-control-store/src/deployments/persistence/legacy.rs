//! Original two-tree/two-buffer serializer retained only as a differential oracle.

use super::{
    byte_limit, catalog_snapshot_value, corrupt, CompiledCatalog,
    DirectoryDeploymentRepositoryConfig, LimitedBytes, Payload, Record, StoredObjectGeneration,
};
use latent_artifacts::content_digest;
use latent_core::PlatformError;
use latent_manifest::{__serde::Serialize, __serde_json as json, JsonManifestCodec, ManifestCodec};

pub(super) fn encode(
    catalog: &CompiledCatalog,
    config: DirectoryDeploymentRepositoryConfig,
) -> Result<Vec<u8>, PlatformError> {
    let codec = JsonManifestCodec::default();
    let deployments = catalog
        .deployments
        .values()
        .map(|deployment| {
            let bytes = codec
                .encode_deployment(deployment)
                .map_err(super::super::manifest_error)?;
            json::from_slice(&bytes).map_err(|_| corrupt())
        })
        .collect::<Result<Vec<_>, PlatformError>>()?;
    let payload = Payload {
        generation: catalog.generation.0,
        generated_at_unix_millis: catalog.generated_at_unix_millis,
        deployments,
        snapshot: catalog_snapshot_value(catalog),
        object_generations: Some(
            catalog
                .versions
                .iter()
                .map(|(id, generation)| StoredObjectGeneration {
                    id: id.0.clone(),
                    generation: *generation,
                })
                .collect(),
        ),
        control: None,
    };
    let payload_bytes = bounded_json(&payload, config.max_state_bytes)?;
    let checksum = content_digest(&payload_bytes).0;
    drop(payload_bytes);
    let record = Record {
        format_version: 2,
        checksum,
        payload,
    };
    bounded_json(&record, config.max_state_bytes)
}

fn bounded_json<T: Serialize>(value: &T, limit: usize) -> Result<Vec<u8>, PlatformError> {
    let mut output = LimitedBytes {
        bytes: Vec::new(),
        limit,
    };
    json::to_writer(&mut output, value).map_err(|_| byte_limit())?;
    Ok(output.bytes)
}

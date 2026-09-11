use latent_artifacts::{content_digest, encode_contract_metadata, ContractMetadataLimits};
use latent_executor::ExecutionBackend;
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use serde_json::{json, Value};

use super::{platform, Case, MeasurementNode, MeasurementWriter, Result};

pub(super) fn write(node: &MeasurementNode, writer: &mut MeasurementWriter) -> Result<()> {
    let artifact = &node.fixtures.echo.artifact;
    let config = &node.runtime_config;
    let key = node
        .node
        .backend
        .preparation_key(&artifact.descriptor.release_digest)
        .map_err(platform)?;
    let manifest = JsonManifestCodec::default()
        .encode_capsule(&artifact.manifest)
        .map_err(|_| "measurement manifest encoding")?;
    let contracts =
        encode_contract_metadata(&artifact.contracts, ContractMetadataLimits::default())
            .map_err(platform)?;
    let (_, warm) = Case::Echo.request(node, "benchmark-input");
    let (_, first) = Case::FirstEcho.request(node, "benchmark-input");
    let budget = warm.budget.as_ref().ok_or("missing benchmark budget")?;
    writer.write("benchmark-input", &json!({
        "component_digest":artifact.descriptor.release_digest.0,"component_size_bytes":artifact.descriptor.size_bytes.to_string(),
        "manifest_sha256":content_digest(&manifest).0,"contract_metadata_sha256":content_digest(&contracts).0,
        "tenant":node.fixtures.echo.tenant,"service":node.fixtures.echo.service,
        "contract":node.fixtures.echo.contract,"function":"echo",
        "inputs":{"cold_first_rpc":payload(&first.payload),"warm_rpc":payload(&warm.payload)},
        "budget":{"cpu_fuel":budget.cpu_fuel.to_string(),"memory_bytes":budget.memory_bytes.to_string(),
            "wall_time_limit_millis":budget.wall_time_limit_millis.map(|value|value.to_string()),"log_bytes":budget.log_bytes.to_string()},
        "preparation_key":{"backend_id":node.node.backend.backend_id(),"engine_version":key.engine_version,
            "engine_configuration_digest":key.engine_configuration_digest,"target_triple":key.target_triple,"cpu_feature_set":key.cpu_feature_set},
        "backend_options":{"allocator":config.instance_allocator.name(),"copy_on_write":config.copy_on_write_images,
            "fuel_async_yield_interval":config.fuel_async_yield_interval.map(|value|value.to_string()),
            "maximum_wasm_stack_bytes":config.maximum_wasm_stack_bytes.to_string(),"async_stack_bytes":config.async_stack_bytes.to_string(),
            "hostcall_fuel":config.hostcall_fuel.to_string(),"prepared_cache_enabled":config.prepared_cache_enabled},
        "boundary_version":"wasmtime-component-call-includes-canonical-post-return-v1",
        "rpc_boundary":"persistent-loopback-tonic-invoke-round-trip-v1"
    }))?;
    Ok(())
}

fn payload(bytes: &[u8]) -> Value {
    json!({"payload_sha256":content_digest(bytes).0,"payload_byte_length":bytes.len().to_string(),
        "media_type":super::super::fixtures::MEDIA,"payload_utf8":std::str::from_utf8(bytes).expect("fixed UTF-8 echo frame")})
}

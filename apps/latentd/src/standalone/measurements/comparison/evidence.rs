use std::path::Path;

use latent_artifacts::{
    content_digest, encode_contract_metadata, CapsuleArtifact, ContractMetadataLimits,
};
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use latent_wasmtime::Phase0InvocationTiming;
use serde_json::{json, Value};

use super::super::{fixture_inputs::retain, fixtures::Fixture, platform};
use super::{node::Node, Result, INPUT};

pub(super) fn input() -> Value {
    json!({"utf8":INPUT,"sha256":content_digest(INPUT.as_bytes()).0,"bytes":INPUT.len().to_string()})
}

pub(super) fn validate_identity(identity: &Value, fixture: &Fixture) -> Result<()> {
    let rows = identity["fixtures"]
        .as_array()
        .filter(|rows| rows.len() == 1)
        .ok_or("comparison must identify exactly the loaded echo fixture")?;
    let row = &rows[0];
    let bytes = fixture.artifact.component_bytes.len().to_string();
    if row["name"] != "echo"
        || row["sha256"] != fixture.release_digest
        || row["bytes"].as_str() != Some(&bytes)
    {
        return Err("comparison loaded component identity mismatch".into());
    }
    Ok(())
}

pub(super) fn artifact(
    directory: &Path,
    fixture: &Fixture,
    published: &CapsuleArtifact,
) -> Result<Value> {
    let codec = JsonManifestCodec::default();
    let capsule = codec
        .encode_capsule(&published.manifest)
        .map_err(|_| "comparison capsule encoding")?;
    let contracts =
        encode_contract_metadata(&published.contracts, ContractMetadataLimits::default())
            .map_err(platform)?;
    let deployment = codec
        .encode_deployment(&fixture.deployment)
        .map_err(|_| "comparison deployment encoding")?;
    Ok(
        json!({"component_sha256":content_digest(&published.component_bytes).0,
        "component_bytes":published.component_bytes.len().to_string(),
        "stored_descriptor_reference":published.descriptor.reference.0,
        "capsule":retain(directory,"echo-capsule.json",&capsule)?,
        "contracts":retain(directory,"echo-contracts.json",&contracts)?,
        "deployment":retain(directory,"echo-deployment.json",&deployment)?}),
    )
}

pub(super) fn options(node: &Node) -> Value {
    let config = &node.runtime_config;
    json!({"cpu_fuel":"10000000000","memory_bytes":"16777216","wall_time_limit_millis":"1000","log_bytes":"16384",
        "pool_capacity":"2","queue_capacity":"3","runtime_workers":"2","control_workers":"1",
        "prepared_cache_maximum_entries":config.prepared_cache_maximum_entries.to_string(),
        "allocator":config.instance_allocator.name(),"copy_on_write":config.copy_on_write_images,
        "prepared_cache_enabled":config.prepared_cache_enabled,
        "fuel_async_yield_interval":config.fuel_async_yield_interval.map(|value|value.to_string()),
        "maximum_wasm_stack_bytes":config.maximum_wasm_stack_bytes.to_string(),
        "async_stack_bytes":config.async_stack_bytes.to_string(),"hostcall_fuel":config.hostcall_fuel.to_string()})
}

pub(super) fn timing(value: Phase0InvocationTiming) -> Value {
    json!({"backend_setup_micros":value.backend_setup_micros.to_string(),
        "guest_call_micros":value.guest_call_micros.to_string(),"host_call_micros":value.host_call_micros.to_string(),
        "host_call_count":value.host_call_count.to_string(),"component_post_return_micros":value.component_post_return_micros.to_string(),
        "activation_resource_reclamation_micros":value.activation_resource_reclamation_micros.to_string(),
        "outcome_classification_micros":value.outcome_classification_micros.to_string(),
        "reusable_proof_micros":value.reusable_proof_micros.to_string(),"backend_total_micros":value.backend_total_micros.to_string()})
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn semantic_input_is_the_exact_historical_targeted_echo_population() {
        let value = input();
        assert_eq!(value["bytes"], "25");
        assert_eq!(value["utf8"], "phase0 targeted warm echo");
        assert_eq!(
            value["sha256"],
            content_digest(b"phase0 targeted warm echo").0
        );
    }
}

use crate::{
    error::Failure,
    management::{canonical_digest, invalid_response, phase2::projection},
};
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use latent_rpc::control::v1 as proto;
use serde_json::{json, Value};
use tonic::metadata::MetadataMap;

pub(super) fn trigger(
    value: proto::Trigger,
    tenant: &str,
    id: Option<&str>,
) -> Result<Value, Failure> {
    if value.generation == 0
        || id.is_some_and(|expected| value.id != expected)
        || value
            .metadata
            .as_ref()
            .and_then(|metadata| metadata.tenant.as_deref())
            != Some(tenant)
    {
        return Err(invalid_response());
    }
    let generation = value.generation;
    let manifest =
        latent_wire::management::http_trigger_from_proto(value).map_err(|_| invalid_response())?;
    let bytes = JsonManifestCodec::default()
        .encode_trigger(&manifest)
        .map_err(|_| invalid_response())?;
    let manifest: Value = serde_json::from_slice(&bytes).map_err(|_| invalid_response())?;
    Ok(json!({"manifest":manifest,"generation":generation.to_string()}))
}

pub(super) fn receipt_scope(
    receipt: &proto::TriggerOperationReceipt,
    tenant: &str,
    operation: &str,
    trigger: Option<&str>,
) -> Result<(), Failure> {
    projection::checked(receipt, 4096)?;
    if receipt.tenant != tenant
        || receipt.operation_id != operation
        || trigger.is_some_and(|id| receipt.trigger_id != id)
    {
        return Err(invalid_response());
    }
    Ok(())
}

pub(super) fn durability(value: i32) -> Result<&'static str, Failure> {
    match proto::TriggerDurability::try_from(value) {
        Ok(proto::TriggerDurability::Confirmed) => Ok("confirmed"),
        Ok(proto::TriggerDurability::Uncertain) => Ok("uncertain"),
        _ => Err(invalid_response()),
    }
}

pub(in crate::management) fn page(
    value: &Option<String>,
    previous: Option<&String>,
    maximum: usize,
) -> Result<(), Failure> {
    if value.as_ref().is_some_and(|token| {
        token.is_empty()
            || token.capacity() > maximum
            || !token.is_ascii()
            || token.chars().any(char::is_control)
            || previous == Some(token)
    }) {
        return Err(invalid_response());
    }
    Ok(())
}

fn header<'value>(metadata: &'value MetadataMap, key: &str) -> Result<&'value str, Failure> {
    let value = metadata
        .get(key)
        .ok_or_else(invalid_response)?
        .to_str()
        .map_err(|_| invalid_response())?;
    if value.len() > 128 {
        return Err(invalid_response());
    }
    Ok(value)
}

fn counter(metadata: &MetadataMap, key: &str) -> Result<u64, Failure> {
    let value = header(metadata, key)?;
    let counter = value.parse::<u64>().map_err(|_| invalid_response())?;
    if counter.to_string() != value {
        return Err(invalid_response());
    }
    Ok(counter)
}

pub(super) fn deletion(
    metadata: &MetadataMap,
    operation: &proto::TriggerOperationPrecondition,
    generation: u64,
    id: &str,
) -> Result<Value, Failure> {
    let returned = metadata
        .get_bin("latent-trigger-operation-bin")
        .ok_or_else(invalid_response)?;
    if returned.as_encoded_bytes().len() > 172
        || returned
            .to_bytes()
            .map_err(|_| invalid_response())?
            .as_ref()
            != operation.operation_id.as_bytes()
    {
        return Err(invalid_response());
    }
    let digest = header(metadata, "latent-trigger-receipt")?;
    let state = counter(metadata, "latent-trigger-state")?;
    let actual_generation = counter(metadata, "latent-trigger-generation")?;
    let durability = header(metadata, "latent-trigger-durability")?;
    let replayed = match header(metadata, "latent-trigger-replayed")? {
        "true" => true,
        "false" => false,
        _ => return Err(invalid_response()),
    };
    if !canonical_digest(digest)
        || !matches!(durability, "confirmed" | "uncertain")
        || operation
            .expected_state_version
            .and_then(|value| value.checked_add(1))
            != Some(state)
        || generation.checked_add(1) != Some(actual_generation)
    {
        return Err(invalid_response());
    }
    Ok(
        json!({"triggerId":id,"operationId":operation.operation_id,"receiptDigest":digest,
        "stateVersion":state.to_string(),"generation":actual_generation.to_string(),
        "durability":durability,"replayed":replayed}),
    )
}

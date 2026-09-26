use super::{
    corrupt, invalid, TriggerOperationReceipt, TriggerOperationRequest, MAX_RECEIPT_BYTES,
};
use latent_core::PlatformError;
use latent_manifest::{__serde_json as json, JsonManifestCodec, ManifestCodec, TriggerManifest};

pub(crate) fn hash(bytes: &[u8]) -> String {
    crate::rollouts::codec::hash(bytes).as_str().to_owned()
}
pub(crate) fn manifest(value: &TriggerManifest) -> Result<String, PlatformError> {
    let bytes = JsonManifestCodec::default()
        .encode_trigger(value)
        .map_err(|_| invalid())?;
    if bytes.len() > super::MAX_DEFINITION_BYTES {
        return Err(super::capacity());
    }
    String::from_utf8(bytes).map_err(|_| invalid())
}
pub(crate) fn request_hash(
    value: &TriggerOperationRequest,
    definition: Option<&str>,
) -> Result<String, PlatformError> {
    let c = value.context();
    let data = json::json!({
        "domain":"lsf-http-trigger-operation-v1", "tenant":c.tenant.0, "actor":c.actor,
        "operationId":c.operation_id, "expectedStateVersion":c.expected_state_version,
        "expectedGeneration":value.expected_generation(), "id":value.id(), "definition":definition,
        "action":match value { TriggerOperationRequest::Apply {..} => "apply", TriggerOperationRequest::Delete {..} => "delete" }
    });
    Ok(hash(&crate::rollouts::codec::encode(
        &data,
        2 * super::MAX_DEFINITION_BYTES + 4096,
    )?))
}
pub(crate) fn receipt_hash(value: &TriggerOperationReceipt) -> Result<String, PlatformError> {
    let mut data = json::to_value(value).map_err(|_| corrupt())?;
    data.as_object_mut()
        .ok_or_else(corrupt)?
        .remove("receiptDigest");
    Ok(hash(&crate::rollouts::codec::encode(
        &data,
        MAX_RECEIPT_BYTES,
    )?))
}
impl TriggerOperationReceipt {
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, PlatformError> {
        crate::rollouts::codec::encode(self, MAX_RECEIPT_BYTES)
    }
}

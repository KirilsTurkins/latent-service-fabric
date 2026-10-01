//! Bounded original signed application requirements, never installation grants.
use base64::{engine::general_purpose::STANDARD, Engine};
use latent_core::{transaction_contract::Value, PlatformError};
use latent_effects::authority::DispatchCeiling;
use latent_manifest::TransactionBinding;
use serde::Deserialize;

pub(super) const PATH: &str = "deferred-http-requirements.json";
pub(super) const MAXIMUM_BYTES: usize = 8192;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Inputs {
    schema_version: String,
    scope: Scope,
    intent: Intent,
    adapter: Adapter,
    contract: Contract,
    ceiling: Ceiling,
    authority: Authority,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Scope {
    capsule: String,
    deployment: String,
    transaction_binding: String,
    namespace: String,
    companion_digest: String,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Intent {
    binding: String,
    operation: String,
    count: u32,
    requested_expiry_unix_millis: serde_json::Value,
    payload: Payload,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Payload {
    bytes: String,
    media_type: String,
    metadata: Vec<(String, String)>,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Adapter {
    name: String,
    intent_format: u32,
    payload_format: String,
    idempotency_profile: String,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Contract {
    retention_horizon_millis: String,
    maximum_body_bytes: usize,
    retry_delay_millis: String,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Ceiling {
    maximum_payload_bytes: String,
    maximum_response_bytes: String,
    maximum_attempts: u32,
    maximum_age_millis: String,
    attempt_timeout_millis: String,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Authority {
    installed: bool,
    rule_granted: bool,
    execution_qualified: bool,
}

pub(super) struct HttpRequirements {
    pub logical_binding: String,
    pub operation: String,
    pub count: u32,
    pub payload_digest: String,
    pub retention_horizon_millis: u64,
    pub maximum_body_bytes: usize,
    pub retry_delay_millis: u64,
    pub ceiling: DispatchCeiling,
}
impl HttpRequirements {
    pub fn decode(
        bytes: &[u8],
        companion: &TransactionBinding,
        companion_digest: &str,
    ) -> Result<Self, PlatformError> {
        if bytes.len() > MAXIMUM_BYTES {
            return Err(super::denied());
        }
        let input: Inputs = serde_json::from_slice(bytes).map_err(|_| super::denied())?;
        if input.schema_version != "latent.application.deferred-http-inputs.v1"
            || input.scope.capsule != companion.capsule
            || input.scope.deployment != companion.deployment
            || input.scope.transaction_binding != companion.binding
            || input.scope.namespace != companion.namespace
            || input.scope.companion_digest != companion_digest
            || input.adapter.name != "qualified-http-put-once-v1"
            || input.adapter.intent_format != 1
            || input.adapter.payload_format != "http-put-once-bytes-v1"
            || input.adapter.idempotency_profile != "retained-put-once-v1"
            || input.intent.operation != "put-once"
            || !(1..=128).contains(&input.intent.count)
            || input.intent.requested_expiry_unix_millis != serde_json::Value::Null
            || input.authority.installed
            || input.authority.rule_granted
            || input.authority.execution_qualified
        {
            return Err(super::denied());
        }
        latent_core::transaction_contract::identity(&input.intent.binding)
            .map_err(|_| super::denied())?;
        let payload = STANDARD
            .decode(&input.intent.payload.bytes)
            .map_err(|_| super::denied())?;
        if STANDARD.encode(&payload) != input.intent.payload.bytes
            || !input.intent.payload.metadata.is_empty()
            || input.intent.payload.media_type != "application/octet-stream"
            || !(1..=65_536).contains(&input.contract.maximum_body_bytes)
            || payload.len() > input.contract.maximum_body_bytes
        {
            return Err(super::denied());
        }
        let value = Value {
            bytes: payload,
            media_type: input.intent.payload.media_type,
            metadata: Vec::new(),
        };
        let selected = Self {
            logical_binding: input.intent.binding,
            operation: input.intent.operation,
            count: input.intent.count,
            payload_digest: latent_effects::payload::payload_digest(&value)
                .map_err(|_| super::denied())?,
            retention_horizon_millis: unsigned(&input.contract.retention_horizon_millis)?,
            maximum_body_bytes: input.contract.maximum_body_bytes,
            retry_delay_millis: unsigned(&input.contract.retry_delay_millis)?,
            ceiling: DispatchCeiling {
                maximum_payload_bytes: unsigned(&input.ceiling.maximum_payload_bytes)?,
                maximum_response_bytes: unsigned(&input.ceiling.maximum_response_bytes)?,
                maximum_attempts: input.ceiling.maximum_attempts,
                maximum_age_millis: unsigned(&input.ceiling.maximum_age_millis)?,
                attempt_timeout_millis: unsigned(&input.ceiling.attempt_timeout_millis)?,
            },
        };
        selected.validate(value.bytes.len())?;
        Ok(selected)
    }
    fn validate(&self, payload_bytes: usize) -> Result<(), PlatformError> {
        let c = self.ceiling;
        if !(1..=604_800_000).contains(&self.retention_horizon_millis)
            || !(1..=60_000).contains(&self.retry_delay_millis)
            || c.maximum_payload_bytes != self.maximum_body_bytes as u64
            || payload_bytes as u64 > c.maximum_payload_bytes
            || !(1024..=4096).contains(&c.maximum_response_bytes)
            || !(1..=16).contains(&c.maximum_attempts)
            || c.maximum_age_millis == 0
            || c.maximum_age_millis > self.retention_horizon_millis
            || c.attempt_timeout_millis == 0
            || c.attempt_timeout_millis > c.maximum_age_millis.min(300_000)
        {
            return Err(super::denied());
        }
        Ok(())
    }
}
fn unsigned(text: &str) -> Result<u64, PlatformError> {
    if text.is_empty()
        || text.len() > 20
        || (text.len() > 1 && text.starts_with('0'))
        || !text.bytes().all(|byte| byte.is_ascii_digit())
    {
        return Err(super::denied());
    }
    text.parse().map_err(|_| super::denied())
}

#[cfg(test)]
mod tests;

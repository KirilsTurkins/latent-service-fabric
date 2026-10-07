//! Closed original signed event requirements; declarations are not grants.
use latent_core::PlatformError;
use latent_effects::authority::DispatchCeiling;
use latent_manifest::TransactionBinding;
use serde::Deserialize;

pub(super) const PATH: &str = "deferred-event-requirements.json";
// The captured declaration uses the same finite reader as the existing signed
// HTTP effect requirements. Provider/engine and activation ceilings still apply.
pub(super) const MAXIMUM_BYTES: usize = super::effect_requirements::MAXIMUM_BYTES;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Inputs {
    schema_version: String,
    scope: Scope,
    intent: Intent,
    adapter: Adapter,
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
    state_schema: String,
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
#[serde(tag = "kind", rename_all = "kebab-case", deny_unknown_fields)]
enum Payload {
    #[serde(rename_all = "camelCase")]
    BoundedEventValue {
        maximum_bytes: usize,
        media_type: String,
        metadata: Metadata,
    },
}
#[derive(Deserialize)]
#[serde(rename_all = "kebab-case")]
enum Metadata {
    Empty,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Adapter {
    name: String,
    intent_format: u32,
    payload_format: String,
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

pub(super) struct EventRequirements {
    pub logical_binding: String,
    pub operation: String,
    pub count: u32,
    pub maximum_value_bytes: usize,
    pub media_type: String,
    pub ceiling: DispatchCeiling,
}
impl EventRequirements {
    pub fn decode(
        raw: &[u8],
        companion: &TransactionBinding,
        companion_digest: &str,
    ) -> Result<Self, PlatformError> {
        if raw.len() > MAXIMUM_BYTES {
            return Err(super::denied());
        }
        let input: Inputs = serde_json::from_slice(raw).map_err(|_| super::denied())?;
        if input.schema_version != "latent.application.deferred-event-inputs.v1"
            || input.scope.capsule != companion.capsule
            || input.scope.deployment != companion.deployment
            || input.scope.transaction_binding != companion.binding
            || input.scope.namespace != companion.namespace
            || input.scope.state_schema != companion.state_schema
            || input.scope.companion_digest != companion_digest
            || input.intent.operation != "event"
            || !(1..=latent_core::transaction_contract::DEFAULT_INTENTS)
                .contains(&input.intent.count)
            || input.intent.requested_expiry_unix_millis != serde_json::Value::Null
            || input.adapter.name != latent_nats::deferred::NATS_DEFERRED_PROFILE
            || input.adapter.intent_format != 1
            || input.adapter.payload_format != "nats-event-value-v1"
            || input.authority.installed
            || input.authority.rule_granted
            || input.authority.execution_qualified
        {
            return Err(super::denied());
        }
        latent_core::transaction_contract::identity(&input.intent.binding)
            .map_err(|_| super::denied())?;
        let Payload::BoundedEventValue {
            maximum_bytes,
            media_type,
            metadata: Metadata::Empty,
        } = input.intent.payload;
        latent_core::transaction_contract::Value {
            bytes: vec![],
            media_type: media_type.clone(),
            metadata: vec![],
        }
        .validate()
        .map_err(|_| super::denied())?;
        let unsigned = super::effect_requirements::unsigned;
        let ceiling = DispatchCeiling {
            maximum_payload_bytes: unsigned(&input.ceiling.maximum_payload_bytes)?,
            maximum_response_bytes: unsigned(&input.ceiling.maximum_response_bytes)?,
            maximum_attempts: input.ceiling.maximum_attempts,
            maximum_age_millis: unsigned(&input.ceiling.maximum_age_millis)?,
            attempt_timeout_millis: unsigned(&input.ceiling.attempt_timeout_millis)?,
        };
        // These application installation caps retain the existing HTTP effect
        // profile's 64 KiB/16-attempt bounds. The concrete NATS rule additionally
        // checks its configured payload ceiling and mandatory 16 KiB buffers;
        // actual host count/byte ledgers can narrow the signed declaration.
        if !(1..=65_536).contains(&maximum_bytes)
            || !(1..=65_536).contains(&ceiling.maximum_payload_bytes)
            || maximum_bytes as u64 > ceiling.maximum_payload_bytes
            || ceiling.maximum_response_bytes != 16_384
            || !(1..=16).contains(&ceiling.maximum_attempts)
            || ceiling.maximum_age_millis == 0
            || ceiling.maximum_age_millis > 86_400_000
            || ceiling.attempt_timeout_millis == 0
            || ceiling.attempt_timeout_millis > ceiling.maximum_age_millis.min(60_000)
        {
            return Err(super::denied());
        }
        Ok(Self {
            logical_binding: input.intent.binding,
            operation: input.intent.operation,
            count: input.intent.count,
            maximum_value_bytes: maximum_bytes,
            media_type,
            ceiling,
        })
    }
}

#[cfg(test)]
mod tests;

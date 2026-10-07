//! Additional closed payload constraints; these grant no staging permission.
use super::{denied, PolicyCallBinding};
use latent_capabilities::broker::{events::EVENTS_CAPABILITY, ProviderReference};
use latent_core::{transaction_contract::Value, PlatformError};

#[derive(Clone)]
enum Constraint {
    ExactDigest(String),
    EventValue {
        provider: ProviderReference,
        maximum_bytes: usize,
        media_type: String,
    },
}

/// Produced by the installed signed declaration and actual provider closure.
/// The private variant cannot be selected by a guest field or caller descriptor.
/// Current namespace/policy checks and original host ledgers remain mandatory.
#[derive(Clone)]
pub struct IntentPayloadConstraint(Constraint);
impl IntentPayloadConstraint {
    #[must_use]
    pub fn exact_digest(digest: String) -> Self {
        Self(Constraint::ExactDigest(digest))
    }

    pub fn bounded_event(
        provider: ProviderReference,
        maximum_bytes: usize,
        media_type: String,
    ) -> Result<Self, PlatformError> {
        if provider.capability() != EVENTS_CAPABILITY
            || provider.profile() != "nats-jetstream-publish-v1"
            || !(1..=65_536).contains(&maximum_bytes)
            || provider.configuration_epoch() == 0
        {
            return Err(denied());
        }
        Value {
            bytes: vec![],
            media_type: media_type.clone(),
            metadata: vec![],
        }
        .validate()
        .map_err(|_| denied())?;
        Ok(Self(Constraint::EventValue {
            provider,
            maximum_bytes,
            media_type,
        }))
    }

    pub(super) fn require_binding(&self, binding: &PolicyCallBinding) -> Result<(), PlatformError> {
        match &self.0 {
            Constraint::ExactDigest(value)
                // Payload identity uses the maintained effect digest format;
                // prefixed artifact/provider digests are a different contract.
                if value.len() != 64
                    || !value
                        .bytes()
                        .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f')) =>
            {
                return Err(denied())
            }
            Constraint::EventValue { provider, .. }
                if binding.profile != "nats-jetstream-effect-v1"
                    || binding.configuration_digest != provider.configuration_digest()
                    || binding.configuration_epoch != provider.configuration_epoch() =>
            {
                return Err(denied())
            }
            _ => (),
        }
        Ok(())
    }

    pub(super) fn check(
        &self,
        binding: &PolicyCallBinding,
        value: &Value,
    ) -> Result<(), PlatformError> {
        self.require_binding(binding)?;
        value.validate().map_err(|_| denied())?;
        match &self.0 {
            Constraint::ExactDigest(expected) => {
                if &latent_effects::payload::payload_digest(value).map_err(|_| denied())?
                    != expected
                {
                    return Err(denied());
                }
            }
            Constraint::EventValue {
                provider,
                maximum_bytes,
                media_type,
            } => {
                if binding.profile != "nats-jetstream-effect-v1"
                    || binding.configuration_digest != provider.configuration_digest()
                    || binding.configuration_epoch != provider.configuration_epoch()
                    || value.bytes.len() > *maximum_bytes
                    || value.media_type != *media_type
                    || !value.metadata.is_empty()
                {
                    return Err(denied());
                }
            }
        }
        Ok(())
    }
}

#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod tests;

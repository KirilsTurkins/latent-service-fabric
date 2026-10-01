//! Exact native installation pins. These declarations never enable a rule.
use latent_core::PlatformError;
use serde::Deserialize;

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DeferredHttpConfig {
    pub requirements_digest: String,
    pub provider_id: String,
    pub provider_incarnation: String,
    pub credential_reference: String,
    pub staging_binding: String,
    pub staging_policies: Vec<String>,
    pub dispatch_binding: String,
    pub dispatch_policies: Vec<String>,
}

pub(super) fn present<'de, D: serde::Deserializer<'de>>(
    source: D,
) -> Result<Option<DeferredHttpConfig>, D::Error> {
    DeferredHttpConfig::deserialize(source).map(Some)
}
impl DeferredHttpConfig {
    pub(super) fn validate(&self) -> Result<(), PlatformError> {
        super::checked_digest(&self.requirements_digest)?;
        if self.provider_incarnation.len() != 64
            || !self
                .provider_incarnation
                .bytes()
                .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
        {
            return Err(super::super::invalid(
                "state.deferredHttp.providerIncarnation",
            ));
        }
        for text in [
            &self.provider_id,
            &self.credential_reference,
            &self.staging_binding,
            &self.dispatch_binding,
        ] {
            super::checked_identity(text)?;
        }
        for policies in [&self.staging_policies, &self.dispatch_policies] {
            if policies.is_empty() || policies.len() > 8 {
                return Err(super::super::invalid("state.deferredHttp.policies"));
            }
            for (index, policy) in policies.iter().enumerate() {
                super::checked_identity(policy)?;
                if policies[..index].contains(policy) {
                    return Err(super::super::invalid("state.deferredHttp.policies"));
                }
            }
        }
        Ok(())
    }
}

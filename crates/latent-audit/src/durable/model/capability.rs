//! Closed, redacted facts captured by the trusted capability broker/provider.
//! These records and their wire projections confer no execution authority.
use super::super::{codec, invalid, Result};
use latent_core::ArtifactBlobDigest;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum AuditCapabilityResourceClass {
    Context,
    Clock,
    Random,
    Log,
    Http,
    Blob,
    Secrets,
    Events,
    Telemetry,
    Service,
}

/// Evidence of a particular provider boundary, never universal delivery or
/// consumer processing. Unknown is also used after cancellation without evidence.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum AuditProviderOutcome {
    NotStarted,
    LocalDispatchAccepted,
    HttpResponseReceived,
    BrokerAcknowledged,
    BlobSealed,
    SecretResolved,
    HostCompleted,
    Rejected,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum AuditCapabilityDigestScope {
    ResourceSelection,
    ProviderRequest,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AuditCapabilityRequestDigest {
    pub scope: AuditCapabilityDigestScope,
    #[serde(with = "codec::text")]
    pub digest: ArtifactBlobDigest,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AuditCapabilityRevision {
    pub id: String,
    pub revision: u64,
    #[serde(with = "codec::text")]
    pub digest: ArtifactBlobDigest,
}
impl AuditCapabilityRevision {
    fn validate(&self) -> Result<()> {
        codec::token(&self.id, 128)?;
        if self.revision == 0 {
            return Err(invalid());
        }
        Ok(())
    }
}

/// The outer record carries the authenticated tenant/actor and exact source
/// publication, component, deployment, revision, and lifecycle generation.
/// Resource selectors (including secret names), claims, and payloads are absent.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AuditCapabilityContext {
    pub activation: String,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "codec::present"
    )]
    pub parent_activation: Option<String>,
    pub root_activation: String,
    pub service: String,
    #[serde(with = "codec::text")]
    pub binding_definition_digest: ArtifactBlobDigest,
    pub binding: AuditCapabilityRevision,
    pub policies: Vec<AuditCapabilityRevision>,
    pub provider_profile: String,
    #[serde(with = "codec::text")]
    pub provider_configuration_digest: ArtifactBlobDigest,
    pub provider_configuration_epoch: u64,
    pub capability: String,
    pub operation: String,
    pub resource_class: AuditCapabilityResourceClass,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "codec::present"
    )]
    pub request: Option<AuditCapabilityRequestDigest>,
    pub required: bool,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "codec::present"
    )]
    pub provider_outcome: Option<AuditProviderOutcome>,
}

impl AuditCapabilityContext {
    /// Check the evidence class, without asserting that the operation occurred.
    #[must_use]
    pub fn accepts_outcome(&self, outcome: AuditProviderOutcome) -> bool {
        use AuditCapabilityResourceClass as R;
        match outcome {
            AuditProviderOutcome::NotStarted
            | AuditProviderOutcome::Unknown
            | AuditProviderOutcome::Rejected => true,
            AuditProviderOutcome::LocalDispatchAccepted => {
                self.resource_class == R::Service && self.operation == "call"
            }
            AuditProviderOutcome::HttpResponseReceived => self.resource_class == R::Http,
            AuditProviderOutcome::BrokerAcknowledged => {
                self.resource_class == R::Events && self.operation == "publish"
            }
            AuditProviderOutcome::BlobSealed => {
                self.resource_class == R::Blob && self.operation == "seal"
            }
            AuditProviderOutcome::SecretResolved => {
                self.resource_class == R::Secrets && self.operation == "read"
            }
            AuditProviderOutcome::HostCompleted => matches!(
                self.resource_class,
                R::Context | R::Clock | R::Random | R::Log | R::Telemetry
            ),
        }
    }
    pub(in crate::durable) fn validate(&self) -> Result<()> {
        for value in [
            &self.activation,
            &self.root_activation,
            &self.service,
            &self.provider_profile,
        ] {
            codec::token(value, 128)?;
        }
        if let Some(parent) = &self.parent_activation {
            codec::token(parent, 128)?;
        }
        self.binding.validate()?;
        if self.policies.is_empty()
            || self.policies.len() > 8
            || self.provider_configuration_epoch == 0
            || self.parent_activation.as_ref() == Some(&self.activation)
        {
            return Err(invalid());
        }
        for (index, policy) in self.policies.iter().enumerate() {
            policy.validate()?;
            if self.policies[..index].iter().any(|old| old.id == policy.id) {
                return Err(invalid());
            }
        }
        latent_core::PHASE3_HOST_ABI_CURRENT
            .interface(&self.capability)
            .ok_or_else(invalid)?;
        codec::token(&self.operation, 64)?;
        let expected = match self.resource_class {
            AuditCapabilityResourceClass::Context => "latent:context/",
            AuditCapabilityResourceClass::Clock => "latent:clock/",
            AuditCapabilityResourceClass::Random => "latent:random/",
            AuditCapabilityResourceClass::Log => "latent:log/",
            AuditCapabilityResourceClass::Http => "latent:http/",
            AuditCapabilityResourceClass::Blob => "latent:blob/",
            AuditCapabilityResourceClass::Secrets => "latent:secrets/",
            AuditCapabilityResourceClass::Events => "latent:events/",
            AuditCapabilityResourceClass::Telemetry => "latent:telemetry/",
            AuditCapabilityResourceClass::Service => "latent:service/",
        };
        if !self.capability.starts_with(expected)
            || self
                .provider_outcome
                .is_some_and(|outcome| !self.accepts_outcome(outcome))
        {
            return Err(invalid());
        }
        Ok(())
    }
}

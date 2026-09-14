use super::{capacity, invalid};
use latent_capabilities::broker::ProviderReference;
use latent_core::{DeploymentId, PlatformError, ServiceId, TenantId};
use latent_manifest::{
    __serde::{Deserialize, Serialize},
    BindingManifest, BindingMode, JsonManifestCodec, ManifestCodec, ManifestValidator,
    Phase1ManifestValidator,
};
use latent_policy::capability::GrantRestriction;

/// A desired binding plus explicit physical-mode narrowing. The provider policy
/// names the independently installed configuration; this document grants none.
#[derive(Debug, Clone)]
pub struct BindingDefinition {
    pub manifest: BindingManifest,
    pub provider_binding_id: String,
    pub allowed_modes: Vec<BindingMode>,
    pub restriction_json: Vec<u8>,
}
/// Trusted node installation facts. Local mode names one exact deployment row,
/// whose publication/revision is captured during every route compilation.
pub struct ConfiguredBindingProvider {
    pub tenant: TenantId,
    pub service: ServiceId,
    pub reference: ProviderReference,
    pub local_deployment: Option<DeploymentId>,
}
impl ConfiguredBindingProvider {
    pub(super) fn mode(&self) -> BindingMode {
        if self.local_deployment.is_some() {
            BindingMode::IsolatedLocal
        } else {
            BindingMode::Host
        }
    }
}
/// Hard ceilings for the initial managed binding profile; independent of the
/// larger unconfigured Phase 1 route index. Callers may lower these bounds.
#[derive(Debug, Clone, Copy)]
pub struct BindingLimits {
    pub maximum_definitions: usize,
    pub maximum_deployments: usize,
    pub maximum_providers: usize,
    pub maximum_graph_depth: usize,
    pub maximum_retained_generations: usize,
    pub maximum_definition_bytes: usize,
    pub maximum_package_bytes: usize,
    pub maximum_metadata_bytes: usize,
}
impl Default for BindingLimits {
    fn default() -> Self {
        Self {
            maximum_definitions: 256,
            // Default broker capacity admits a current and a tentative catalog.
            // Additional retained pins still consume its finite shared quota.
            maximum_deployments: 128,
            maximum_providers: 128,
            maximum_graph_depth: 16,
            maximum_retained_generations: 16,
            maximum_definition_bytes: 64 * 1024,
            maximum_package_bytes: 32 * 1024 * 1024,
            maximum_metadata_bytes: 8 * 1024 * 1024,
        }
    }
}
impl BindingLimits {
    pub(super) fn validate(self) -> Result<(), PlatformError> {
        let hard = Self::default();
        macro_rules! fields { ($($field:ident),+) => { $(
            if self.$field == 0 || self.$field > hard.$field { return Err(invalid()); }
        )+ }; }
        fields!(
            maximum_definitions,
            maximum_deployments,
            maximum_providers,
            maximum_graph_depth,
            maximum_retained_generations,
            maximum_definition_bytes,
            maximum_package_bytes,
            maximum_metadata_bytes
        );
        Ok(())
    }
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde", deny_unknown_fields)]
pub(in crate::deployments) struct StoredBinding {
    pub manifest: String,
    pub provider_binding_id: String,
    pub allowed_modes: Vec<BindingMode>,
    pub restriction: String,
}
impl StoredBinding {
    pub(super) fn encode(
        input: BindingDefinition,
        limits: BindingLimits,
    ) -> Result<Self, PlatformError> {
        let raw = JsonManifestCodec::default()
            .encode_binding(&input.manifest)
            .map_err(|_| invalid())?;
        if raw.len() > limits.maximum_definition_bytes
            || input.restriction_json.len() > limits.maximum_definition_bytes
        {
            return Err(capacity());
        }
        let restriction =
            GrantRestriction::parse(&input.restriction_json, &input.manifest.consumer.contract.0)?;
        let value = Self {
            manifest: String::from_utf8(raw).map_err(|_| invalid())?,
            provider_binding_id: input.provider_binding_id,
            allowed_modes: input.allowed_modes,
            restriction: latent_manifest::__serde_json::to_string(&restriction)
                .map_err(|_| invalid())?,
        };
        value.decode(limits)?;
        Ok(value)
    }
    pub(super) fn decode(&self, limits: BindingLimits) -> Result<BindingDefinition, PlatformError> {
        if self.manifest.len() > limits.maximum_definition_bytes
            || self.restriction.len() > limits.maximum_definition_bytes
        {
            return Err(capacity());
        }
        if !token(&self.provider_binding_id)
            || self.allowed_modes.is_empty()
            || self.allowed_modes.len() > 2
            || self
                .allowed_modes
                .iter()
                .any(|m| !matches!(m, BindingMode::Host | BindingMode::IsolatedLocal))
            || (self.allowed_modes.len() == 2 && self.allowed_modes[0] == self.allowed_modes[1])
        {
            return Err(invalid());
        }
        let manifest = JsonManifestCodec::default()
            .decode_binding(self.manifest.as_bytes())
            .map_err(|_| invalid())?;
        Phase1ManifestValidator
            .validate_binding(&manifest)
            .map_err(|_| invalid())?;
        if matches!(manifest.mode, BindingMode::Inline | BindingMode::Remote)
            || (manifest.mode != BindingMode::Auto && !self.allowed_modes.contains(&manifest.mode))
            || manifest.consumer.contract != manifest.provider.contract
        {
            return Err(invalid());
        }
        GrantRestriction::parse(self.restriction.as_bytes(), &manifest.consumer.contract.0)?;
        Ok(BindingDefinition {
            manifest,
            provider_binding_id: self.provider_binding_id.clone(),
            allowed_modes: self.allowed_modes.clone(),
            restriction_json: self.restriction.as_bytes().to_vec(),
        })
    }
    pub(super) fn retained_bytes(&self) -> usize {
        256 + self.manifest.capacity()
            + self.provider_binding_id.capacity()
            + self.restriction.capacity()
            + self.allowed_modes.capacity() * std::mem::size_of::<BindingMode>()
    }
}
pub(super) fn token(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 256
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"-_.:/@".contains(&b))
}

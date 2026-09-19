use std::path::{Path, PathBuf};

use latent_control_store::bindings::BindingDefinition;
use latent_core::{BudgetProfile, PlatformError};
use latent_manifest::{BindingMode, JsonManifestCodec, ManifestCodec};
use serde::{Deserialize, Deserializer};

use super::{invalid, NodeConfig};

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ConfiguredProviders {
    pub format_version: u32,
    #[serde(default, deserialize_with = "present")]
    pub http: Option<HttpInstallation>,
    #[serde(default, deserialize_with = "present")]
    pub blob: Option<BlobInstallation>,
    pub bindings: Vec<HostBinding>,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProviderIdentity {
    pub id: String,
    pub tenant: String,
    pub service: String,
    pub epoch: u64,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HttpInstallation {
    pub identity: ProviderIdentity,
    pub configuration: latent_http::HttpProviderConfig,
    #[serde(default, deserialize_with = "present")]
    pub credential_directory: Option<PathBuf>,
    #[serde(default)]
    pub credentials: Vec<ProviderSecretFile>,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProviderSecretFile {
    pub reference: String,
    pub file: String,
    pub destination: usize,
    pub header: String,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BlobInstallation {
    pub identity: ProviderIdentity,
    pub namespace: String,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HostBinding {
    pub name: String,
    pub tenant: String,
    pub consumer_service: String,
    pub provider_service: String,
    pub contract: String,
    pub provider_binding: String,
    #[serde(default, deserialize_with = "present")]
    pub route: Option<String>,
}

pub(super) fn present<'de, Document: Deserialize<'de>, Input: Deserializer<'de>>(
    input: Input,
) -> Result<Option<Document>, Input::Error> {
    Document::deserialize(input).map(Some)
}

pub(super) fn derive(config: &NodeConfig) -> Result<Option<ConfiguredProviders>, PlatformError> {
    let Some(providers) = &config.providers else {
        return Ok(None);
    };
    if !config.credentials_from_protected_file
        || !cfg!(all(target_os = "linux", target_arch = "x86_64"))
        || config.capability_policies.is_none()
        || config.audit.is_none()
        || config.budget_profile.profile() != BudgetProfile::Phase3
        || providers.format_version != 1
        || (providers.http.is_none() && providers.blob.is_none())
        || providers.bindings.is_empty()
        || providers.bindings.capacity() > 16
    {
        return Err(invalid("providers"));
    }
    if let Some(http) = &providers.http {
        http.identity.validate()?;
        http.configuration
            .validate()
            .map_err(|_| invalid("providers.http"))?;
        if http.credentials.capacity() > 8
            || http.credential_directory.is_some() == http.credentials.is_empty()
        {
            return Err(invalid("providers.http.credentials"));
        }
        for (index, credential) in http.credentials.iter().enumerate() {
            if !token(&credential.reference, 128)
                || !token(&credential.file, 128)
                || credential.file.contains(['/', '\\', ':'])
                || matches!(credential.file.as_str(), "." | "..")
                || !token(&credential.header, 64)
                || credential.destination >= http.configuration.destinations.len()
                || http.credentials[..index].iter().any(|previous| {
                    previous.reference == credential.reference
                        || previous.destination == credential.destination
                })
            {
                return Err(invalid("providers.http.credentials"));
            }
        }
    }
    if let Some(blob) = &providers.blob {
        blob.identity.validate()?;
        if !token(&blob.namespace, 128) {
            return Err(invalid("providers.blob.namespace"));
        }
        if providers.http.as_ref().is_some_and(|http| {
            http.identity.id == blob.identity.id
                || (http.identity.tenant == blob.identity.tenant
                    && http.identity.service == blob.identity.service)
        }) {
            return Err(invalid("providers.identity"));
        }
    }
    providers.definitions()?;
    Ok(Some(providers.clone()))
}

impl ProviderIdentity {
    fn validate(&self) -> Result<(), PlatformError> {
        if !token(&self.id, 128)
            || !token(&self.tenant, 128)
            || !token(&self.service, 128)
            || self.epoch == 0
            || self.id.contains(['/', '\\', ':'])
            || matches!(self.id.as_str(), "." | "..")
        {
            return Err(invalid("providers.identity"));
        }
        Ok(())
    }
}

impl ConfiguredProviders {
    pub(crate) fn definitions(&self) -> Result<Vec<BindingDefinition>, PlatformError> {
        self.bindings.iter().enumerate().map(|(index, binding)| {
            if [&binding.name, &binding.tenant, &binding.consumer_service,
                &binding.provider_service, &binding.provider_binding, &binding.contract]
                .iter().any(|value| !token(value, 128))
                || binding.route.as_ref().is_some_and(|route| !token(route, 128))
                || self.bindings[..index].iter().any(|previous| {
                    previous.tenant == binding.tenant && previous.name == binding.name
                })
            {
                return Err(invalid("providers.bindings"));
            }
            let installed = match binding.contract.as_str() {
                "latent:http/client@0.2.0" => self.http.as_ref().map(|http| &http.identity),
                "latent:blob/blob@0.2.0" => self.blob.as_ref().map(|blob| &blob.identity),
                _ => None,
            }.ok_or_else(|| invalid("providers.bindings.contract"))?;
            if installed.tenant != binding.tenant || installed.service != binding.provider_service {
                return Err(invalid("providers.bindings.scope"));
            }
            let mut consumer = serde_json::json!({"service":binding.consumer_service,"contract":binding.contract});
            if let Some(route) = &binding.route {
                consumer["route"] = serde_json::json!(route);
            }
            let document = serde_json::json!({"apiVersion":latent_manifest::MANIFEST_API_VERSION,
                "kind":"Binding","metadata":{"name":binding.name,"tenant":binding.tenant},
                "spec":{"consumer":consumer,"provider":{"service":binding.provider_service,
                    "contract":binding.contract},"mode":"host"}});
            let bytes = serde_json::to_vec(&document).map_err(|_| invalid("providers.bindings"))?;
            Ok(BindingDefinition {
                manifest: JsonManifestCodec::default().decode_binding(&bytes)
                    .map_err(|_| invalid("providers.bindings"))?,
                provider_binding_id: binding.provider_binding.clone(),
                allowed_modes: vec![BindingMode::Host],
                restriction_json: br#"{"operations":[]}"#.to_vec(),
            })
        }).collect()
    }
}

pub(super) fn anchor(config: &mut ConfiguredProviders, parent: &Path) -> Result<(), PlatformError> {
    if let Some(directory) = config
        .http
        .as_mut()
        .and_then(|http| http.credential_directory.as_mut())
    {
        if directory.as_os_str().is_empty() || directory.as_os_str().len() > 4096 {
            return Err(invalid("providers.http.credentialDirectory"));
        }
        if directory.is_relative() {
            *directory = parent
                .canonicalize()
                .map_err(|_| invalid("configurationPath"))?
                .join(&*directory);
        }
    }
    Ok(())
}

fn token(value: &String, maximum: usize) -> bool {
    !value.is_empty()
        && value.capacity() <= maximum
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"-_.:/@".contains(&byte))
}

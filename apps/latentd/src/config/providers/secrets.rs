use std::path::{Component, Path, PathBuf};

use latent_core::PlatformError;
use serde::Deserialize;

use super::{invalid, present, token, ProviderIdentity};

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SecretInstallation {
    pub identity: ProviderIdentity,
    pub directory: PathBuf,
    pub references: Vec<GuestSecretFile>,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct GuestSecretFile {
    pub reference: String,
    pub file: String,
    #[serde(default, deserialize_with = "present")]
    pub expires_at_unix_millis: Option<u64>,
}

impl SecretInstallation {
    pub(super) fn validate(&self) -> Result<(), PlatformError> {
        self.identity.validate()?;
        if !self.directory.is_absolute()
            || self.directory.capacity() > 4096
            || self
                .directory
                .components()
                .any(|p| matches!(p, Component::ParentDir))
            || self.references.is_empty()
            || self.references.capacity() > 8
        {
            return Err(invalid("providers.secrets"));
        }
        for (index, entry) in self.references.iter().enumerate() {
            if !token(&entry.reference, 128)
                || entry.file.is_empty()
                || entry.file.capacity() > 128
                || matches!(entry.file.as_str(), "." | "..")
                || !entry
                    .file
                    .bytes()
                    .all(|v| v.is_ascii_alphanumeric() || b"._-".contains(&v))
                || self.references[..index]
                    .iter()
                    .any(|old| old.reference == entry.reference || old.file == entry.file)
            {
                return Err(invalid("providers.secrets.references"));
            }
        }
        Ok(())
    }

    pub(super) fn anchor(&mut self, parent: &Path) -> Result<(), PlatformError> {
        if self.directory.as_os_str().is_empty() || self.directory.as_os_str().len() > 4096 {
            return Err(invalid("providers.secrets.directory"));
        }
        if self.directory.is_relative() {
            self.directory = parent
                .canonicalize()
                .map_err(|_| invalid("configurationPath"))?
                .join(&self.directory);
        }
        Ok(())
    }
}

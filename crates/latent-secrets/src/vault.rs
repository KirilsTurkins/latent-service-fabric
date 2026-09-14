//! Explicit KV-v2 references, bounded shared plaintext and checked disclosure.
mod config;
mod json;
mod memory;
mod provider;

use crate::SecretError;
pub use config::{VaultConfig, VaultEncoding, VaultLimits, VaultReference};
pub use provider::{VaultSecretProvider, VaultSnapshot, VAULT_SECRETS_PROFILE};
type Result<T> = std::result::Result<T, SecretError>;

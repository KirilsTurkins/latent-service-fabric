//! Explicit KV-v2 references, bounded shared plaintext and checked disclosure.
#![forbid(unsafe_code)]
#![cfg(all(target_os = "linux", target_arch = "x86_64"))]

mod config;
mod json;
mod memory;
mod provider;

pub use config::{VaultConfig, VaultEncoding, VaultLimits, VaultReference};
pub use latent_capabilities::broker::secrets::SecretError;
pub use provider::{VaultSecretProvider, VaultSnapshot, VAULT_SECRETS_PROFILE};
type Result<T> = std::result::Result<T, SecretError>;

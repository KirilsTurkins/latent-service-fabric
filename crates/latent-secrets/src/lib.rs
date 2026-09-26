//! Linux operator-owned secret generations. Guests receive only explicitly
//! granted values; provider authentication bindings never implement guest reads.
#![forbid(unsafe_code)]

pub use latent_capabilities::broker::secrets::SecretError;

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod config;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod environment;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod provider;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod store;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub use config::{SecretLimits, SecretPurpose, SecretSource, SecretSpec};
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub use provider::{LocalSecretProvider, LOCAL_SECRETS_PROFILE};
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub use store::{LocalSecretStore, SecretClock, SecretSnapshot, SystemSecretClock};

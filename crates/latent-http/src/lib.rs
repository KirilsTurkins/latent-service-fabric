//! One shared configured HTTP provider. No ambient network or credential authority.
#![forbid(unsafe_code)]
mod config;
mod credentials;
mod destination;
mod dns;
mod execute;
mod headers;
mod network;
mod provider;
pub use config::{
    HttpAddressPolicy, HttpDestination, HttpLimits, HttpProviderConfig, HttpResolution,
};
pub use credentials::HttpCredential;
use latent_capabilities::broker::http::HttpError;
pub use provider::{HttpProvider, HTTP_PROVIDER_PROFILE};

#[cfg(test)]
mod tests;

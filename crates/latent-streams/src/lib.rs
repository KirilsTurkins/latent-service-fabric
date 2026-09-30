//! Qualification-only bounded outbound TCP; production enablement is ADR-gated.
#![forbid(unsafe_code)]

mod config;
mod connection;
mod lifecycle;
mod provider;

pub use config::{StreamDestination, StreamLimits, StreamProviderConfig, StreamResolution};
pub use latent_capabilities::broker::network::{StreamError, StreamErrorCode};
pub use lifecycle::{StreamLifecycle, StreamStatus};
pub use provider::StreamProvider;

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StreamUsage {
    pub owners: usize,
    pub connections: usize,
    pub pending_operations: usize,
    pub retained_chunks: usize,
    pub accepted_write_bytes: u64,
    pub delivered_read_bytes: u64,
    pub retired: bool,
}

fn error(code: StreamErrorCode) -> StreamError {
    StreamError::new(code)
}
#[cfg(test)]
mod tests;

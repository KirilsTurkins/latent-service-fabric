//! Qualification-only bounded outbound TCP; production enablement is ADR-gated.
#![forbid(unsafe_code)]

mod config;
mod connection;
mod lifecycle;
mod maintenance;
mod provider;

pub use config::{StreamDestination, StreamLimits, StreamProviderConfig, StreamResolution};
pub use latent_capabilities::broker::network::{StreamError, StreamErrorCode};
pub use lifecycle::{StreamLifecycle, StreamStatus};
pub use maintenance::{StreamMaintenance, StreamMaintenanceStop};
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

fn inspection_unavailable(_: StreamError) -> latent_core::PlatformError {
    latent_core::PlatformError {
        code: latent_core::PlatformErrorCode::ResourceExhausted,
        message: "outbound-stream-inspection-unavailable".into(),
        retryable: false,
        details: Vec::new(),
    }
}
#[cfg(test)]
mod tests;

//! Shared TLS `JetStream` publication; no detached driver or automatic replay.
#![forbid(unsafe_code)]
mod config;
mod network;
mod protocol;
mod provider;
mod request;
pub mod triggers;
pub use config::{NatsConfig, NatsEndpoint, TopicMapping};
pub use latent_capabilities::broker::events::EventError;
pub use provider::{NatsCredential, NatsPublisher, NatsSnapshot, NATS_PUBLISH_PROFILE};
type Result<T> = std::result::Result<T, EventError>;

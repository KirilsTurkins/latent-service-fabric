//! WIT-native remote invocation abstractions placed behind an LSF transport seam.

#![forbid(unsafe_code)]

use latent_activation::{ActivationEnvelope, ActivationOutcome};
use latent_core::{BoxFuture, Metadata, NodeId, PlatformError};
use latent_wire::DuplexChannel;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NodeEndpoint {
    pub node: NodeId,
    pub authority: String,
    pub transport: String,
    pub identity: String,
    pub attributes: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RemoteInvocationReceipt {
    pub accepted_by: NodeId,
    pub transport_request_id: String,
    pub accepted_at_unix_millis: u64,
}

pub trait RemoteInvocationClient: Send + Sync {
    fn invoke<'a>(
        &'a self,
        endpoint: &'a NodeEndpoint,
        activation: ActivationEnvelope,
    ) -> BoxFuture<'a, ActivationOutcome>;
}

pub trait RemoteInvocationHandler: Send + Sync {
    fn handle<'a>(&'a self, activation: ActivationEnvelope) -> BoxFuture<'a, ActivationOutcome>;
}

pub trait RemoteInvocationServer: Send + Sync {
    fn serve<'a>(
        &'a self,
        channel: &'a dyn DuplexChannel,
        handler: &'a dyn RemoteInvocationHandler,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;
}

pub trait NodeConnectionFactory: Send + Sync {
    fn connect<'a>(
        &'a self,
        endpoint: &'a NodeEndpoint,
    ) -> BoxFuture<'a, Result<Box<dyn DuplexChannel>, PlatformError>>;
}

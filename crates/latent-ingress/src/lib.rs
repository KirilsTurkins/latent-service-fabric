//! Shared ingress protocol adaptation, identity extraction, and invocation routing interfaces.

#![forbid(unsafe_code)]

/// Versioned, bounded inbound HTTP application mapping and ownership.
pub mod http;

use latent_activation::{ActivationEnvelope, ActivationOutcome};
use latent_core::{BoxFuture, InvocationPrincipal, Metadata, PlatformError};
use latent_identity::{AuthenticationContext, PresentedCredential};
use latent_triggers::TriggerEvent;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IngressProtocol {
    Http,
    DirectRpc,
    Event,
    Queue,
    Timer,
    Blob,
    Internal,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IngressRequest {
    pub protocol: IngressProtocol,
    pub authority: Option<String>,
    pub path_or_topic: String,
    pub method_or_operation: String,
    pub headers: Metadata,
    pub payload: Vec<u8>,
    pub media_type: String,
    pub credential: Option<PresentedCredential>,
    pub authentication_context: AuthenticationContext,
    pub received_at_unix_millis: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IngressResponse {
    pub status: u16,
    pub headers: Metadata,
    pub payload: Vec<u8>,
    pub media_type: String,
}

pub trait PrincipalExtractor: Send + Sync {
    fn extract<'a>(
        &'a self,
        request: &'a IngressRequest,
    ) -> BoxFuture<'a, Result<InvocationPrincipal, PlatformError>>;
}

pub trait IngressAdapter: Send + Sync {
    fn protocol(&self) -> IngressProtocol;

    fn to_activation(
        &self,
        request: IngressRequest,
        principal: InvocationPrincipal,
    ) -> BoxFuture<'_, Result<ActivationEnvelope, PlatformError>>;

    #[expect(
        clippy::wrong_self_convention,
        reason = "retain the existing public adapter method name"
    )]
    fn from_outcome(&self, outcome: ActivationOutcome) -> Result<IngressResponse, PlatformError>;
}

pub trait IngressRouter: Send + Sync {
    fn route(
        &self,
        request: IngressRequest,
    ) -> BoxFuture<'_, Result<IngressResponse, PlatformError>>;

    fn route_trigger(&self, event: TriggerEvent) -> BoxFuture<'_, ActivationOutcome>;
}

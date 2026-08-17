//! Authentication, authorization, delegation, and workload-identity interfaces.

#![forbid(unsafe_code)]

use latent_core::{
    BoxFuture, InvocationPrincipal, Metadata, NodeId, PlatformError, ServiceId, TenantId,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PresentedCredential {
    pub scheme: String,
    pub bytes: Vec<u8>,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuthenticationContext {
    pub transport_peer: Option<String>,
    pub tenant_hint: Option<TenantId>,
    pub service_hint: Option<ServiceId>,
    pub attributes: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuthorizationRequest {
    pub principal: InvocationPrincipal,
    pub action: String,
    pub resource: String,
    pub attributes: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuthorizationDecision {
    pub allowed: bool,
    pub reason: String,
    pub obligations: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DelegationToken {
    pub issuer: String,
    pub subject: InvocationPrincipal,
    pub audience: String,
    pub operations: Vec<String>,
    pub expires_at_unix_millis: u64,
    pub bytes: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NodeIdentity {
    pub node: NodeId,
    pub workload_identity: String,
    pub certificate_chain: Vec<Vec<u8>>,
    pub expires_at_unix_millis: u64,
}

pub trait Authenticator: Send + Sync {
    fn authenticate<'a>(
        &'a self,
        credential: &'a PresentedCredential,
        context: &'a AuthenticationContext,
    ) -> BoxFuture<'a, Result<InvocationPrincipal, PlatformError>>;
}

pub trait Authorizer: Send + Sync {
    fn authorize<'a>(
        &'a self,
        request: AuthorizationRequest,
    ) -> BoxFuture<'a, Result<AuthorizationDecision, PlatformError>>;
}

pub trait DelegationIssuer: Send + Sync {
    fn issue<'a>(
        &'a self,
        principal: &'a InvocationPrincipal,
        audience: &'a str,
        operations: &'a [String],
        ttl_millis: u64,
    ) -> BoxFuture<'a, Result<DelegationToken, PlatformError>>;

    fn verify<'a>(
        &'a self,
        token: &'a DelegationToken,
        audience: &'a str,
    ) -> BoxFuture<'a, Result<InvocationPrincipal, PlatformError>>;
}

pub trait NodeIdentityProvider: Send + Sync {
    fn current<'a>(&'a self) -> BoxFuture<'a, Result<NodeIdentity, PlatformError>>;
    fn rotate<'a>(&'a self) -> BoxFuture<'a, Result<NodeIdentity, PlatformError>>;
}

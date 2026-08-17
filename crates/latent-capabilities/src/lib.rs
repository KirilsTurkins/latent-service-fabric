//! Capability grants, activation-scoped handles, providers, and broker interfaces.

#![forbid(unsafe_code)]

use latent_core::{
    ActivationId, BoxFuture, CapabilityHandleId, CapabilityId, ContractId, Metadata, Payload,
    PlatformError, PolicyId, ProviderId,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CapabilityDescriptor {
    pub id: CapabilityId,
    pub contract: ContractId,
    pub provider: ProviderId,
    pub operations: Vec<String>,
    pub attributes: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CapabilityGrant {
    pub capability: CapabilityId,
    pub policy: PolicyId,
    pub operations: Vec<String>,
    pub constraints: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CapabilityBindingRequest {
    pub activation_id: ActivationId,
    pub grant: CapabilityGrant,
    pub requested_contract: ContractId,
    pub attributes: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CapabilityHandle {
    pub id: CapabilityHandleId,
    pub activation_id: ActivationId,
    pub capability: CapabilityId,
    pub provider: ProviderId,
    pub expires_at_unix_millis: Option<u64>,
    pub attributes: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CapabilityCall {
    pub handle: CapabilityHandleId,
    pub operation: String,
    pub payload: Payload,
    pub payload_media_type: String,
    pub deadline_unix_millis: Option<u64>,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CapabilityResponse {
    pub payload: Payload,
    pub payload_media_type: String,
    pub metadata: Metadata,
}

pub trait CapabilityProvider: Send + Sync {
    fn descriptor(&self) -> &CapabilityDescriptor;

    fn bind<'a>(
        &'a self,
        request: CapabilityBindingRequest,
    ) -> BoxFuture<'a, Result<CapabilityHandle, PlatformError>>;

    fn invoke<'a>(
        &'a self,
        call: CapabilityCall,
    ) -> BoxFuture<'a, Result<CapabilityResponse, PlatformError>>;

    fn release<'a>(
        &'a self,
        handle: CapabilityHandle,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;
}

pub trait CapabilityBroker: Send + Sync {
    fn bind<'a>(
        &'a self,
        request: CapabilityBindingRequest,
    ) -> BoxFuture<'a, Result<CapabilityHandle, PlatformError>>;

    fn invoke<'a>(
        &'a self,
        call: CapabilityCall,
    ) -> BoxFuture<'a, Result<CapabilityResponse, PlatformError>>;

    fn release_activation<'a>(
        &'a self,
        activation_id: &'a ActivationId,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;
}

pub trait CapabilityRegistry: Send + Sync {
    fn get(&self, id: &CapabilityId) -> Option<&dyn CapabilityProvider>;
    fn list(&self) -> Vec<CapabilityDescriptor>;
}

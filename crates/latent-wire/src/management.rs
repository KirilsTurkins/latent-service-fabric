//! Bounded standalone management adapters over the local catalogs and inventory.

mod authentication;
mod bounds;
mod deployment;
mod errors;
mod inspection;
mod inventory;
mod limits;
mod release;
mod routes;

use std::fmt;
use std::sync::Arc;

use latent_artifacts::ArtifactRepository;
use latent_control_store::{CompiledRouteStore, DeploymentStore};
use latent_core::{ActivationClock, InvocationPrincipal, PlatformError};
use latent_node::InventoryReporter;
use prost::Message;
use tonic::{Request, Response, Status};

use crate::invocation::PrincipalPolicy;

pub use authentication::{LocalManagementPolicy, ManagementOperation, ManagementPolicy};
use bounds::{identifier, RequestBudget};
pub use deployment::{
    control_budget_from_proto, control_budget_to_proto, deployment_from_proto,
    deployment_manifest_from_proto, deployment_to_proto,
};
pub use inventory::{node_inventory_from_proto, node_inventory_to_proto};
pub use latent_rpc::control::v1 as proto;
pub use limits::ManagementLimits;
pub use release::{release_descriptor_from_proto, release_descriptor_to_proto};

/// All services share existing node-owned state. The adapter opens no listener.
#[derive(Clone)]
pub struct ManagementServices {
    pub artifacts: Arc<dyn ArtifactRepository>,
    pub deployments: Arc<dyn DeploymentStore>,
    pub routes: Arc<dyn CompiledRouteStore>,
    pub inventory: Arc<dyn InventoryReporter>,
    pub principals: Arc<dyn PrincipalPolicy>,
    pub authorization: Arc<dyn ManagementPolicy>,
    pub clock: Arc<dyn ActivationClock>,
}

#[derive(Clone)]
pub struct ManagementServiceAdapter {
    services: ManagementServices,
    limits: ManagementLimits,
}

impl ManagementServiceAdapter {
    pub fn new(
        services: ManagementServices,
        limits: ManagementLimits,
    ) -> Result<Self, PlatformError> {
        limits.validate()?;
        Ok(Self { services, limits })
    }

    #[must_use]
    pub const fn limits(&self) -> &ManagementLimits {
        &self.limits
    }

    fn authenticate<T>(
        &self,
        request: &mut Request<T>,
        operation: ManagementOperation,
    ) -> Result<InvocationPrincipal, Status> {
        let context = crate::invocation::take_context(
            request,
            &self.limits.auth,
            self.services.principals.as_ref(),
        )?;
        self.services
            .authorization
            .authorize(context.principal(), operation)
            .map_err(|error| errors::platform_status(error, &self.limits))?;
        Ok(context.into_principal())
    }

    /// Call after bounded traversal, so `encoded_len` cannot inspect an unbounded map.
    fn check_encoded<T: Message>(&self, message: &T) -> Result<(), Status> {
        if message.encoded_len() > self.limits.max_request_bytes {
            return Err(bounds::exhausted());
        }
        Ok(())
    }

    fn response<T: Message>(&self, message: T) -> Result<Response<T>, Status> {
        if message.encoded_len() > self.limits.max_response_bytes {
            return Err(bounds::exhausted());
        }
        Ok(Response::new(message))
    }

    #[must_use]
    pub fn release_server(self) -> proto::release_service_server::ReleaseServiceServer<Self> {
        let input = self.limits.max_request_bytes;
        let output = self.limits.max_response_bytes;
        proto::release_service_server::ReleaseServiceServer::new(self)
            .max_decoding_message_size(input)
            .max_encoding_message_size(output)
    }

    #[must_use]
    pub fn deployment_server(
        self,
    ) -> proto::deployment_service_server::DeploymentServiceServer<Self> {
        let input = self.limits.max_request_bytes;
        let output = self.limits.max_response_bytes;
        proto::deployment_service_server::DeploymentServiceServer::new(self)
            .max_decoding_message_size(input)
            .max_encoding_message_size(output)
    }

    #[must_use]
    pub fn route_server(self) -> proto::route_service_server::RouteServiceServer<Self> {
        let input = self.limits.max_request_bytes;
        let output = self.limits.max_response_bytes;
        proto::route_service_server::RouteServiceServer::new(self)
            .max_decoding_message_size(input)
            .max_encoding_message_size(output)
    }

    #[must_use]
    pub fn node_server(self) -> proto::node_service_server::NodeServiceServer<Self> {
        let input = self.limits.max_request_bytes;
        let output = self.limits.max_response_bytes;
        proto::node_service_server::NodeServiceServer::new(self)
            .max_decoding_message_size(input)
            .max_encoding_message_size(output)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ManagementConversionError {
    pub field: &'static str,
    pub reason: &'static str,
}

impl ManagementConversionError {
    #[must_use]
    pub const fn new(field: &'static str, reason: &'static str) -> Self {
        Self { field, reason }
    }
}

impl fmt::Display for ManagementConversionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {}", self.field, self.reason)
    }
}

impl std::error::Error for ManagementConversionError {}

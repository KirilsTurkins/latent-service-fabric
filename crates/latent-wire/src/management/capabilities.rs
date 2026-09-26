//! Scoped diagnostic RPCs on the bounded policy control owner. No grant minting.
mod conversion;
mod page;
mod reads;

use super::{
    policies::{conversion::finish, validation},
    proto, ManagementServiceAdapter, PolicyResponseService,
};
use latent_capabilities::broker::{
    diagnostics::CapabilityInspectionSource, ActivationCapabilityBroker,
};
use latent_core::{PlatformError, PlatformErrorCode};
use std::sync::Arc;
use tonic::{Request, Response, Status};

const MAX_REQUEST_BYTES: usize = 8 * 1024;
const MAX_RESPONSE_BYTES: usize = 128 * 1024;
#[derive(Clone)]
pub(super) struct Inspection {
    source: Arc<dyn CapabilityInspectionSource>,
    broker: Arc<ActivationCapabilityBroker>,
}
impl ManagementServiceAdapter {
    pub fn with_capability_inspection(
        mut self,
        source: Arc<dyn CapabilityInspectionSource>,
        broker: Arc<ActivationCapabilityBroker>,
    ) -> Result<Self, PlatformError> {
        if self.capabilities.is_some()
            || self
                .policies
                .as_ref()
                .is_none_or(|p| !broker.policy_owner_matches(p.store()))
        {
            return Err(PlatformError {
                code: PlatformErrorCode::InvalidArgument,
                message: "capability-inspection-owner-mismatch".into(),
                retryable: false,
                details: Vec::new(),
            });
        }
        self.capabilities = Some(Inspection { source, broker });
        Ok(self)
    }
    #[must_use]
    pub fn capability_server(
        self,
    ) -> PolicyResponseService<proto::capability_service_server::CapabilityServiceServer<Self>>
    {
        let input = self.limits.max_request_bytes.min(MAX_REQUEST_BYTES);
        let output = self.limits.max_response_bytes.min(MAX_RESPONSE_BYTES);
        PolicyResponseService::new(
            proto::capability_service_server::CapabilityServiceServer::new(self)
                .max_decoding_message_size(input)
                .max_encoding_message_size(output),
        )
    }
    fn capability_inspection(&self) -> Result<Inspection, Status> {
        self.capabilities
            .clone()
            .ok_or_else(|| Status::unimplemented("capability-inspection-unavailable"))
    }
}
#[tonic::async_trait]
impl proto::capability_service_server::CapabilityService for ManagementServiceAdapter {
    async fn list_capabilities(
        &self,
        request: Request<proto::ListCapabilitiesRequest>,
    ) -> Result<Response<proto::ListCapabilitiesResponse>, Status> {
        reads::list(self, request).await
    }
    async fn explain_capability_grant(
        &self,
        request: Request<proto::ExplainCapabilityGrantRequest>,
    ) -> Result<Response<proto::ExplainCapabilityGrantResponse>, Status> {
        reads::explain(self, request).await
    }
}

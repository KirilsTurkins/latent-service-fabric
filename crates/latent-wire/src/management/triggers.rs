//! Tenant HTTP trigger management over the existing catalog and control runtime.
mod conversion;
mod response;
#[cfg(all(test, unix))]
mod tests;
mod validation;
use super::{
    control_audit, errors::platform_status, proto, DeploymentResponseService, ManagementOperation,
    ManagementServiceAdapter,
};
use latent_control_store::{
    http_routes::{TriggerOperationCommit, TriggerOperationRequest, TriggerRead},
    DirectoryDeploymentRepository,
};
use latent_core::{PlatformError, PlatformErrorCode, TriggerId};
use latent_rollout::trigger_audit::ManagedTriggerAudit;
use std::{sync::Arc, time::Instant};
use tonic::{Request, Response, Status};

pub fn http_trigger_from_proto(
    value: proto::Trigger,
) -> Result<latent_manifest::TriggerManifest, Status> {
    let limits = super::ManagementLimits::default();
    let mut budget = super::RequestBudget::new::<proto::Trigger>(&limits)?;
    validation::wire(&value, &mut budget, &limits)?;
    latent_control_store::http_routes::normalize_http_trigger(conversion::manifest(value)?)
        .map_err(|_| Status::invalid_argument("invalid-http-trigger"))
}

pub fn http_trigger_to_proto(
    manifest: latent_manifest::TriggerManifest,
    generation: u64,
) -> Result<proto::Trigger, PlatformError> {
    let manifest = latent_control_store::http_routes::normalize_http_trigger(manifest)?;
    Ok(conversion::manifest_to_proto(manifest, generation))
}

impl ManagementServiceAdapter {
    pub fn with_http_control(
        mut self,
        catalog: Arc<DirectoryDeploymentRepository>,
    ) -> Result<Self, PlatformError> {
        let deployments: Arc<dyn latent_control_store::DeploymentStore> = catalog.clone();
        let routes: Arc<dyn latent_control_store::CompiledRouteStore> = catalog.clone();
        if self.http.is_some()
            || !Arc::ptr_eq(&deployments, &self.services.deployments)
            || !Arc::ptr_eq(&routes, &self.services.routes)
        {
            return Err(PlatformError {
                code: PlatformErrorCode::InvalidArgument,
                message: "http-control-catalog-owner-mismatch".into(),
                retryable: false,
                details: Vec::new(),
            });
        }
        self.http = Some(catalog);
        Ok(self)
    }
    #[must_use]
    pub fn trigger_server(
        self,
    ) -> DeploymentResponseService<proto::trigger_service_server::TriggerServiceServer<Self>> {
        let input = self.limits.max_request_bytes.min(64 * 1024);
        let output = self.limits.max_response_bytes;
        DeploymentResponseService::new(
            proto::trigger_service_server::TriggerServiceServer::new(self)
                .max_decoding_message_size(input)
                .max_encoding_message_size(output),
        )
    }
    fn trigger_store(&self) -> Result<&DirectoryDeploymentRepository, Status> {
        self.http
            .as_deref()
            .ok_or_else(|| Status::unimplemented("HTTP trigger control is not configured"))
    }
}

#[tonic::async_trait]
impl proto::trigger_service_server::TriggerService for ManagementServiceAdapter {
    async fn apply_trigger(
        &self,
        mut request: Request<proto::ApplyTriggerRequest>,
    ) -> Result<Response<proto::ApplyTriggerResponse>, Status> {
        let expires = validation::deadline(&request);
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        let store = self.trigger_store()?;
        let _request_lease = store
            .reserve_trigger_request()
            .map_err(|e| platform_status(e, &self.limits))?;
        let command = validation::apply(request.into_inner(), principal, &self.limits)?;
        let (result, ack) = execute(self, command, expires).await?;
        let (value, lease) = result.into_parts();
        let output = response::apply(value, ack)?;
        response::finish(self, output, lease, expires)
            .map(|r| control_audit::response(r, ack))
            .map_err(|e| control_audit::status(e, ack))
    }
    async fn delete_trigger(
        &self,
        mut request: Request<proto::DeleteTriggerRequest>,
    ) -> Result<Response<proto::Empty>, Status> {
        let expires = validation::deadline(&request);
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        let store = self.trigger_store()?;
        let _request_lease = store
            .reserve_trigger_request()
            .map_err(|e| platform_status(e, &self.limits))?;
        let command = validation::delete(request.into_inner(), principal, &self.limits)?;
        let (result, ack) = execute(self, command, expires).await?;
        let (value, lease) = result.into_parts();
        let mut output = response::finish(self, proto::Empty {}, lease, expires)
            .map_err(|e| control_audit::status(e, ack))?;
        response::delete_metadata(output.metadata_mut(), &value);
        Ok(control_audit::response(output, ack))
    }
    async fn get_trigger(
        &self,
        mut request: Request<proto::GetTriggerRequest>,
    ) -> Result<Response<proto::GetTriggerResponse>, Status> {
        let expires = validation::deadline(&request);
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        let tenant = validation::tenant(&principal)?;
        validation::read_id(&request.get_ref().id, &self.limits)?;
        self.check_encoded(request.get_ref())?;
        validation::completed(expires)?;
        let result = self
            .trigger_store()?
            .get_trigger(&tenant, &TriggerId(request.into_inner().id))
            .map_err(|e| platform_status(e, &self.limits))?;
        let (value, lease) = result.into_parts();
        let output = proto::GetTriggerResponse {
            trigger: value.trigger.map(conversion::trigger),
            state_version: value.state_version,
            route_generation: value.route_generation.0,
            durability: response::durability(value.confirmed),
        };
        response::finish(self, output, lease, expires)
    }
    async fn list_triggers(
        &self,
        mut request: Request<proto::ListTriggersRequest>,
    ) -> Result<Response<proto::ListTriggersResponse>, Status> {
        let expires = validation::deadline(&request);
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        let tenant = validation::tenant(&principal)?;
        let page = validation::page(request.into_inner(), tenant, &self.limits)?;
        validation::completed(expires)?;
        let result = self
            .trigger_store()?
            .list_triggers(&page)
            .map_err(|e| platform_status(e, &self.limits))?;
        let (value, lease) = result.into_parts();
        let output = proto::ListTriggersResponse {
            triggers: value
                .triggers
                .into_iter()
                .map(conversion::trigger)
                .collect(),
            page: Some(proto::PageResponse {
                next_page_token: value.next_page_token,
            }),
            state_version: value.state_version,
            route_generation: value.route_generation.0,
        };
        response::finish(self, output, lease, expires)
    }
    async fn get_trigger_operation(
        &self,
        mut request: Request<proto::GetTriggerOperationRequest>,
    ) -> Result<Response<proto::GetTriggerOperationResponse>, Status> {
        let expires = validation::deadline(&request);
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        let tenant = validation::tenant(&principal)?;
        validation::read_id(&request.get_ref().operation_id, &self.limits)?;
        self.check_encoded(request.get_ref())?;
        validation::completed(expires)?;
        let result = self
            .trigger_store()?
            .get_trigger_operation(&tenant, &request.into_inner().operation_id)
            .map_err(|e| platform_status(e, &self.limits))?;
        let (value, lease) = result.into_parts();
        let output = conversion::lookup(value);
        response::finish(self, output, lease, expires)
    }
}

async fn execute(
    adapter: &ManagementServiceAdapter,
    request: TriggerOperationRequest,
    expires: Instant,
) -> Result<
    (
        TriggerRead<TriggerOperationCommit>,
        latent_artifacts::ReleaseAuditAck,
    ),
    Status,
> {
    let audit =
        adapter.services.audit.as_ref().ok_or_else(|| {
            Status::unimplemented("HTTP trigger mutations require configured audit")
        })?;
    validation::completed(expires)?;
    let store = adapter.trigger_store()?;
    let prepared = store
        .prepare_trigger_operation(request)
        .map_err(|e| platform_status(e, &adapter.limits))?;
    response::preflight(adapter, &prepared)?;
    let mut audit =
        ManagedTriggerAudit::begin(audit, prepared.preview(), prepared.replayed(), expires)
            .await
            .map_err(|e| platform_status(e, &adapter.limits))?;
    let result = audit.commit(store, prepared, expires);
    let matches = result
        .as_ref()
        .ok()
        .is_none_or(|r| audit.matches(r.value()));
    let ack = audit
        .finish(
            store,
            result
                .as_ref()
                .ok()
                .filter(|_| matches)
                .map(TriggerRead::value),
            expires,
        )
        .await;
    if !matches {
        return Err(control_audit::status(
            Status::internal("HTTP trigger receipt association changed"),
            ack,
        ));
    }
    result
        .map(|r| (r, ack))
        .map_err(|e| control_audit::status(platform_status(e, &adapter.limits), ack))
}

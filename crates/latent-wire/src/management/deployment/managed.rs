//! Inline managed control: bounded preparation, audited synchronous commit, leased replies.
mod lease;
mod reads;
mod response;
mod validation;

pub use lease::DeploymentResponseService;
pub(super) use reads::{get, lookup};
pub(super) use validation::deadline;

use super::super::{control_audit, errors::platform_status, proto, ManagementServiceAdapter};
use latent_control_store::deployment_operations::{
    DeploymentOperationCommit, DeploymentOperationRead, DeploymentOperationRequest,
};
use latent_core::InvocationPrincipal;
use latent_rollout::deployment_audit::{
    record_rejection, DeploymentRejectionIdentity, ManagedDeploymentAudit,
};
use std::time::Instant;
use tonic::{Response, Status};

pub(super) async fn apply(
    adapter: &ManagementServiceAdapter,
    value: proto::ApplyDeploymentRequest,
    principal: InvocationPrincipal,
    deadline: Instant,
) -> Result<Response<proto::ApplyDeploymentResponse>, Status> {
    let request = validation::apply(value, principal, &adapter.limits)?;
    let (result, ack) = execute(adapter, request, deadline).await?;
    let (value, lease) = result.into_parts();
    let output = response::apply(value, ack, &adapter.limits)
        .map_err(|error| control_audit::status(error, ack))?;
    response::finish(output, lease, &adapter.limits, deadline)
        .map_err(|error| control_audit::status(error, ack))
}

pub(super) async fn delete(
    adapter: &ManagementServiceAdapter,
    value: proto::DeleteDeploymentRequest,
    principal: InvocationPrincipal,
    deadline: Instant,
) -> Result<Response<proto::Empty>, Status> {
    let request = validation::delete(value, principal, &adapter.limits)?;
    let (result, ack) = execute(adapter, request, deadline).await?;
    let (value, lease) = result.into_parts();
    let mut output = response::finish(proto::Empty {}, lease, &adapter.limits, deadline)
        .map_err(|error| control_audit::status(error, ack))?;
    response::delete_metadata(output.metadata_mut(), &value)
        .map_err(|error| control_audit::status(error, ack))?;
    Ok(control_audit::response(output, ack))
}

async fn execute(
    adapter: &ManagementServiceAdapter,
    request: DeploymentOperationRequest,
    deadline: Instant,
) -> Result<
    (
        DeploymentOperationRead<DeploymentOperationCommit>,
        latent_artifacts::ReleaseAuditAck,
    ),
    Status,
> {
    let audit = adapter.services.audit.as_ref().ok_or_else(|| {
        Status::unimplemented("managed deployment operations require configured audit")
    })?;
    validation::completed(deadline)?;
    response::scratch(&adapter.limits)?;
    let store = adapter.services.deployments.as_ref();
    let _request_lease = store
        .reserve_operation_request()
        .map_err(|error| platform_status(error, &adapter.limits))?;
    let rejected = DeploymentRejectionIdentity::from_request(&request)
        .map_err(|error| platform_status(error, &adapter.limits))?;
    let context = request.context().clone();
    let prepared = tokio::time::timeout_at(deadline.into(), store.prepare_operation(request))
        .await
        .map_err(|_| validation::expired())?;
    let prepared = match prepared {
        Ok(prepared) => prepared,
        Err(error) => {
            response::rejection(&error, &adapter.limits)?;
            let ack = record_rejection(audit, rejected, &error, deadline)
                .await
                .map_err(|error| platform_status(error, &adapter.limits))?;
            return Err(control_audit::status(
                platform_status(error, &adapter.limits),
                ack,
            ));
        }
    };
    validation::completed(deadline)?;
    if prepared.preview().tenant != context.tenant
        || prepared.preview().actor != context.actor
        || prepared.preview().operation_id != context.operation_id
        || prepared.preview().expected_state_version != context.expected_state_version
        || &prepared.preview().request_digest != rejected.request_digest()
    {
        return Err(Status::internal(
            "managed deployment preview association changed",
        ));
    }
    drop(rejected);
    response::preflight(&prepared, &context.tenant, &adapter.limits)?;
    let mut guard =
        ManagedDeploymentAudit::begin(audit, prepared.preview(), prepared.replayed(), deadline)
            .await
            .map_err(|error| platform_status(error, &adapter.limits))?;
    // commit checks the deadline, marks mutation_started and calls the synchronous
    // catalog commit without an await. Dropped RPC waits never imply an undo.
    let result = guard.commit(store, prepared, deadline);
    let associated = result
        .as_ref()
        .ok()
        .is_none_or(|value| guard.matches(value.value()));
    let ack = guard
        .finish(
            store,
            result
                .as_ref()
                .ok()
                .filter(|_| associated)
                .map(DeploymentOperationRead::value),
            deadline,
        )
        .await;
    if !associated {
        return Err(control_audit::status(
            Status::internal("managed deployment commit association changed"),
            ack,
        ));
    }
    result
        .map(|value| (value, ack))
        .map_err(|error| control_audit::status(platform_status(error, &adapter.limits), ack))
}

use super::{mutation, proto, response, validation};
use crate::management::{
    control_audit, errors::platform_status, ManagementLimits, ManagementServiceAdapter,
};
use latent_control_store::rollouts::{RolloutCommand, RolloutId, RolloutRequest};
use latent_core::{
    InvocationPrincipal, PlatformError, PlatformErrorCode, RouteGeneration, TenantId,
};
use latent_rollout::{MutationPreview, RollbackPreview};
use std::time::Instant;
use tonic::{Response, Status};

pub(super) async fn change(
    adapter: &ManagementServiceAdapter,
    value: proto::ChangeRolloutRequest,
    principal: InvocationPrincipal,
    tenant: TenantId,
    limits: ManagementLimits,
    deadline: Instant,
) -> Result<Response<proto::ChangeRolloutResponse>, Status> {
    let Some(proto::change_rollout_request::Command::Rollback(command)) = value.command else {
        return Err(Status::invalid_argument("rollback command required"));
    };
    let request = RolloutRequest::Change {
        context: validation::context(principal, value.operation.expect("validated operation"))?,
        id: RolloutId(value.id),
        command: RolloutCommand::Rollback {
            target_generation: RouteGeneration(command.target_generation),
        },
    };
    let mut tenant_bytes = [0_u8; 256];
    let tenant_length = tenant.0.len();
    tenant_bytes[..tenant_length].copy_from_slice(tenant.0.as_bytes());
    let preview_limits = limits.clone();
    let result = adapter
        .rollout_handle()?
        .rollback(request, deadline, move |preview| {
            preflight(
                &preview,
                std::str::from_utf8(&tenant_bytes[..tenant_length]).expect("validated UTF-8"),
                &preview_limits,
            )
            .map_err(|error| PlatformError {
                code: if error.code() == tonic::Code::ResourceExhausted {
                    PlatformErrorCode::ResourceExhausted
                } else {
                    PlatformErrorCode::Internal
                },
                message: "rollback-response-preflight".into(),
                retryable: false,
                details: Vec::new(),
            })
        })
        .map_err(|error| platform_status(error, &limits))?
        .wait()
        .await
        .map_err(|failure| {
            control_audit::status(platform_status(failure.error, &limits), failure.audit_ack)
        })?;
    response::scope(&result.value().receipt, &tenant)?;
    let (value, lease) = result.into_parts();
    let acknowledgement = value.audit_ack;
    let value = mutation(value);
    response::finish(
        proto::ChangeRolloutResponse {
            receipt: value.0,
            audit_ack: value.1,
            replayed: value.2,
            durability: value.3,
            observation: value.4,
        },
        lease,
        &limits,
        deadline,
    )
    .map_err(|status| control_audit::status(status, acknowledgement))
}

fn preflight(
    preview: &RollbackPreview<'_>,
    tenant: &str,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    match (preview.receipt, preview.failure) {
        (Some(receipt), None) => response::preflight(
            MutationPreview {
                receipt,
                replayed: preview.replayed,
                audit_ack: preview.audit_ack,
                observation: preview.observation,
            },
            tenant,
            limits,
        ),
        (None, Some(failure)) => response::rejection(failure, limits),
        _ => Err(Status::internal("invalid rollback preview")),
    }
}

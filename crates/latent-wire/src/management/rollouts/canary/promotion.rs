use super::super::{mutation, proto, response, validation};
use crate::management::{
    bounds, control_audit, errors::platform_status, ManagementLimits, ManagementServiceAdapter,
    RequestBudget,
};
use latent_control_store::rollouts::{RolloutCommand, RolloutId, RolloutRequest};
use latent_core::{InvocationPrincipal, PlatformError, PlatformErrorCode, TenantId};
use latent_rollout::{MutationPreview, PromotionPreview};
use std::time::Instant;
use tonic::{Response, Status};

pub(in crate::management::rollouts) async fn promote(
    adapter: &ManagementServiceAdapter,
    value: proto::ChangeRolloutRequest,
    principal: InvocationPrincipal,
    tenant: TenantId,
    limits: ManagementLimits,
    deadline: Instant,
) -> Result<Response<proto::ChangeRolloutResponse>, Status> {
    let Some(proto::change_rollout_request::Command::Promote(command)) = value.command else {
        return Err(Status::invalid_argument("promotion command required"));
    };
    let request = RolloutRequest::Change {
        context: validation::context(principal, value.operation.expect("validated operation"))?,
        id: RolloutId(value.id),
        command: RolloutCommand::Promote {
            next_step: command.next_step,
        },
    };
    let mut tenant_bytes = [0_u8; 256];
    let tenant_length = tenant.0.len();
    tenant_bytes[..tenant_length].copy_from_slice(tenant.0.as_bytes());
    let preview_limits = limits.clone();
    let result = adapter
        .rollout_handle()?
        .promote(request, deadline, move |preview| {
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
                message: "promotion-response-preflight".into(),
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
    preview: &PromotionPreview<'_>,
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
        (None, Some(failure)) => {
            // Rejections contain only the public fixed error envelope and the
            // prepaid audit metadata. The full diagnostic report is an Evaluate response.
            let mut budget = RequestBudget::for_response::<proto::PlatformError>(limits)?;
            control_audit::charge(&mut budget)?;
            budget.allocation::<u8>(256)?;
            let error = PlatformError {
                code: failure.code,
                message: String::new(),
                retryable: failure.retryable,
                details: Vec::new(),
            };
            let status = platform_status(error, limits);
            if status.message().len() + status.details().len() + 128 > limits.max_response_bytes {
                return Err(bounds::exhausted());
            }
            Ok(())
        }
        _ => Err(Status::internal("invalid promotion preview")),
    }
}

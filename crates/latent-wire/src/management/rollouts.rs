//! Tenant-scoped control on the one configured, audited coordinator.
mod canary;
mod conversion;
mod enums;
mod lease;
mod reads;
mod response;
mod rollback;
mod validation;

#[cfg(test)]
mod tests;

use latent_control_store::rollouts as domain;
use latent_core::{DeploymentId, PlatformError, PlatformErrorCode};
use latent_manifest::{ManifestValidator, Phase1ManifestValidator};
use latent_rollout::{MutationPreview, MutationResult, RolloutHandle};
use tonic::{Request, Response, Status};

use super::{
    control_audit, errors::platform_status, proto, ManagementLimits, ManagementOperation,
    ManagementServiceAdapter,
};
pub use lease::RolloutResponseService;

pub(super) const MAX_REQUEST_BYTES: usize = 64 * 1024;
pub(super) const MAX_RESPONSE_BYTES: usize = 64 * 1024;

impl ManagementServiceAdapter {
    fn rollout_handle(&self) -> Result<&RolloutHandle, Status> {
        self.services
            .rollouts
            .as_ref()
            .ok_or_else(|| Status::unimplemented("manual rollout control is disabled"))
    }
}

#[tonic::async_trait]
impl proto::rollout_service_server::RolloutService for ManagementServiceAdapter {
    async fn start_rollout(
        &self,
        mut request: Request<proto::StartRolloutRequest>,
    ) -> Result<Response<proto::StartRolloutResponse>, Status> {
        let deadline = validation::deadline(&request);
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        let tenant = validation::tenant(&principal)?;
        let limits = validation::limits(&self.limits, false);
        validation::start(request.get_ref(), &tenant, &limits)?;
        let handle = self.rollout_handle()?;
        validation::completed(deadline)?;
        let value = request.into_inner();
        let mut candidate =
            super::deployment_manifest_from_proto(value.candidate.expect("validated candidate"))
                .map_err(|_| {
                    Status::invalid_argument("invalid rollout candidate representation")
                })?;
        Phase1ManifestValidator
            .validate_deployment(&candidate)
            .map_err(|_| Status::invalid_argument("invalid rollout candidate"))?;
        candidate.normalize_storage_fields();
        let domain = domain::RolloutRequest::Start {
            context: validation::context(principal, value.operation.expect("validated operation"))?,
            spec: domain::StartRolloutSpec {
                id: domain::RolloutId(value.id),
                base: domain::DeploymentExpectation {
                    id: DeploymentId(value.base_deployment_id),
                    generation: value
                        .expected_base_generation
                        .expect("validated generation"),
                },
                candidate,
                canary_policy: value
                    .canary_policy
                    .as_ref()
                    .map(canary::policy::decode)
                    .transpose()?,
                candidate_weights: value
                    .candidate_weights
                    .into_iter()
                    .map(|value| u16::try_from(value).expect("validated basis points"))
                    .collect(),
            },
        };
        let preflight_limits = limits.clone();
        let mut preflight_tenant = [0_u8; 256];
        let tenant_length = tenant.0.len();
        preflight_tenant[..tenant_length].copy_from_slice(tenant.0.as_bytes());
        let result = handle
            .submit(domain, deadline, move |preview| {
                preflight(
                    preview,
                    std::str::from_utf8(&preflight_tenant[..tenant_length])
                        .expect("validated tenant UTF-8"),
                    &preflight_limits,
                )
            })
            .map_err(|error| platform_status(error, &limits))?
            .wait()
            .await
            .map_err(|failure| {
                control_audit::status(platform_status(failure.error, &limits), failure.audit_ack)
            })?;
        response::scope(&result.value().receipt, &tenant)?;
        let (result, lease) = result.into_parts();
        let audit_ack = result.audit_ack;
        let value = mutation(result);
        let output = proto::StartRolloutResponse {
            receipt: value.0,
            audit_ack: value.1,
            replayed: value.2,
            durability: value.3,
            observation: value.4,
        };
        response::finish(output, lease, &limits, deadline)
            .map_err(|status| control_audit::status(status, audit_ack))
    }

    #[allow(
        clippy::too_many_lines,
        reason = "bound and authenticate every mutation before dispatch to its single coordinator path"
    )]
    async fn change_rollout(
        &self,
        mut request: Request<proto::ChangeRolloutRequest>,
    ) -> Result<Response<proto::ChangeRolloutResponse>, Status> {
        let deadline = validation::deadline(&request);
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        let tenant = validation::tenant(&principal)?;
        let limits = validation::limits(&self.limits, false);
        validation::change(request.get_ref(), &limits)?;
        let handle = self.rollout_handle()?;
        validation::completed(deadline)?;
        if matches!(
            request.get_ref().command,
            Some(proto::change_rollout_request::Command::Promote(_))
        ) {
            return canary::promote(
                self,
                request.into_inner(),
                principal,
                tenant,
                limits,
                deadline,
            )
            .await;
        }
        if matches!(
            request.get_ref().command,
            Some(proto::change_rollout_request::Command::Rollback(_))
        ) {
            return rollback::change(
                self,
                request.into_inner(),
                principal,
                tenant,
                limits,
                deadline,
            )
            .await;
        }
        let value = request.into_inner();
        let command = match value.command.expect("validated command") {
            proto::change_rollout_request::Command::Advance(value) => {
                domain::RolloutCommand::Advance {
                    next_step: value.next_step,
                }
            }
            proto::change_rollout_request::Command::Pause(_) => domain::RolloutCommand::Pause,
            proto::change_rollout_request::Command::Resume(_) => domain::RolloutCommand::Resume,
            proto::change_rollout_request::Command::Abort(_) => domain::RolloutCommand::Abort,
            proto::change_rollout_request::Command::Promote(_) => {
                unreachable!("promotion dispatched separately")
            }
            proto::change_rollout_request::Command::Rollback(_) => {
                unreachable!("rollback dispatched separately")
            }
        };
        let domain = domain::RolloutRequest::Change {
            context: validation::context(principal, value.operation.expect("validated operation"))?,
            id: domain::RolloutId(value.id),
            command,
        };
        let preflight_limits = limits.clone();
        let mut preflight_tenant = [0_u8; 256];
        let tenant_length = tenant.0.len();
        preflight_tenant[..tenant_length].copy_from_slice(tenant.0.as_bytes());
        let result = handle
            .submit(domain, deadline, move |preview| {
                preflight(
                    preview,
                    std::str::from_utf8(&preflight_tenant[..tenant_length])
                        .expect("validated tenant UTF-8"),
                    &preflight_limits,
                )
            })
            .map_err(|error| platform_status(error, &limits))?
            .wait()
            .await
            .map_err(|failure| {
                control_audit::status(platform_status(failure.error, &limits), failure.audit_ack)
            })?;
        response::scope(&result.value().receipt, &tenant)?;
        let (result, lease) = result.into_parts();
        let audit_ack = result.audit_ack;
        let value = mutation(result);
        let output = proto::ChangeRolloutResponse {
            receipt: value.0,
            audit_ack: value.1,
            replayed: value.2,
            durability: value.3,
            observation: value.4,
        };
        response::finish(output, lease, &limits, deadline)
            .map_err(|status| control_audit::status(status, audit_ack))
    }

    async fn get_rollout(
        &self,
        request: Request<proto::GetRolloutRequest>,
    ) -> Result<Response<proto::GetRolloutResponse>, Status> {
        reads::get(self, request).await
    }
    async fn list_rollouts(
        &self,
        request: Request<proto::ListRolloutsRequest>,
    ) -> Result<Response<proto::ListRolloutsResponse>, Status> {
        reads::list(self, request).await
    }
    async fn get_rollout_operation(
        &self,
        request: Request<proto::GetRolloutOperationRequest>,
    ) -> Result<Response<proto::GetRolloutOperationResponse>, Status> {
        reads::operation(self, request).await
    }

    async fn evaluate_rollout(
        &self,
        request: Request<proto::EvaluateRolloutRequest>,
    ) -> Result<Response<proto::EvaluateRolloutResponse>, Status> {
        canary::evaluate(self, request).await
    }
}

fn mutation(
    value: MutationResult,
) -> (
    Option<proto::RolloutOperationReceipt>,
    Option<proto::AuditAck>,
    bool,
    i32,
    Option<proto::RolloutObservation>,
) {
    let durability = if value.durability.is_ok() {
        proto::RolloutDurability::Confirmed
    } else {
        proto::RolloutDurability::Uncertain
    };
    (
        Some(conversion::receipt(value.receipt)),
        Some(control_audit::wire(value.audit_ack)),
        value.replayed,
        durability as i32,
        value.observation.map(canary::observation),
    )
}

fn preflight(
    preview: MutationPreview<'_>,
    tenant: &str,
    limits: &ManagementLimits,
) -> Result<(), PlatformError> {
    response::preflight(preview, tenant, limits).map_err(|status| PlatformError {
        code: if status.code() == tonic::Code::ResourceExhausted {
            PlatformErrorCode::ResourceExhausted
        } else {
            PlatformErrorCode::Internal
        },
        message: "rollout-response-preflight".into(),
        retryable: false,
        details: Vec::new(),
    })
}

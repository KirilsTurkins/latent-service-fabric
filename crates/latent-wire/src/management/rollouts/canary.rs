pub(super) mod policy;
mod promotion;
mod report;
#[cfg(test)]
mod tests;

use super::{proto, response, validation};
use crate::management::{
    control_audit, errors::platform_status, ManagementOperation, ManagementServiceAdapter,
    RequestBudget,
};
use latent_artifacts::{ReleaseActor, ReleaseActorKind};
use latent_control_store::rollouts::RolloutId;
use latent_rollout::{CanaryEvaluationRequest, RolloutObservation, RolloutObservationState};
pub(super) use promotion::promote;
pub(super) use report::{charge_decision, decision};
use tonic::{Request, Response, Status};

pub(super) fn observation(value: RolloutObservation) -> proto::RolloutObservation {
    proto::RolloutObservation {
        state: match value.state {
            RolloutObservationState::Collecting => proto::RolloutObservationState::Collecting,
            RolloutObservationState::AwaitingEvaluation => {
                proto::RolloutObservationState::AwaitingEvaluation
            }
            RolloutObservationState::Unavailable => proto::RolloutObservationState::Unavailable,
            RolloutObservationState::Retired => proto::RolloutObservationState::Retired,
        } as i32,
        window_epoch: value.window_epoch,
    }
}

pub(super) async fn evaluate(
    adapter: &ManagementServiceAdapter,
    mut request: Request<proto::EvaluateRolloutRequest>,
) -> Result<Response<proto::EvaluateRolloutResponse>, Status> {
    let deadline = validation::deadline(&request);
    let principal = adapter.authenticate(&mut request, ManagementOperation::Tenant)?;
    let tenant = validation::tenant(&principal)?;
    let limits = validation::limits(&adapter.limits, true);
    let mut budget = RequestBudget::new::<proto::EvaluateRolloutRequest>(&limits)?;
    validation::id(
        &request.get_ref().id,
        &mut budget,
        limits.max_id_bytes.min(128),
    )?;
    let revision = request
        .get_ref()
        .expected_revision
        .filter(|value| *value != 0)
        .ok_or_else(|| Status::invalid_argument("positive rollout revision is required"))?;
    validation::encoded(request.get_ref(), &limits)?;
    let handle = adapter.rollout_handle()?;
    validation::completed(deadline)?;
    let id = request.into_inner().id;
    let expected_id = id.as_str().to_owned();
    let result = handle
        .evaluate(
            CanaryEvaluationRequest {
                tenant,
                actor: ReleaseActor {
                    subject: principal.subject.as_str().into(),
                    kind: ReleaseActorKind::Administrator,
                },
                id: RolloutId(id),
                expected_revision: revision,
            },
            deadline,
        )
        .map_err(|failure| platform_status(failure, &limits))?
        .wait()
        .await
        .map_err(|failure| {
            control_audit::status(platform_status(failure.error, &limits), failure.audit_ack)
        })?;
    if result.value().rollout_id.0 != expected_id || result.value().revision != revision {
        return Err(Status::internal("canary report identity mismatch"));
    }
    report::charge(result.value(), &limits)?;
    let (value, lease) = result.into_parts();
    response::finish(
        proto::EvaluateRolloutResponse {
            report: Some(report::wire(value)),
        },
        lease,
        &limits,
        deadline,
    )
}

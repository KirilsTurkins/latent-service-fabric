use super::{enums, proto};
use latent_control_store::rollouts as domain;

pub(super) fn receipt(value: domain::RolloutOperationReceipt) -> proto::RolloutOperationReceipt {
    proto::RolloutOperationReceipt {
        rollout_id: value.rollout_id.0,
        tenant: value.tenant.0,
        operation_id: value.operation_id,
        request_digest: value.request_digest.into_string(),
        actor: Some(proto::ReleaseActor {
            subject: value.actor.subject,
            kind: enums::actor(value.actor.kind),
        }),
        action: enums::action(value.action),
        expected_revision: value.expected_revision,
        revision: value.revision,
        outcome: match value.outcome {
            domain::RolloutOperationOutcome::Committed => {
                proto::RolloutOperationOutcome::Committed as i32
            }
        },
        reason: enums::reason(value.reason),
        state_version: value.state_version,
        route_generation: value.route_generation.0,
        state: enums::state(value.state),
        step: value.step,
        plan_digest: value.plan_digest.into_string(),
        completed_at_unix_millis: value.completed_at_unix_millis,
        receipt_digest: value.receipt_digest.into_string(),
        canary_decision: value.canary_decision.map(super::canary::decision),
        rollback_target: value.rollback_target.map(rollback_target),
    }
}

pub(super) fn status(value: domain::RolloutStatus) -> proto::RolloutStatus {
    proto::RolloutStatus {
        id: value.id.0,
        tenant: value.tenant.0,
        service: value.service.0,
        revision: value.revision,
        state: enums::state(value.state),
        reason: enums::reason(value.reason),
        current_step: value.current_step,
        candidate_weights: value.candidate_weights.into_iter().map(u32::from).collect(),
        base: Some(release(value.base)),
        candidate: Some(release(value.candidate)),
        objects: value
            .objects
            .into_iter()
            .map(|value| proto::RolloutObjectVersion {
                deployment_id: value.deployment_id.0,
                generation: value.generation,
            })
            .collect(),
        route_generation: value.route_generation.0,
        state_version: value.state_version,
        plan_digest: value.plan_digest.into_string(),
        previous_route_generation: value.previous_route_generation.0,
        created_at_unix_millis: value.created_at_unix_millis,
        updated_at_unix_millis: value.updated_at_unix_millis,
        retained_operation_floor: value.retained_operation_floor,
        canary_policy: value.canary_policy.map(super::canary::policy::wire),
        rollback_target: value.rollback_target.map(rollback_target),
    }
}
fn release(value: domain::RolloutRelease) -> proto::RolloutRelease {
    proto::RolloutRelease {
        deployment_id: value.deployment_id.0,
        component_digest: value.component.0,
        package_digest: value.package.map(latent_core::PackageDigest::into_string),
    }
}

fn rollback_target(value: domain::RolloutRollbackTarget) -> proto::RolloutRollbackTarget {
    proto::RolloutRollbackTarget {
        format_version: value.format_version,
        historical_route_generation: value.historical_route_generation.0,
        manifest_digest: value.manifest_digest.into_string(),
    }
}

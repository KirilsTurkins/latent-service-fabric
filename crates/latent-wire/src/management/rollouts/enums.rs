use super::proto;
use latent_artifacts::ReleaseActorKind;
use latent_control_store::rollouts as domain;
use tonic::Status;

pub(super) fn state(value: domain::RolloutState) -> i32 {
    match value {
        domain::RolloutState::Running => proto::RolloutState::Running as i32,
        domain::RolloutState::Paused => proto::RolloutState::Paused as i32,
        domain::RolloutState::Completed => proto::RolloutState::Completed as i32,
        domain::RolloutState::Aborted => proto::RolloutState::Aborted as i32,
        domain::RolloutState::Conflicted => proto::RolloutState::Conflicted as i32,
    }
}

pub(super) fn action(value: domain::RolloutAction) -> i32 {
    match value {
        domain::RolloutAction::Start => proto::RolloutAction::Start as i32,
        domain::RolloutAction::Advance => proto::RolloutAction::Advance as i32,
        domain::RolloutAction::Pause => proto::RolloutAction::Pause as i32,
        domain::RolloutAction::Resume => proto::RolloutAction::Resume as i32,
        domain::RolloutAction::Abort => proto::RolloutAction::Abort as i32,
    }
}

pub(super) fn reason(value: domain::RolloutReason) -> i32 {
    match value {
        domain::RolloutReason::OperatorRequested => proto::RolloutReason::OperatorRequested as i32,
        domain::RolloutReason::StageApplied => proto::RolloutReason::StageApplied as i32,
        domain::RolloutReason::Completed => proto::RolloutReason::Completed as i32,
        domain::RolloutReason::GenerationConflict => {
            proto::RolloutReason::GenerationConflict as i32
        }
        domain::RolloutReason::CohortChanged => proto::RolloutReason::CohortChanged as i32,
        domain::RolloutReason::ReleaseIneligible => proto::RolloutReason::ReleaseIneligible as i32,
        domain::RolloutReason::IncompatibleRelease => {
            proto::RolloutReason::IncompatibleRelease as i32
        }
        domain::RolloutReason::ResourceLimit => proto::RolloutReason::ResourceLimit as i32,
        domain::RolloutReason::RecoveryRequired => proto::RolloutReason::RecoveryRequired as i32,
        domain::RolloutReason::OutcomeUncertain => proto::RolloutReason::OutcomeUncertain as i32,
    }
}

pub(super) fn actor(value: ReleaseActorKind) -> i32 {
    match value {
        ReleaseActorKind::User => proto::ReleaseActorKind::User as i32,
        ReleaseActorKind::Service => proto::ReleaseActorKind::Service as i32,
        ReleaseActorKind::Node => proto::ReleaseActorKind::Node as i32,
        ReleaseActorKind::Trigger => proto::ReleaseActorKind::Trigger as i32,
        ReleaseActorKind::Administrator => proto::ReleaseActorKind::Administrator as i32,
        ReleaseActorKind::Anonymous => proto::ReleaseActorKind::Anonymous as i32,
        ReleaseActorKind::Host => proto::ReleaseActorKind::Host as i32,
    }
}

pub(super) fn state_input(value: i32) -> Result<domain::RolloutState, Status> {
    match proto::RolloutState::try_from(value) {
        Ok(proto::RolloutState::Running) => Ok(domain::RolloutState::Running),
        Ok(proto::RolloutState::Paused) => Ok(domain::RolloutState::Paused),
        Ok(proto::RolloutState::Completed) => Ok(domain::RolloutState::Completed),
        Ok(proto::RolloutState::Aborted) => Ok(domain::RolloutState::Aborted),
        Ok(proto::RolloutState::Conflicted) => Ok(domain::RolloutState::Conflicted),
        _ => Err(Status::invalid_argument("invalid rollout state")),
    }
}

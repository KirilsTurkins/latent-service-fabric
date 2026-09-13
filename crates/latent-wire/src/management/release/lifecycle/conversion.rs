use super::proto;
use latent_artifacts as domain;
use tonic::Status;

pub(super) fn release_actor_kind(value: domain::ReleaseActorKind) -> i32 {
    match value {
        domain::ReleaseActorKind::User => proto::ReleaseActorKind::User as i32,
        domain::ReleaseActorKind::Service => proto::ReleaseActorKind::Service as i32,
        domain::ReleaseActorKind::Node => proto::ReleaseActorKind::Node as i32,
        domain::ReleaseActorKind::Trigger => proto::ReleaseActorKind::Trigger as i32,
        domain::ReleaseActorKind::Administrator => proto::ReleaseActorKind::Administrator as i32,
        domain::ReleaseActorKind::Anonymous => proto::ReleaseActorKind::Anonymous as i32,
        domain::ReleaseActorKind::Host => proto::ReleaseActorKind::Host as i32,
    }
}

pub(super) fn release_lifecycle_state(value: domain::ReleaseLifecycleState) -> i32 {
    match value {
        domain::ReleaseLifecycleState::Admitted => proto::ReleaseLifecycleState::Admitted as i32,
        domain::ReleaseLifecycleState::Revoked => proto::ReleaseLifecycleState::Revoked as i32,
        domain::ReleaseLifecycleState::Retired => proto::ReleaseLifecycleState::Retired as i32,
    }
}

pub(super) fn release_lifecycle_action(value: domain::ReleaseLifecycleAction) -> i32 {
    match value {
        domain::ReleaseLifecycleAction::Publish => proto::ReleaseLifecycleAction::Publish as i32,
        domain::ReleaseLifecycleAction::Revoke => proto::ReleaseLifecycleAction::Revoke as i32,
        domain::ReleaseLifecycleAction::Retire => proto::ReleaseLifecycleAction::Retire as i32,
        domain::ReleaseLifecycleAction::RenewEvidence => {
            proto::ReleaseLifecycleAction::RenewEvidence as i32
        }
    }
}

pub(super) fn release_operation_disposition(value: domain::ReleaseOperationDisposition) -> i32 {
    match value {
        domain::ReleaseOperationDisposition::Committed => {
            proto::ReleaseOperationDisposition::Committed as i32
        }
        domain::ReleaseOperationDisposition::Rejected => {
            proto::ReleaseOperationDisposition::Rejected as i32
        }
    }
}

pub(super) fn release_lifecycle_reason(value: domain::ReleaseLifecycleReason) -> i32 {
    match value {
        domain::ReleaseLifecycleReason::ContentConflict => {
            proto::ReleaseLifecycleReason::ContentConflict as i32
        }
        domain::ReleaseLifecycleReason::Admitted => proto::ReleaseLifecycleReason::Admitted as i32,
        domain::ReleaseLifecycleReason::EvidenceRenewed => {
            proto::ReleaseLifecycleReason::EvidenceRenewed as i32
        }
        domain::ReleaseLifecycleReason::OperatorRevocation => {
            proto::ReleaseLifecycleReason::OperatorRevocation as i32
        }
        domain::ReleaseLifecycleReason::SecurityIncident => {
            proto::ReleaseLifecycleReason::SecurityIncident as i32
        }
        domain::ReleaseLifecycleReason::CorruptContent => {
            proto::ReleaseLifecycleReason::CorruptContent as i32
        }
        domain::ReleaseLifecycleReason::Superseded => {
            proto::ReleaseLifecycleReason::Superseded as i32
        }
        domain::ReleaseLifecycleReason::EndOfSupport => {
            proto::ReleaseLifecycleReason::EndOfSupport as i32
        }
        domain::ReleaseLifecycleReason::OperatorRetirement => {
            proto::ReleaseLifecycleReason::OperatorRetirement as i32
        }
        domain::ReleaseLifecycleReason::InvalidPackage => {
            proto::ReleaseLifecycleReason::InvalidPackage as i32
        }
        domain::ReleaseLifecycleReason::IntegrityMismatch => {
            proto::ReleaseLifecycleReason::IntegrityMismatch as i32
        }
        domain::ReleaseLifecycleReason::IncompatibleContract => {
            proto::ReleaseLifecycleReason::IncompatibleContract as i32
        }
        domain::ReleaseLifecycleReason::EvidenceRejected => {
            proto::ReleaseLifecycleReason::EvidenceRejected as i32
        }
        domain::ReleaseLifecycleReason::PolicyDenied => {
            proto::ReleaseLifecycleReason::PolicyDenied as i32
        }
        domain::ReleaseLifecycleReason::ReleaseRevoked => {
            proto::ReleaseLifecycleReason::ReleaseRevoked as i32
        }
        domain::ReleaseLifecycleReason::ReleaseRetired => {
            proto::ReleaseLifecycleReason::ReleaseRetired as i32
        }
        domain::ReleaseLifecycleReason::GenerationConflict => {
            proto::ReleaseLifecycleReason::GenerationConflict as i32
        }
    }
}

pub(super) fn release_live_eligibility(value: domain::ReleaseLiveEligibility) -> i32 {
    match value {
        domain::ReleaseLiveEligibility::Eligible => proto::ReleaseLiveEligibility::Eligible as i32,
        domain::ReleaseLiveEligibility::Denied => proto::ReleaseLiveEligibility::Denied as i32,
        domain::ReleaseLiveEligibility::Unknown => proto::ReleaseLiveEligibility::Unknown as i32,
    }
}

pub(super) fn release_eligibility_reason(value: domain::ReleaseEligibilityReason) -> i32 {
    match value {
        domain::ReleaseEligibilityReason::LocalEligible => {
            proto::ReleaseEligibilityReason::LocalEligible as i32
        }
        domain::ReleaseEligibilityReason::Verified => {
            proto::ReleaseEligibilityReason::Verified as i32
        }
        domain::ReleaseEligibilityReason::Revoked => {
            proto::ReleaseEligibilityReason::Revoked as i32
        }
        domain::ReleaseEligibilityReason::Retired => {
            proto::ReleaseEligibilityReason::Retired as i32
        }
        domain::ReleaseEligibilityReason::PolicyDenied => {
            proto::ReleaseEligibilityReason::PolicyDenied as i32
        }
        domain::ReleaseEligibilityReason::ProofExpired => {
            proto::ReleaseEligibilityReason::ProofExpired as i32
        }
        domain::ReleaseEligibilityReason::RuntimeIncompatible => {
            proto::ReleaseEligibilityReason::RuntimeIncompatible as i32
        }
        domain::ReleaseEligibilityReason::CorruptContent => {
            proto::ReleaseEligibilityReason::CorruptContent as i32
        }
        domain::ReleaseEligibilityReason::AuthorityUnavailable => {
            proto::ReleaseEligibilityReason::AuthorityUnavailable as i32
        }
        domain::ReleaseEligibilityReason::MutationUncertain => {
            proto::ReleaseEligibilityReason::MutationUncertain as i32
        }
    }
}

pub(super) fn change(
    value: i32,
    reason: i32,
) -> Result<
    (
        domain::ReleaseLifecycleAction,
        domain::ReleaseLifecycleReason,
    ),
    Status,
> {
    use proto::{ReleaseLifecycleAction as A, ReleaseLifecycleReason as R};
    let invalid = || Status::invalid_argument("invalid release lifecycle action or reason");
    let reason = R::try_from(reason).map_err(|_| invalid())?;
    let pair = match (A::try_from(value).map_err(|_| invalid())?, reason) {
        (A::Revoke, R::OperatorRevocation) => (
            domain::ReleaseLifecycleAction::Revoke,
            domain::ReleaseLifecycleReason::OperatorRevocation,
        ),
        (A::Revoke, R::SecurityIncident) => (
            domain::ReleaseLifecycleAction::Revoke,
            domain::ReleaseLifecycleReason::SecurityIncident,
        ),
        (A::Revoke, R::CorruptContent) => (
            domain::ReleaseLifecycleAction::Revoke,
            domain::ReleaseLifecycleReason::CorruptContent,
        ),
        (A::Retire, R::Superseded) => (
            domain::ReleaseLifecycleAction::Retire,
            domain::ReleaseLifecycleReason::Superseded,
        ),
        (A::Retire, R::EndOfSupport) => (
            domain::ReleaseLifecycleAction::Retire,
            domain::ReleaseLifecycleReason::EndOfSupport,
        ),
        (A::Retire, R::OperatorRetirement) => (
            domain::ReleaseLifecycleAction::Retire,
            domain::ReleaseLifecycleReason::OperatorRetirement,
        ),
        _ => return Err(invalid()),
    };
    Ok(pair)
}

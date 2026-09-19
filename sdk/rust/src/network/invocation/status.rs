use super::{convert, RpcFailure};
use crate::{ActivationStatus, RetainedInvocationOutcome};
use latent_core::{ActivationId, ActivationPhase, ActivationTerminalState, PlatformErrorCode};
use latent_rpc::{invocation::v1 as proto, platform_error::TryIntoDomainPlatformError};

pub(super) fn convert(value: proto::ActivationStatus) -> Result<ActivationStatus, RpcFailure> {
    convert::valid_id(&value.activation_id)?;
    let terminal_state = value.terminal_state.as_deref().map(terminal).transpose()?;
    let terminal_outcome = value
        .terminal_outcome
        .map(|outcome| match outcome {
            proto::activation_status::TerminalOutcome::Succeeded(success) => {
                Ok(RetainedInvocationOutcome::Succeeded {
                    committed_state_version: success.committed_state_version,
                    effect_ids: success.effect_ids,
                    metadata: success.metadata.into_iter().collect(),
                })
            }
            proto::activation_status::TerminalOutcome::DeclaredError(error) => Ok(
                RetainedInvocationOutcome::DeclaredError(convert::declared(error)),
            ),
            proto::activation_status::TerminalOutcome::PlatformFailure(error) => Ok(
                RetainedInvocationOutcome::PlatformFailure(error.try_into_domain().map_err(
                    |error| RpcFailure::unsupported("platform_error.code", error.code()),
                )?),
            ),
        })
        .transpose()?;
    let consistent = match (&terminal_state, &terminal_outcome) {
        (None, None) => {
            value.final_consumption.is_none() && value.terminal_at_unix_millis.is_none()
        }
        (Some(state), Some(outcome))
            if value.final_consumption.is_some() && value.terminal_at_unix_millis.is_some() =>
        {
            match outcome {
                RetainedInvocationOutcome::Succeeded { .. }
                | RetainedInvocationOutcome::DeclaredError(_) => {
                    *state == ActivationTerminalState::Completed
                }
                RetainedInvocationOutcome::PlatformFailure(error) => {
                    *state == terminal_for_error(error.code)
                }
            }
        }
        _ => false,
    };
    if !consistent {
        return Err(convert::invalid());
    }
    Ok(ActivationStatus {
        activation_id: ActivationId(value.activation_id),
        phase: phase(&value.phase)?,
        terminal_state,
        terminal_outcome,
        final_consumption: value.final_consumption.map(convert::consumption),
        last_updated_unix_millis: value.last_updated_unix_millis,
        terminal_at_unix_millis: value.terminal_at_unix_millis,
        metadata: value.metadata.into_iter().collect(),
    })
}

fn phase(value: &str) -> Result<ActivationPhase, RpcFailure> {
    Ok(match value {
        "received" => ActivationPhase::Received,
        "resolved" => ActivationPhase::Resolved,
        "admitted" => ActivationPhase::Admitted,
        "queued" => ActivationPhase::Queued,
        "materializing" => ActivationPhase::Materializing,
        "running" => ActivationPhase::Running,
        "suspended" => ActivationPhase::Suspended,
        "preparing_commit" => ActivationPhase::PreparingCommit,
        "committed" => ActivationPhase::Committed,
        "effects_pending" => ActivationPhase::EffectsPending,
        _ => return Err(RpcFailure::unsupported("activation.phase", value)),
    })
}

pub(super) fn terminal(value: &str) -> Result<ActivationTerminalState, RpcFailure> {
    Ok(match value {
        "completed" => ActivationTerminalState::Completed,
        "rejected" => ActivationTerminalState::Rejected,
        "cancelled" => ActivationTerminalState::Cancelled,
        "deadline_exceeded" => ActivationTerminalState::DeadlineExceeded,
        "resource_exhausted" => ActivationTerminalState::ResourceExhausted,
        "guest_trap" => ActivationTerminalState::GuestTrap,
        "state_conflict" => ActivationTerminalState::StateConflict,
        "dependency_failed" => ActivationTerminalState::DependencyFailed,
        "platform_failed" => ActivationTerminalState::PlatformFailed,
        _ => return Err(RpcFailure::unsupported("activation.terminal_state", value)),
    })
}

fn terminal_for_error(code: PlatformErrorCode) -> ActivationTerminalState {
    match code {
        PlatformErrorCode::DeadlineExceeded => ActivationTerminalState::DeadlineExceeded,
        PlatformErrorCode::Cancelled => ActivationTerminalState::Cancelled,
        PlatformErrorCode::ResourceExhausted => ActivationTerminalState::ResourceExhausted,
        PlatformErrorCode::GuestTrap => ActivationTerminalState::GuestTrap,
        PlatformErrorCode::StateConflict => ActivationTerminalState::StateConflict,
        PlatformErrorCode::DependencyFailed
        | PlatformErrorCode::Unavailable
        | PlatformErrorCode::RouteUnavailable => ActivationTerminalState::DependencyFailed,
        PlatformErrorCode::AdmissionRejected
        | PlatformErrorCode::PermissionDenied
        | PlatformErrorCode::Unauthenticated
        | PlatformErrorCode::InvalidArgument
        | PlatformErrorCode::NotFound
        | PlatformErrorCode::AlreadyExists
        | PlatformErrorCode::IncompatibleContract
        | PlatformErrorCode::CorruptArtifact => ActivationTerminalState::Rejected,
        _ => ActivationTerminalState::PlatformFailed,
    }
}

fn status_to_proto(status: &ActivationStatus) -> proto::ActivationStatus {
    let terminal_outcome = status
        .terminal_outcome
        .as_ref()
        .map(|outcome| match outcome {
            RetainedActivationOutcome::Succeeded(summary) => {
                proto::activation_status::TerminalOutcome::Succeeded(
                    proto::ActivationSuccessSummary {
                        committed_state_version: summary.committed_state_version.clone(),
                        effect_ids: summary.effect_ids.clone(),
                        metadata: summary.metadata.clone().into_iter().collect(),
                    },
                )
            }
            RetainedActivationOutcome::DeclaredError(error) => {
                proto::activation_status::TerminalOutcome::DeclaredError(declared_error_to_proto(
                    error,
                ))
            }
            RetainedActivationOutcome::PlatformFailure(error) => {
                proto::activation_status::TerminalOutcome::PlatformFailure(platform_error_to_proto(
                    error,
                ))
            }
        });
    proto::ActivationStatus {
        activation_id: status.activation_id.0.clone(),
        phase: activation_phase_name(status.phase).to_owned(),
        terminal_state: status
            .terminal_state
            .map(|state| terminal_state_name(state).to_owned()),
        last_updated_unix_millis: status.last_updated_unix_millis,
        metadata: status.metadata.clone().into_iter().collect(),
        terminal_outcome,
        final_consumption: status.final_consumption.as_ref().map(consumption_to_proto),
        terminal_at_unix_millis: status.terminal_at_unix_millis,
    }
}

fn activation_phase_name(phase: ActivationPhase) -> &'static str {
    match phase {
        ActivationPhase::Received => "received",
        ActivationPhase::Resolved => "resolved",
        ActivationPhase::Admitted => "admitted",
        ActivationPhase::Queued => "queued",
        ActivationPhase::Materializing => "materializing",
        ActivationPhase::Running => "running",
        ActivationPhase::Suspended => "suspended",
        ActivationPhase::PreparingCommit => "preparing_commit",
        ActivationPhase::Committed => "committed",
        ActivationPhase::EffectsPending => "effects_pending",
        _ => "unknown",
    }
}

fn parse_activation_phase(value: &str) -> Result<ActivationPhase, InvocationConversionError> {
    match value {
        "received" => Ok(ActivationPhase::Received),
        "resolved" => Ok(ActivationPhase::Resolved),
        "admitted" => Ok(ActivationPhase::Admitted),
        "queued" => Ok(ActivationPhase::Queued),
        "materializing" => Ok(ActivationPhase::Materializing),
        "running" => Ok(ActivationPhase::Running),
        "suspended" => Ok(ActivationPhase::Suspended),
        "preparing_commit" => Ok(ActivationPhase::PreparingCommit),
        "committed" => Ok(ActivationPhase::Committed),
        "effects_pending" => Ok(ActivationPhase::EffectsPending),
        _ => Err(InvocationConversionError::new(
            "activation phase is unknown to this build",
        )),
    }
}

fn terminal_state_name(state: ActivationTerminalState) -> &'static str {
    match state {
        ActivationTerminalState::Completed => "completed",
        ActivationTerminalState::Rejected => "rejected",
        ActivationTerminalState::Cancelled => "cancelled",
        ActivationTerminalState::DeadlineExceeded => "deadline_exceeded",
        ActivationTerminalState::ResourceExhausted => "resource_exhausted",
        ActivationTerminalState::GuestTrap => "guest_trap",
        ActivationTerminalState::StateConflict => "state_conflict",
        ActivationTerminalState::DependencyFailed => "dependency_failed",
        _ => "platform_failed",
    }
}

fn parse_terminal_state(value: &str) -> Result<ActivationTerminalState, InvocationConversionError> {
    match value {
        "completed" => Ok(ActivationTerminalState::Completed),
        "rejected" => Ok(ActivationTerminalState::Rejected),
        "cancelled" => Ok(ActivationTerminalState::Cancelled),
        "deadline_exceeded" => Ok(ActivationTerminalState::DeadlineExceeded),
        "resource_exhausted" => Ok(ActivationTerminalState::ResourceExhausted),
        "guest_trap" => Ok(ActivationTerminalState::GuestTrap),
        "state_conflict" => Ok(ActivationTerminalState::StateConflict),
        "dependency_failed" => Ok(ActivationTerminalState::DependencyFailed),
        "platform_failed" => Ok(ActivationTerminalState::PlatformFailed),
        _ => Err(InvocationConversionError::new(
            "activation terminal state is unknown to this build",
        )),
    }
}

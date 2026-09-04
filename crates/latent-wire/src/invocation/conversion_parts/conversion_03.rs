fn status_to_proto(
    status: &ActivationStatus,
    public: bool,
    limits: Option<&InvocationLimits>,
) -> proto::ActivationStatus {
    let terminal_outcome = status.terminal_outcome.as_ref().map(|outcome| match outcome {
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
            proto::activation_status::TerminalOutcome::DeclaredError(declared_error_to_proto(error))
        }
        RetainedActivationOutcome::PlatformFailure(error) => {
            let error = if public {
                public_platform_error(error, limits.expect("public conversion requires limits"))
            } else {
                error.clone()
            };
            proto::activation_status::TerminalOutcome::PlatformFailure(platform_error_to_proto(
                &error,
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
        final_consumption: status
            .final_consumption
            .as_ref()
            .map(consumption_to_proto),
        terminal_at_unix_millis: status.terminal_at_unix_millis,
    }
}

fn public_platform_error(error: &PlatformError, limits: &InvocationLimits) -> PlatformError {
    PlatformError {
        code: error.code,
        message: truncate_utf8(
            public_platform_message(error.code),
            limits.max_platform_error_message_bytes,
        ),
        retryable: error.retryable,
        details: error
            .details
            .iter()
            .filter_map(|detail| public_error_detail(detail, limits))
            .take(limits.max_platform_error_details)
            .collect(),
    }
}

fn public_error_detail(detail: &ErrorDetail, limits: &InvocationLimits) -> Option<ErrorDetail> {
    let fields = match detail.kind.as_str() {
        "cell-pool.all-quarantined" => allow_fields(
            detail,
            limits,
            &[("quarantined", PublicValueKind::Unsigned)],
        ),
        "cell-pool.unsupported-operation" => allow_fields(
            detail,
            limits,
            &[
                ("operation", PublicValueKind::Atom),
                ("scope", PublicValueKind::Atom),
            ],
        ),
        "resource.limit" | "admission.limit" => allow_fields(
            detail,
            limits,
            &[
                ("resource", PublicValueKind::Atom),
                ("requested", PublicValueKind::Unsigned),
                ("limit", PublicValueKind::Unsigned),
            ],
        ),
        "route.unavailable" => allow_fields(
            detail,
            limits,
            &[("route_generation", PublicValueKind::Unsigned)],
        ),
        "state.conflict" => allow_fields(
            detail,
            limits,
            &[
                ("expected_version", PublicValueKind::Atom),
                ("current_version", PublicValueKind::Atom),
            ],
        ),
        "retry" => allow_fields(
            detail,
            limits,
            &[("retry_after_millis", PublicValueKind::Unsigned)],
        ),
        _ => return None,
    };
    Some(ErrorDetail {
        kind: detail.kind.clone(),
        fields,
    })
}

#[derive(Debug, Clone, Copy)]
enum PublicValueKind {
    Atom,
    Unsigned,
}

fn allow_fields(
    detail: &ErrorDetail,
    limits: &InvocationLimits,
    allowed: &[(&str, PublicValueKind)],
) -> latent_core::Metadata {
    allowed
        .iter()
        .filter_map(|(key, kind)| {
            let value = detail.fields.get(*key)?;
            let value = match kind {
                PublicValueKind::Atom => public_atom(value, limits.max_string_bytes),
                PublicValueKind::Unsigned => public_unsigned(value, limits.max_string_bytes),
            }?;
            Some(((*key).to_owned(), value))
        })
        .take(limits.max_platform_error_fields)
        .collect()
}

fn public_atom(value: &str, maximum: usize) -> Option<String> {
    if value.is_empty()
        || value.len() > maximum
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
    {
        return None;
    }
    Some(value.to_owned())
}

fn public_unsigned(value: &str, maximum: usize) -> Option<String> {
    if value.is_empty() || value.len() > maximum || !value.bytes().all(|byte| byte.is_ascii_digit())
    {
        return None;
    }
    Some(value.to_owned())
}

fn truncate_utf8(value: &str, maximum: usize) -> String {
    if value.len() <= maximum {
        return value.to_owned();
    }
    let mut end = maximum.min(value.len());
    while !value.is_char_boundary(end) {
        end = end.saturating_sub(1);
    }
    value[..end].to_owned()
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

fn parse_activation_phase(
    value: &str,
) -> Result<ActivationPhase, InvocationConversionError> {
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
        ActivationTerminalState::PlatformFailed => "platform_failed",
        _ => "platform_failed",
    }
}

fn parse_terminal_state(
    value: &str,
) -> Result<ActivationTerminalState, InvocationConversionError> {
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
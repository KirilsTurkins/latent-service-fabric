use super::{
    activation_phase_name, parse_activation_phase, parse_terminal_state, proto,
    terminal_state_for_platform_error, terminal_state_name, ActivationOutcome, ActivationStatus,
    ActivationTerminalState, InvocationConversionError, InvocationResponse, InvocationRevision,
    RetainedActivationOutcome,
};

pub(in super::super) fn validate_response_shape(
    response: &InvocationResponse,
) -> Result<(), InvocationConversionError> {
    valid_id(&response.receipt.activation_id.0)?;
    if let Some(pin) = &response.receipt.resolved_revision {
        valid_id(&pin.revision_id.0)?;
        valid_id(&pin.release_digest.0)?;
    } else if !matches!(response.outcome, ActivationOutcome::Failed { .. }) {
        return Err(InvocationConversionError::new(
            "an unresolved invocation must have a platform-failure outcome",
        ));
    }
    if let ActivationOutcome::Failed {
        terminal_state,
        error,
        ..
    } = &response.outcome
    {
        if *terminal_state != terminal_state_for_platform_error(error.code) {
            return Err(InvocationConversionError::new(
                "invocation terminal state is not representable by its platform error code",
            ));
        }
    }
    Ok(())
}

pub(super) fn pin_from_wire(
    response: &mut proto::InvokeResponse,
) -> Result<Option<InvocationRevision>, InvocationConversionError> {
    match (
        response.revision_id.is_empty(),
        response.release_digest.is_empty(),
    ) {
        (true, true)
            if response.route_generation == 0
                && matches!(
                    response.result,
                    Some(proto::invoke_response::Result::PlatformFailure(_))
                ) =>
        {
            Ok(None)
        }
        (false, false) => {
            valid_id(&response.revision_id)?;
            valid_id(&response.release_digest)?;
            Ok(Some(InvocationRevision {
                revision_id: latent_core::RevisionId(std::mem::take(&mut response.revision_id)),
                release_digest: latent_core::ReleaseDigest(std::mem::take(
                    &mut response.release_digest,
                )),
                route_generation: latent_core::RouteGeneration(response.route_generation),
            }))
        }
        _ => Err(InvocationConversionError::new(
            "invocation revision pin is absent or partially populated",
        )),
    }
}

pub(in super::super) fn validate_status_shape(
    status: &ActivationStatus,
) -> Result<(), InvocationConversionError> {
    valid_id(&status.activation_id.0)?;
    // Reject future values instead of silently converting them to a fallback.
    parse_activation_phase(activation_phase_name(status.phase))?;
    match status.terminal_state {
        None if status.terminal_outcome.is_none()
            && status.final_consumption.is_none()
            && status.terminal_at_unix_millis.is_none() =>
        {
            Ok(())
        }
        Some(state)
            if status.final_consumption.is_some() && status.terminal_at_unix_millis.is_some() =>
        {
            if parse_terminal_state(terminal_state_name(state))? != state {
                return Err(InvocationConversionError::new(
                    "activation terminal state is unknown to this build",
                ));
            }
            let consistent = matches!(
                (&status.terminal_outcome, state),
                (
                    Some(
                        RetainedActivationOutcome::Succeeded(_)
                            | RetainedActivationOutcome::DeclaredError(_)
                    ),
                    ActivationTerminalState::Completed
                )
            ) || (matches!(
                status.terminal_outcome,
                Some(RetainedActivationOutcome::PlatformFailure(_))
            ) && state != ActivationTerminalState::Completed);
            if consistent {
                Ok(())
            } else {
                Err(InvocationConversionError::new(
                    "activation terminal outcome contradicts its terminal state",
                ))
            }
        }
        _ => Err(InvocationConversionError::new(
            "activation status has contradictory terminal diagnostic presence",
        )),
    }
}

fn valid_id(value: &str) -> Result<(), InvocationConversionError> {
    if value.is_empty() || value.chars().any(|c| c.is_control() || c.is_whitespace()) {
        Err(InvocationConversionError::new(
            "invocation receipt identity is invalid",
        ))
    } else {
        Ok(())
    }
}

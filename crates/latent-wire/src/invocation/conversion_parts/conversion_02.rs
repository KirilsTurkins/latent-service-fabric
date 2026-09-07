pub fn cancel_disposition_from_proto(
    response: proto::CancelResponse,
) -> Result<CancelDisposition, InvocationConversionError> {
    match proto::CancelDisposition::try_from(response.disposition) {
        Ok(proto::CancelDisposition::Accepted) if response.terminal_state.is_none() => {
            Ok(CancelDisposition::Accepted)
        }
        Ok(proto::CancelDisposition::AlreadyTerminal) => {
            let state = response.terminal_state.ok_or_else(|| {
                InvocationConversionError::new(
                    "already-terminal cancellation is missing its terminal state",
                )
            })?;
            Ok(CancelDisposition::AlreadyTerminal(parse_terminal_state(
                &state,
            )?))
        }
        Ok(proto::CancelDisposition::NotFound) if response.terminal_state.is_none() => {
            Ok(CancelDisposition::NotFound)
        }
        Ok(proto::CancelDisposition::Unspecified) | Err(_) => Err(InvocationConversionError::new(
            "cancellation disposition is unspecified or unknown",
        )),
        _ => Err(InvocationConversionError::new(
            "cancellation disposition carries a contradictory terminal state",
        )),
    }
}

#[must_use]
pub fn budget_to_proto(budget: &ResourceBudget) -> proto::ResourceBudget {
    proto::ResourceBudget {
        cpu_fuel: budget.cpu_fuel,
        memory_bytes: budget.memory_bytes,
        child_calls: budget.child_calls,
        outbound_requests: budget.outbound_requests,
        state_read_bytes: budget.state_read_bytes,
        state_write_bytes: budget.state_write_bytes,
        blob_read_bytes: budget.blob_read_bytes,
        blob_write_bytes: budget.blob_write_bytes,
        log_bytes: budget.log_bytes,
        effect_count: budget.effect_count,
        wall_time_limit_millis: budget.wall_time_limit_millis,
    }
}

#[must_use]
pub fn budget_from_proto(budget: proto::ResourceBudget) -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: budget.cpu_fuel,
        memory_bytes: budget.memory_bytes,
        wall_time_limit_millis: budget.wall_time_limit_millis,
        child_calls: budget.child_calls,
        outbound_requests: budget.outbound_requests,
        state_read_bytes: budget.state_read_bytes,
        state_write_bytes: budget.state_write_bytes,
        blob_read_bytes: budget.blob_read_bytes,
        blob_write_bytes: budget.blob_write_bytes,
        log_bytes: budget.log_bytes,
        effect_count: budget.effect_count,
    }
}

#[must_use]
pub fn consumption_to_proto(consumption: &BudgetConsumption) -> proto::BudgetConsumption {
    proto::BudgetConsumption {
        cpu_fuel: consumption.cpu_fuel,
        peak_memory_bytes: consumption.peak_memory_bytes,
        wall_time_micros: consumption.wall_time_micros,
        child_calls: consumption.child_calls,
        outbound_requests: consumption.outbound_requests,
        state_read_bytes: consumption.state_read_bytes,
        state_write_bytes: consumption.state_write_bytes,
        blob_read_bytes: consumption.blob_read_bytes,
        blob_write_bytes: consumption.blob_write_bytes,
        log_bytes: consumption.log_bytes,
        effect_count: consumption.effect_count,
    }
}

#[must_use]
pub fn consumption_from_proto(consumption: proto::BudgetConsumption) -> BudgetConsumption {
    BudgetConsumption {
        cpu_fuel: consumption.cpu_fuel,
        peak_memory_bytes: consumption.peak_memory_bytes,
        wall_time_micros: consumption.wall_time_micros,
        child_calls: consumption.child_calls,
        outbound_requests: consumption.outbound_requests,
        state_read_bytes: consumption.state_read_bytes,
        state_write_bytes: consumption.state_write_bytes,
        blob_read_bytes: consumption.blob_read_bytes,
        blob_write_bytes: consumption.blob_write_bytes,
        log_bytes: consumption.log_bytes,
        effect_count: consumption.effect_count,
    }
}

#[must_use]
pub fn declared_error_to_proto(error: &DeclaredError) -> proto::DeclaredError {
    proto::DeclaredError {
        code: error.code.clone(),
        message: error.message.clone(),
        payload: error.payload.clone(),
        media_type: error.media_type.clone(),
        metadata: error.metadata.clone().into_iter().collect(),
    }
}

#[must_use]
pub fn declared_error_from_proto(error: proto::DeclaredError) -> DeclaredError {
    DeclaredError {
        code: error.code,
        message: error.message,
        payload: error.payload,
        media_type: error.media_type,
        metadata: error.metadata.into_iter().collect(),
    }
}

#[must_use]
pub fn platform_error_to_proto(error: &PlatformError) -> proto::PlatformError {
    proto::PlatformError::from(error)
}

pub fn platform_error_from_proto(
    error: proto::PlatformError,
) -> Result<PlatformError, InvocationConversionError> {
    error
        .try_into_domain()
        .map_err(|_| InvocationConversionError::new("platform error code is unknown to this build"))
}

pub(super) fn public_invocation_response_to_proto(
    response: InvocationResponse,
    limits: &InvocationLimits,
) -> proto::InvokeResponse {
    let (result, consumption) = owned_outcome_to_proto(response.outcome, limits);
    let pin = response.receipt.resolved_revision;
    let (revision_id, release_digest, route_generation) = pin.map_or_else(
        || (String::new(), String::new(), 0),
        |pin| {
            (
                pin.revision_id.0,
                pin.release_digest.0,
                pin.route_generation.0,
            )
        },
    );
    proto::InvokeResponse {
        activation_id: response.receipt.activation_id.0,
        revision_id,
        release_digest,
        route_generation,
        result: Some(result),
        consumption: Some(consumption_to_proto(&consumption)),
    }
}

pub(super) fn public_activation_status_to_proto(
    status: ActivationStatus,
    limits: &InvocationLimits,
) -> proto::ActivationStatus {
    let terminal_outcome = status.terminal_outcome.map(|outcome| match outcome {
        RetainedActivationOutcome::Succeeded(summary) => {
            proto::activation_status::TerminalOutcome::Succeeded(proto::ActivationSuccessSummary {
                committed_state_version: summary.committed_state_version,
                effect_ids: summary.effect_ids,
                metadata: summary.metadata.into_iter().collect(),
            })
        }
        RetainedActivationOutcome::DeclaredError(error) => {
            proto::activation_status::TerminalOutcome::DeclaredError(owned_declared_error(error))
        }
        RetainedActivationOutcome::PlatformFailure(error) => {
            proto::activation_status::TerminalOutcome::PlatformFailure(
                public_platform_error(error, limits).into(),
            )
        }
    });
    proto::ActivationStatus {
        activation_id: status.activation_id.0,
        phase: activation_phase_name(status.phase).to_owned(),
        terminal_state: status
            .terminal_state
            .map(|state| terminal_state_name(state).to_owned()),
        terminal_outcome,
        final_consumption: status.final_consumption.as_ref().map(consumption_to_proto),
        last_updated_unix_millis: status.last_updated_unix_millis,
        terminal_at_unix_millis: status.terminal_at_unix_millis,
        metadata: status.metadata.into_iter().collect(),
    }
}

fn outcome_to_proto(
    outcome: &ActivationOutcome,
) -> (proto::invoke_response::Result, &BudgetConsumption) {
    match outcome {
        ActivationOutcome::Succeeded(success) => (
            proto::invoke_response::Result::Success(proto::Success {
                payload: success.output.clone(),
                media_type: success.output_media_type.clone(),
                committed_state_version: success.committed_state_version.clone(),
                effect_ids: success.effect_ids.clone(),
                metadata: success.metadata.clone().into_iter().collect(),
            }),
            &success.consumption,
        ),
        ActivationOutcome::DeclaredError { error, consumption } => (
            proto::invoke_response::Result::DeclaredError(declared_error_to_proto(error)),
            consumption,
        ),
        ActivationOutcome::Failed {
            error, consumption, ..
        } => (
            proto::invoke_response::Result::PlatformFailure(platform_error_to_proto(error)),
            consumption,
        ),
    }
}

fn owned_declared_error(error: DeclaredError) -> proto::DeclaredError {
    proto::DeclaredError {
        code: error.code,
        message: error.message,
        payload: error.payload,
        media_type: error.media_type,
        metadata: error.metadata.into_iter().collect(),
    }
}

fn owned_outcome_to_proto(
    outcome: ActivationOutcome,
    limits: &InvocationLimits,
) -> (proto::invoke_response::Result, BudgetConsumption) {
    match outcome {
        ActivationOutcome::Succeeded(success) => (
            proto::invoke_response::Result::Success(proto::Success {
                payload: success.output,
                media_type: success.output_media_type,
                committed_state_version: success.committed_state_version,
                effect_ids: success.effect_ids,
                metadata: success.metadata.into_iter().collect(),
            }),
            success.consumption,
        ),
        ActivationOutcome::DeclaredError { error, consumption } => (
            proto::invoke_response::Result::DeclaredError(owned_declared_error(error)),
            consumption,
        ),
        ActivationOutcome::Failed {
            error, consumption, ..
        } => (
            proto::invoke_response::Result::PlatformFailure(
                public_platform_error(error, limits).into(),
            ),
            consumption,
        ),
    }
}

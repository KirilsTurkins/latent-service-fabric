pub fn cancel_disposition_from_proto(
    response: proto::CancelResponse,
) -> Result<CancelDisposition, InvocationConversionError> {
    match proto::CancelDisposition::try_from(response.disposition) {
        Ok(proto::CancelDisposition::Accepted) if response.terminal_state.is_none() => {
            Ok(CancelDisposition::Accepted)
        }
        Ok(proto::CancelDisposition::AlreadyTerminal) => {
            let state = response.terminal_state.as_deref().ok_or_else(|| {
                InvocationConversionError::new(
                    "already-terminal cancellation is missing its terminal state",
                )
            })?;
            Ok(CancelDisposition::AlreadyTerminal(parse_terminal_state(
                state,
            )?))
        }
        Ok(proto::CancelDisposition::NotFound) if response.terminal_state.is_none() => {
            Ok(CancelDisposition::NotFound)
        }
        Ok(proto::CancelDisposition::Unspecified) | Err(_) => Err(
            InvocationConversionError::new("cancellation disposition is unspecified or unknown"),
        ),
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
        .map_err(|error| InvocationConversionError::new(error.to_string()))
}

pub(super) fn public_invocation_response_to_proto(
    response: InvocationResponse,
    limits: &InvocationLimits,
) -> proto::InvokeResponse {
    let (result, consumption) = outcome_to_proto(&response.outcome, true, Some(limits));
    proto::InvokeResponse {
        activation_id: response.receipt.activation_id.0,
        revision_id: response.receipt.revision_id.0,
        release_digest: response.receipt.release_digest.0,
        route_generation: response.receipt.route_generation.0,
        result: Some(result),
        consumption: Some(consumption_to_proto(consumption)),
    }
}

pub(super) fn public_activation_status_to_proto(
    status: ActivationStatus,
    limits: &InvocationLimits,
) -> proto::ActivationStatus {
    status_to_proto(&status, true, Some(limits))
}

fn outcome_to_proto<'a>(
    outcome: &'a ActivationOutcome,
    public: bool,
    limits: Option<&InvocationLimits>,
) -> (proto::invoke_response::Result, &'a BudgetConsumption) {
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
        } => {
            let error = if public {
                public_platform_error(error, limits.expect("public conversion requires limits"))
            } else {
                error.clone()
            };
            (
                proto::invoke_response::Result::PlatformFailure(platform_error_to_proto(&error)),
                consumption,
            )
        }
    }
}
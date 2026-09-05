/// A malformed or semantically contradictory generated invocation message.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvocationConversionError {
    message: String,
}

impl InvocationConversionError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }

    #[must_use]
    pub fn message(&self) -> &str {
        &self.message
    }
}

impl fmt::Display for InvocationConversionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl std::error::Error for InvocationConversionError {}

#[must_use]

pub fn invocation_request_to_proto(request: &InvocationRequest) -> proto::InvokeRequest {
    proto::InvokeRequest {
        activation_id: request
            .requested_activation_id
            .as_ref()
            .map(|activation_id| activation_id.0.clone()),
        parent_activation_id: request
            .parent_activation_id
            .as_ref()
            .map(|activation_id| activation_id.0.clone()),
        root_activation_id: request
            .root_activation_id
            .as_ref()
            .map(|activation_id| activation_id.0.clone()),
        target: Some(proto::InvocationTarget {
            tenant: request.target.tenant.0.clone(),
            service: request.target.service.0.clone(),
            contract: request.target.contract.0.clone(),
            function: request.target.function.0.clone(),
            route: request.target.route.clone(),
        }),
        payload: request.payload.clone(),
        media_type: request.media_type.clone(),
        deadline_unix_millis: request.deadline_unix_millis,
        priority: u32::from(request.priority),
        idempotency_key: request
            .idempotency_key
            .as_ref()
            .map(|key| key.0.clone()),
        budget: Some(budget_to_proto(&request.budget)),
        metadata: request.metadata.clone().into_iter().collect(),
    }
}

pub fn invocation_request_from_proto(
    request: proto::InvokeRequest,
) -> Result<InvocationRequest, InvocationConversionError> {
    let target = request
        .target
        .ok_or_else(|| InvocationConversionError::new("invocation target is missing"))?;
    let budget = request
        .budget
        .ok_or_else(|| InvocationConversionError::new("resource budget is missing"))?;
    let priority = u8::try_from(request.priority)
        .map_err(|_| InvocationConversionError::new("priority does not fit in an unsigned byte"))?;
    Ok(InvocationRequest {
        requested_activation_id: request.activation_id.map(latent_core::ActivationId),
        parent_activation_id: request.parent_activation_id.map(latent_core::ActivationId),
        root_activation_id: request.root_activation_id.map(latent_core::ActivationId),
        target: latent_routing::InvocationTarget {
            tenant: latent_core::TenantId(target.tenant),
            service: latent_core::ServiceId(target.service),
            contract: latent_core::ContractId(target.contract),
            function: latent_core::FunctionId(target.function),
            route: target.route,
        },
        payload: request.payload,
        media_type: request.media_type,
        deadline_unix_millis: request.deadline_unix_millis,
        priority,
        idempotency_key: request.idempotency_key.map(latent_core::IdempotencyKey),
        budget: budget_from_proto(budget),
        metadata: request.metadata.into_iter().collect(),
    })
}

#[must_use]
pub fn invocation_response_to_proto(response: &InvocationResponse) -> proto::InvokeResponse {
    let (result, consumption) = outcome_to_proto(&response.outcome, false, None);
    proto::InvokeResponse {
        activation_id: response.receipt.activation_id.0.clone(),
        revision_id: response.receipt.revision_id.0.clone(),
        release_digest: response.receipt.release_digest.0.clone(),
        route_generation: response.receipt.route_generation.0,
        result: Some(result),
        consumption: Some(consumption_to_proto(consumption)),
    }
}

pub fn invocation_response_from_proto(
    response: proto::InvokeResponse,
) -> Result<InvocationResponse, InvocationConversionError> {
    let consumption = response
        .consumption
        .map(consumption_from_proto)
        .ok_or_else(|| InvocationConversionError::new("final consumption is missing"))?;
    let outcome = match response
        .result
        .ok_or_else(|| InvocationConversionError::new("invocation result is missing"))?
    {
        proto::invoke_response::Result::Success(success) => {
            ActivationOutcome::Succeeded(ActivationSuccess {
                output: success.payload,
                output_media_type: success.media_type,
                consumption,
                committed_state_version: success.committed_state_version,
                effect_ids: success.effect_ids,
                metadata: success.metadata.into_iter().collect(),
            })
        }
        proto::invoke_response::Result::DeclaredError(error) => {
            ActivationOutcome::DeclaredError {
                error: declared_error_from_proto(error),
                consumption,
            }
        }
        proto::invoke_response::Result::PlatformFailure(error) => {
            let error = platform_error_from_proto(error)?;
            ActivationOutcome::Failed {
                terminal_state: terminal_state_for_platform_error(error.code),
                error,
                consumption,
            }
        }
    };
    Ok(InvocationResponse {
        receipt: InvocationReceipt {
            activation_id: latent_core::ActivationId(response.activation_id),
            revision_id: latent_core::RevisionId(response.revision_id),
            release_digest: latent_core::ReleaseDigest(response.release_digest),
            route_generation: latent_core::RouteGeneration(response.route_generation),
        },
        outcome,
    })
}

#[must_use]
pub fn activation_status_to_proto(status: &ActivationStatus) -> proto::ActivationStatus {
    status_to_proto(status, false, None)
}

pub fn activation_status_from_proto(
    status: proto::ActivationStatus,
) -> Result<ActivationStatus, InvocationConversionError> {
    let terminal_outcome = status
        .terminal_outcome
        .map(|outcome| match outcome {
            proto::activation_status::TerminalOutcome::Succeeded(summary) => {
                Ok(RetainedActivationOutcome::Succeeded(ActivationSuccessSummary {
                    committed_state_version: summary.committed_state_version,
                    effect_ids: summary.effect_ids,
                    metadata: summary.metadata.into_iter().collect(),
                }))
            }
            proto::activation_status::TerminalOutcome::DeclaredError(error) => {
                Ok(RetainedActivationOutcome::DeclaredError(
                    declared_error_from_proto(error),
                ))
            }
            proto::activation_status::TerminalOutcome::PlatformFailure(error) => {
                Ok(RetainedActivationOutcome::PlatformFailure(
                    platform_error_from_proto(error)?,
                ))
            }
        })
        .transpose()?;
    Ok(ActivationStatus {
        activation_id: latent_core::ActivationId(status.activation_id),
        phase: parse_activation_phase(&status.phase)?,
        terminal_state: status
            .terminal_state
            .as_deref()
            .map(parse_terminal_state)
            .transpose()?,
        terminal_outcome,
        final_consumption: status.final_consumption.map(consumption_from_proto),
        last_updated_unix_millis: status.last_updated_unix_millis,
        terminal_at_unix_millis: status.terminal_at_unix_millis,
        metadata: status.metadata.into_iter().collect(),
    })
}

#[must_use]
pub fn cancel_disposition_to_proto(disposition: CancelDisposition) -> proto::CancelResponse {
    match disposition {
        CancelDisposition::Accepted => proto::CancelResponse {
            disposition: proto::CancelDisposition::Accepted as i32,
            terminal_state: None,
        },
        CancelDisposition::AlreadyTerminal(state) => proto::CancelResponse {
            disposition: proto::CancelDisposition::AlreadyTerminal as i32,
            terminal_state: Some(terminal_state_name(state).to_owned()),
        },
        CancelDisposition::NotFound => proto::CancelResponse {
            disposition: proto::CancelDisposition::NotFound as i32,
            terminal_state: None,
        },
    }
}
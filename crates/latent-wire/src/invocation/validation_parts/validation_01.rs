pub(super) struct DeadlinePlan {
    pub(super) effective_unix_millis: Option<u64>,
    pub(super) delay: Option<Duration>,
}

pub(super) fn deadline_plan(
    request: &Request<proto::InvokeRequest>,
    context_deadline_unix_millis: Option<u64>,
    now_unix_millis: u64,
    limits: &InvocationLimits,
) -> Result<DeadlinePlan, Status> {
    let caller_deadline = request.get_ref().deadline_unix_millis;
    let caller_delay = caller_deadline
        .map(|deadline| {
            bounded_absolute_deadline(
                "caller deadline",
                deadline,
                now_unix_millis,
                limits.max_timeout_millis,
            )
        })
        .transpose()?;
    let context_delay = context_deadline_unix_millis
        .map(|deadline| {
            bounded_absolute_deadline(
                "transport deadline",
                deadline,
                now_unix_millis,
                limits.max_timeout_millis,
            )
        })
        .transpose()?;
    let header_delay = grpc_timeout(request)?;
    if header_delay.is_some_and(|duration| {
        duration > Duration::from_millis(limits.max_timeout_millis)
    }) {
        return Err(Status::invalid_argument(
            "transport timeout exceeds the configured maximum",
        ));
    }
    if header_delay == Some(Duration::ZERO) {
        return Err(Status::deadline_exceeded(
            "the invocation deadline was exceeded",
        ));
    }

    let header_deadline = header_delay.map(|duration| {
        now_unix_millis.saturating_add(duration_to_ceil_millis(duration))
    });
    Ok(DeadlinePlan {
        effective_unix_millis: minimum_deadline([
            caller_deadline,
            context_deadline_unix_millis,
            header_deadline,
        ]),
        delay: minimum_duration([caller_delay, context_delay, header_delay]),
    })
}

pub(super) fn validate_invoke<P: PrincipalPolicy>(
    request: proto::InvokeRequest,
    principal: InvocationPrincipal,
    effective_deadline_unix_millis: Option<u64>,
    limits: &InvocationLimits,
    principals: &P,
) -> Result<super::InvocationCommand, Status> {
    ensure_message_size(&request, limits.max_message_bytes, "invocation request")?;
    if request.payload.len() > limits.max_payload_bytes {
        return Err(Status::resource_exhausted(
            "invocation payload exceeds the configured limit",
        ));
    }
    validate_media_type(&request.media_type, limits.max_string_bytes)?;
    validate_metadata(&request.metadata, limits)?;
    validate_optional_identifier(
        "activation_id",
        request.activation_id.as_deref(),
        limits.max_id_bytes,
    )?;
    validate_optional_identifier(
        "parent_activation_id",
        request.parent_activation_id.as_deref(),
        limits.max_id_bytes,
    )?;
    validate_optional_identifier(
        "root_activation_id",
        request.root_activation_id.as_deref(),
        limits.max_id_bytes,
    )?;
    validate_optional_identifier(
        "idempotency_key",
        request.idempotency_key.as_deref(),
        limits.max_id_bytes,
    )?;
    if request.priority > u32::from(u8::MAX) {
        return Err(Status::invalid_argument(
            "priority must fit in an unsigned byte",
        ));
    }

    let target = request
        .target
        .as_ref()
        .ok_or_else(|| Status::invalid_argument("invocation target is required"))?;
    validate_target(target, limits)?;
    principals
        .authorize_target(&principal, &target.tenant)
        .map_err(super::platform_status)?;
    let budget = request
        .budget
        .as_ref()
        .ok_or_else(|| Status::invalid_argument("resource budget is required"))?;
    validate_budget(budget, limits)?;

    let mut request = invocation_request_from_proto(request)
        .map_err(|error| Status::invalid_argument(error.to_string()))?;
    request.deadline_unix_millis = effective_deadline_unix_millis;
    Ok(super::InvocationCommand { principal, request })
}

pub(super) fn validate_cancel(
    request: proto::CancelRequest,
    limits: &InvocationLimits,
) -> Result<proto::CancelRequest, Status> {
    ensure_message_size(&request, limits.max_message_bytes, "cancel request")?;
    validate_identifier(
        "activation_id",
        &request.activation_id,
        limits.max_id_bytes,
    )?;
    if request.reason.len() > limits.max_cancel_reason_bytes {
        return Err(Status::resource_exhausted(
            "cancellation reason exceeds the configured limit",
        ));
    }
    if request.reason.bytes().any(|byte| byte.is_ascii_control()) {
        return Err(Status::invalid_argument(
            "cancellation reason contains a control character",
        ));
    }
    Ok(request)
}

pub(super) fn validate_status_query(
    request: proto::GetActivationRequest,
    limits: &InvocationLimits,
) -> Result<ActivationId, Status> {
    ensure_message_size(&request, limits.max_message_bytes, "status request")?;
    validate_identifier(
        "activation_id",
        &request.activation_id,
        limits.max_id_bytes,
    )?;
    Ok(ActivationId(request.activation_id))
}

pub(super) fn validate_runtime_response(
    response: &InvocationResponse,
    limits: &InvocationLimits,
) -> Result<(), Status> {
    if !trusted_identifier(&response.receipt.activation_id.0, limits.max_id_bytes)
        || !trusted_identifier(&response.receipt.revision_id.0, limits.max_id_bytes)
        || !trusted_identifier(&response.receipt.release_digest.0, limits.max_id_bytes)
    {
        return Err(Status::internal(
            "the invocation runtime returned an invalid receipt",
        ));
    }
    match &response.outcome {
        ActivationOutcome::Succeeded(success) => {
            if success.output.len() > limits.max_payload_bytes {
                return Err(Status::resource_exhausted(
                    "invocation response payload exceeds the configured limit",
                ));
            }
            validate_runtime_media_type(&success.output_media_type, limits)?;
            validate_runtime_metadata(&success.metadata, limits)?;
        }
        ActivationOutcome::DeclaredError { error, .. } => {
            if error.payload.len() > limits.max_payload_bytes {
                return Err(Status::resource_exhausted(
                    "declared-error payload exceeds the configured limit",
                ));
            }
            validate_runtime_media_type(&error.media_type, limits)?;
            validate_runtime_metadata(&error.metadata, limits)?;
        }
        ActivationOutcome::Failed { .. } => {}
    }
    Ok(())
}

pub(super) fn validate_runtime_status(
    status: &ActivationStatus,
    requested_activation_id: &ActivationId,
    limits: &InvocationLimits,
) -> Result<(), Status> {
    if &status.activation_id != requested_activation_id {
        return Err(Status::internal(
            "the invocation runtime returned status for a different activation",
        ));
    }
    validate_runtime_metadata(&status.metadata, limits)?;
    match status.terminal_state {
        Some(_) => {
            if status.terminal_outcome.is_none()
                || status.final_consumption.is_none()
                || status.terminal_at_unix_millis.is_none()
            {
                return Err(Status::internal(
                    "terminal activation status is missing diagnostic accounting",
                ));
            }
            match status.terminal_outcome.as_ref() {
                Some(RetainedActivationOutcome::Succeeded(summary)) => {
                    validate_runtime_metadata(&summary.metadata, limits)?;
                }
                Some(RetainedActivationOutcome::DeclaredError(error)) => {
                    if error.payload.len() > limits.max_payload_bytes {
                        return Err(Status::resource_exhausted(
                            "retained declared-error payload exceeds the configured limit",
                        ));
                    }
                    validate_runtime_media_type(&error.media_type, limits)?;
                    validate_runtime_metadata(&error.metadata, limits)?;
                }
                Some(RetainedActivationOutcome::PlatformFailure(_)) | None => {}
            }
        }
        None => {
            if status.terminal_outcome.is_some()
                || status.final_consumption.is_some()
                || status.terminal_at_unix_millis.is_some()
            {
                return Err(Status::internal(
                    "active activation status contains terminal-only fields",
                ));
            }
        }
    }
    Ok(())
}
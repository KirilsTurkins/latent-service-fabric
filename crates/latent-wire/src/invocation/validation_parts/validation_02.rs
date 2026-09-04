fn validate_target(
    target: &proto::InvocationTarget,
    limits: &InvocationLimits,
) -> Result<(), Status> {
    validate_identifier("target.tenant", &target.tenant, limits.max_id_bytes)?;
    validate_identifier("target.service", &target.service, limits.max_id_bytes)?;
    validate_identifier("target.contract", &target.contract, limits.max_id_bytes)?;
    validate_identifier("target.function", &target.function, limits.max_id_bytes)?;
    validate_optional_identifier(
        "target.route",
        target.route.as_deref(),
        limits.max_string_bytes,
    )
}

fn validate_optional_identifier(
    name: &str,
    value: Option<&str>,
    maximum: usize,
) -> Result<(), Status> {
    if let Some(value) = value {
        validate_identifier(name, value, maximum)?;
    }
    Ok(())
}

fn validate_identifier(name: &str, value: &str, maximum: usize) -> Result<(), Status> {
    if value.is_empty() {
        return Err(Status::invalid_argument(format!(
            "{name} must not be empty"
        )));
    }
    if value.len() > maximum {
        return Err(Status::resource_exhausted(format!(
            "{name} exceeds the configured byte limit"
        )));
    }
    if !identifier_bytes_are_valid(value) {
        return Err(Status::invalid_argument(format!(
            "{name} contains unsupported characters"
        )));
    }
    Ok(())
}

fn trusted_identifier(value: &str, maximum: usize) -> bool {
    !value.is_empty() && value.len() <= maximum && identifier_bytes_are_valid(value)
}

fn identifier_bytes_are_valid(value: &str) -> bool {
    value.bytes().all(|byte| {
        byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b':' | b'/' | b'@')
    })
}

fn validate_media_type(value: &str, maximum: usize) -> Result<(), Status> {
    if value.is_empty() {
        return Err(Status::invalid_argument("media_type is required"));
    }
    if value.len() > maximum {
        return Err(Status::resource_exhausted(
            "media_type exceeds the configured byte limit",
        ));
    }
    if value.bytes().any(|byte| byte.is_ascii_control()) {
        return Err(Status::invalid_argument(
            "media_type contains a control character",
        ));
    }
    Ok(())
}

fn validate_metadata(
    metadata: &std::collections::HashMap<String, String>,
    limits: &InvocationLimits,
) -> Result<(), Status> {
    if metadata.len() > limits.max_metadata_entries {
        return Err(Status::resource_exhausted(
            "metadata contains too many entries",
        ));
    }
    let mut total = 0_usize;
    for (key, value) in metadata {
        if key.is_empty() {
            return Err(Status::invalid_argument(
                "metadata keys must not be empty",
            ));
        }
        if key.len() > limits.max_string_bytes || value.len() > limits.max_string_bytes {
            return Err(Status::resource_exhausted(
                "metadata key or value exceeds the configured byte limit",
            ));
        }
        if key.bytes().any(|byte| byte.is_ascii_control())
            || value.bytes().any(|byte| byte.is_ascii_control())
        {
            return Err(Status::invalid_argument(
                "metadata contains a control character",
            ));
        }
        let lower = key.to_ascii_lowercase();
        if lower.starts_with("latent.auth.") || lower.starts_with("latent.principal.") {
            return Err(Status::invalid_argument(
                "caller metadata must not contain authentication fields",
            ));
        }
        total = total
            .saturating_add(key.len())
            .saturating_add(value.len());
    }
    if total > limits.max_metadata_bytes {
        return Err(Status::resource_exhausted(
            "metadata exceeds the configured aggregate byte limit",
        ));
    }
    Ok(())
}

fn validate_budget(
    budget: &proto::ResourceBudget,
    limits: &InvocationLimits,
) -> Result<(), Status> {
    let valid = budget.cpu_fuel <= limits.max_cpu_fuel
        && budget.memory_bytes <= limits.max_memory_bytes
        && budget.child_calls <= limits.max_child_calls
        && budget.outbound_requests <= limits.max_outbound_requests
        && budget.state_read_bytes <= limits.max_state_read_bytes
        && budget.state_write_bytes <= limits.max_state_write_bytes
        && budget.blob_read_bytes <= limits.max_blob_read_bytes
        && budget.blob_write_bytes <= limits.max_blob_write_bytes
        && budget.log_bytes <= limits.max_log_bytes
        && budget.effect_count <= limits.max_effect_count
        && budget
            .wall_time_limit_millis
            .is_none_or(|value| value <= limits.max_timeout_millis);
    if valid {
        Ok(())
    } else {
        Err(Status::resource_exhausted(
            "resource budget exceeds the configured RPC ceiling",
        ))
    }
}

fn validate_runtime_media_type(
    value: &str,
    limits: &InvocationLimits,
) -> Result<(), Status> {
    validate_media_type(value, limits.max_string_bytes)
        .map_err(|_| Status::internal("the invocation runtime returned an invalid media type"))
}

fn validate_runtime_metadata(
    metadata: &latent_core::Metadata,
    limits: &InvocationLimits,
) -> Result<(), Status> {
    let metadata: std::collections::HashMap<String, String> =
        metadata.clone().into_iter().collect();
    validate_metadata(&metadata, limits)
        .map_err(|_| Status::internal("the invocation runtime returned invalid metadata"))
}

fn ensure_message_size<M: Message>(
    message: &M,
    maximum: usize,
    description: &str,
) -> Result<(), Status> {
    if message.encoded_len() > maximum {
        Err(Status::resource_exhausted(format!(
            "{description} exceeds the configured message limit"
        )))
    } else {
        Ok(())
    }
}

fn bounded_absolute_deadline(
    name: &str,
    deadline_unix_millis: u64,
    now_unix_millis: u64,
    maximum_timeout_millis: u64,
) -> Result<Duration, Status> {
    if deadline_unix_millis <= now_unix_millis {
        return Err(Status::deadline_exceeded(format!("{name} has expired")));
    }
    let delay_millis = deadline_unix_millis.saturating_sub(now_unix_millis);
    if delay_millis > maximum_timeout_millis {
        return Err(Status::invalid_argument(format!(
            "{name} exceeds the configured maximum timeout"
        )));
    }
    Ok(Duration::from_millis(delay_millis))
}

fn grpc_timeout(request: &Request<proto::InvokeRequest>) -> Result<Option<Duration>, Status> {
    let Some(value) = request.metadata().get("grpc-timeout") else {
        return Ok(None);
    };
    let value = value
        .to_str()
        .map_err(|_| Status::invalid_argument("grpc-timeout metadata is not valid ASCII"))?;
    if value.is_empty() || value.len() > 9 {
        return Err(Status::invalid_argument(
            "grpc-timeout metadata is malformed",
        ));
    }
    let (digits, unit) = value.split_at(value.len() - 1);
    if digits.is_empty() || digits.len() > 8 || !digits.bytes().all(|byte| byte.is_ascii_digit()) {
        return Err(Status::invalid_argument(
            "grpc-timeout metadata is malformed",
        ));
    }
    let value = digits
        .parse::<u64>()
        .map_err(|_| Status::invalid_argument("grpc-timeout metadata is malformed"))?;
    let duration = match unit {
        "H" => Duration::from_secs(value.saturating_mul(60 * 60)),
        "M" => Duration::from_secs(value.saturating_mul(60)),
        "S" => Duration::from_secs(value),
        "m" => Duration::from_millis(value),
        "u" => Duration::from_micros(value),
        "n" => Duration::from_nanos(value),
        _ => {
            return Err(Status::invalid_argument(
                "grpc-timeout metadata uses an unsupported unit",
            ));
        }
    };
    Ok(Some(duration))
}

fn duration_to_ceil_millis(duration: Duration) -> u64 {
    let milliseconds = duration.as_millis();
    let rounded = if duration.subsec_nanos() % 1_000_000 == 0 {
        milliseconds
    } else {
        milliseconds.saturating_add(1)
    };
    u64::try_from(rounded).unwrap_or(u64::MAX)
}

fn minimum_deadline<const N: usize>(deadlines: [Option<u64>; N]) -> Option<u64> {
    deadlines.into_iter().flatten().min()
}

fn minimum_duration<const N: usize>(durations: [Option<Duration>; N]) -> Option<Duration> {
    durations.into_iter().flatten().min()
}
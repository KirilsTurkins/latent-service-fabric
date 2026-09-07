use latent_activation::{ActivationOutcome, ActivationStatus, RetainedActivationOutcome};
use latent_core::{ActivationId, DeclaredError, ErrorDetail, Metadata, PlatformError};
use tonic::Status;

use super::super::{conversion, InvocationLimits, InvocationResponse};
use super::fields::{
    exhausted, identifier, media_type, runtime_error, RetainedBytes, GENERATED_ACTIVATION_ID_BYTES,
};

pub(in super::super) fn validate_runtime_response(
    response: &InvocationResponse,
    limits: &InvocationLimits,
) -> Result<(), Status> {
    validate_response(response, limits).map_err(runtime_error)
}

fn validate_response(
    response: &InvocationResponse,
    limits: &InvocationLimits,
) -> Result<(), Status> {
    let mut bytes = RetainedBytes::new::<InvocationResponse>(limits)?;
    let maximum = limits.max_id_bytes.max(GENERATED_ACTIVATION_ID_BYTES);
    bytes.string(&response.receipt.activation_id.0, maximum)?;
    identifier(&response.receipt.activation_id.0, maximum)?;
    if let Some(pin) = &response.receipt.resolved_revision {
        // Generated catalog identities have their own fixed-size allowance;
        // a short caller-name bound must not reject every genuine revision.
        let maximum = limits.max_id_bytes.max(83);
        for value in [&pin.revision_id.0, &pin.release_digest.0] {
            bytes.string(value, maximum)?;
            identifier(value, maximum)?;
        }
    }
    conversion::validate_response_shape(response)
        .map_err(|_| Status::internal("the invocation runtime returned an invalid receipt"))?;
    match &response.outcome {
        ActivationOutcome::Succeeded(success) => {
            bytes.payload(&success.output, limits.max_payload_bytes)?;
            bytes.string(&success.output_media_type, limits.max_string_bytes)?;
            media_type(&success.output_media_type, limits.max_string_bytes)?;
            summary(
                &mut bytes,
                success.committed_state_version.as_ref(),
                &success.effect_ids,
                &success.metadata,
                limits,
            )
        }
        ActivationOutcome::DeclaredError { error, .. } => declared(&mut bytes, error, limits),
        ActivationOutcome::Failed { error, .. } => platform(&mut bytes, error, limits),
    }
}

pub(in super::super) fn validate_runtime_status(
    status: &ActivationStatus,
    requested_activation_id: &ActivationId,
    limits: &InvocationLimits,
) -> Result<(), Status> {
    validate_status(status, requested_activation_id, limits).map_err(runtime_error)
}

fn validate_status(
    status: &ActivationStatus,
    requested: &ActivationId,
    limits: &InvocationLimits,
) -> Result<(), Status> {
    let mut bytes = RetainedBytes::new::<ActivationStatus>(limits)?;
    let maximum = limits.max_id_bytes.max(GENERATED_ACTIVATION_ID_BYTES);
    bytes.string(&status.activation_id.0, maximum)?;
    identifier(&status.activation_id.0, maximum)?;
    if &status.activation_id != requested {
        return Err(Status::internal(
            "the invocation runtime returned status for a different activation",
        ));
    }
    bytes.metadata(&status.metadata, limits, limits.max_metadata_entries, false)?;
    conversion::validate_status_shape(status).map_err(|_| {
        Status::internal("the invocation runtime returned contradictory terminal status")
    })?;
    match &status.terminal_outcome {
        Some(RetainedActivationOutcome::Succeeded(value)) => summary(
            &mut bytes,
            value.committed_state_version.as_ref(),
            &value.effect_ids,
            &value.metadata,
            limits,
        ),
        Some(RetainedActivationOutcome::DeclaredError(error)) => {
            declared(&mut bytes, error, limits)
        }
        Some(RetainedActivationOutcome::PlatformFailure(error)) => {
            platform(&mut bytes, error, limits)
        }
        None => Ok(()),
    }
}

fn summary(
    bytes: &mut RetainedBytes,
    version: Option<&String>,
    effects: &Vec<String>,
    metadata: &Metadata,
    limits: &InvocationLimits,
) -> Result<(), Status> {
    if effects.len() > limits.max_metadata_entries {
        return Err(exhausted());
    }
    bytes.allocation::<String>(effects.capacity())?;
    if let Some(version) = version {
        bytes.string(version, limits.max_string_bytes)?;
    }
    for value in effects {
        bytes.string(value, limits.max_string_bytes)?;
        identifier(value, limits.max_string_bytes)?;
    }
    bytes.metadata(metadata, limits, limits.max_metadata_entries, false)
}

fn declared(
    bytes: &mut RetainedBytes,
    error: &DeclaredError,
    limits: &InvocationLimits,
) -> Result<(), Status> {
    bytes.payload(&error.payload, limits.max_payload_bytes)?;
    for value in [&error.code, &error.message, &error.media_type] {
        bytes.string(value, limits.max_string_bytes)?;
    }
    identifier(&error.code, limits.max_string_bytes)?;
    media_type(&error.media_type, limits.max_string_bytes)?;
    bytes.metadata(&error.metadata, limits, limits.max_metadata_entries, false)
}

fn platform(
    bytes: &mut RetainedBytes,
    error: &PlatformError,
    limits: &InvocationLimits,
) -> Result<(), Status> {
    bytes.string(&error.message, limits.max_string_bytes)?;
    if error.details.len() > limits.max_platform_error_details {
        return Err(exhausted());
    }
    bytes.allocation::<ErrorDetail>(error.details.capacity())?;
    for detail in &error.details {
        bytes.string(&detail.kind, limits.max_string_bytes)?;
        bytes.metadata(
            &detail.fields,
            limits,
            limits.max_platform_error_fields,
            false,
        )?;
    }
    Ok(())
}

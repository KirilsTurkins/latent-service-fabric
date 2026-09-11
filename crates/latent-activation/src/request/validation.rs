use std::mem::size_of;

use latent_core::{Metadata, PlatformError, PlatformErrorCode, PrincipalKind};

use super::{error, ActivationRequest, ActivationRequestLimits};

pub(super) fn validate(
    request: &ActivationRequest,
    limits: ActivationRequestLimits,
) -> Result<(), PlatformError> {
    if request.input.capacity() > limits.maximum_input_bytes {
        return Err(exhausted());
    }
    if request.principal.tenant.as_ref() != Some(&request.target.tenant)
        || request.principal.kind == PrincipalKind::Anonymous
        || (request.principal.kind == PrincipalKind::Service && request.principal.service.is_none())
    {
        return Err(error(
            PlatformErrorCode::PermissionDenied,
            "activation-principal-not-authorized",
        ));
    }
    if request.parent_activation_id.is_some() && request.root_activation_id.is_none() {
        return Err(error(
            PlatformErrorCode::InvalidArgument,
            "activation-parent-requires-root",
        ));
    }
    let mut bytes = ContextBytes(limits.maximum_context_bytes);
    bytes.charge(size_of::<ActivationRequest>())?;
    for value in [
        request.activation_id.as_ref().map(|id| &id.0),
        request.root_activation_id.as_ref().map(|id| &id.0),
    ] {
        // Reserve the largest accepted generated/default-root spelling before
        // consulting the ID source or cloning a default root.
        bytes.string_length(value.map_or(limits.maximum_identifier_bytes, String::capacity))?;
        if let Some(value) = value {
            identifier(value, limits.maximum_identifier_bytes)?;
        }
    }
    for value in [
        request.parent_activation_id.as_ref().map(|id| &id.0),
        request.principal.tenant.as_ref().map(|id| &id.0),
        request.principal.service.as_ref().map(|id| &id.0),
        request.idempotency_key.as_ref().map(|id| &id.0),
        request.target.route.as_ref(),
    ]
    .into_iter()
    .flatten()
    {
        identifier(value, limits.maximum_identifier_bytes)?;
        bytes.string_length(value.capacity())?;
    }
    for value in [
        &request.principal.subject,
        &request.target.tenant.0,
        &request.target.service.0,
        &request.target.contract.0,
        &request.target.function.0,
        &request.trace.trace_id.0,
        &request.trace.span_id.0,
    ] {
        identifier(value, limits.maximum_identifier_bytes)?;
        bytes.string_length(value.capacity())?;
    }
    if request.input_media_type.is_empty()
        || request.input_media_type.len() > limits.maximum_identifier_bytes
        || request.input_media_type.chars().any(char::is_control)
    {
        return Err(error(
            PlatformErrorCode::InvalidArgument,
            "invalid-activation-media-type",
        ));
    }
    bytes.string_length(request.input_media_type.capacity())?;
    for metadata in [
        &request.metadata,
        &request.trace.baggage,
        &request.principal.claims,
    ] {
        bytes.metadata(metadata)?;
    }
    request
        .budget
        .validate_phase1_request()
        .map_err(|error| error.to_platform_error())
}

pub(super) fn identifier(value: &str, maximum: usize) -> Result<(), PlatformError> {
    if value.is_empty()
        || value.len() > maximum
        || value
            .chars()
            .any(|character| character.is_control() || character.is_whitespace())
    {
        return Err(error(
            PlatformErrorCode::InvalidArgument,
            "invalid-activation-identifier",
        ));
    }
    Ok(())
}

struct ContextBytes(usize);
impl ContextBytes {
    fn charge(&mut self, bytes: usize) -> Result<(), PlatformError> {
        self.0 = self.0.checked_sub(bytes).ok_or_else(exhausted)?;
        Ok(())
    }
    fn string_length(&mut self, bytes: usize) -> Result<(), PlatformError> {
        self.charge(size_of::<String>())?;
        self.charge(bytes)
    }
    fn metadata(&mut self, metadata: &Metadata) -> Result<(), PlatformError> {
        // Sparse B-tree allocations are charged before traversing keys.
        self.charge(metadata.len().checked_mul(4096).ok_or_else(exhausted)?)?;
        for (key, value) in metadata {
            self.string_length(key.capacity())?;
            self.string_length(value.capacity())?;
        }
        Ok(())
    }
}

fn exhausted() -> PlatformError {
    error(
        PlatformErrorCode::ResourceExhausted,
        "activation-request-too-large",
    )
}

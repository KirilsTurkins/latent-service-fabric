mod detail;
#[cfg(test)]
mod tests;

use latent_core::{ErrorDetail, PlatformError, PlatformErrorCode};
use prost::Message;
use tonic::Status;

use super::{proto, ManagementLimits};

const MAX_PUBLIC_DETAILS: usize = 16;
const MAX_ENCODED_ERROR_BYTES: usize = 8192;

pub(super) fn platform_status(error: PlatformError, limits: &ManagementLimits) -> Status {
    let code = crate::invocation::tonic_code(error.code);
    let message = public_message(error.code);
    let wire_code = error.code.wire_code();
    let base = std::mem::size_of::<proto::PlatformError>() + message.len() + wire_code.len();
    let wire = proto::PlatformError {
        code: wire_code.to_owned(),
        message: message.to_owned(),
        retryable: error.retryable,
        detail_items: public_details(error.details, limits, base),
    };
    if wire.encoded_len() <= limits.max_response_bytes.min(MAX_ENCODED_ERROR_BYTES) {
        Status::with_details(code, message, wire.encode_to_vec().into())
    } else {
        Status::new(code, message)
    }
}

fn public_details(
    source: Vec<ErrorDetail>,
    limits: &ManagementLimits,
    base: usize,
) -> Vec<proto::ErrorDetail> {
    if source.len()
        > limits
            .auth
            .max_platform_error_details
            .min(MAX_PUBLIC_DETAILS)
        || source.capacity() > limits.max_response_bytes / std::mem::size_of::<ErrorDetail>()
    {
        return Vec::new();
    }
    let Some(mut remaining) = source
        .len()
        .checked_mul(std::mem::size_of::<proto::ErrorDetail>())
        .and_then(|bytes| bytes.checked_add(base))
        .and_then(|bytes| limits.max_response_bytes.checked_sub(bytes))
    else {
        return Vec::new();
    };
    let mut output = Vec::with_capacity(source.len());
    for source_detail in source {
        let Some(detail) = detail::PublicDetail::parse(&source_detail, limits) else {
            continue;
        };
        let Some(next) = remaining.checked_sub(detail.retained_cost()) else {
            continue;
        };
        remaining = next;
        output.push(detail.into_proto());
    }
    output
}

fn public_message(code: PlatformErrorCode) -> &'static str {
    match code {
        PlatformErrorCode::Unavailable => "the management service is unavailable",
        PlatformErrorCode::DeadlineExceeded => "the management deadline was exceeded",
        PlatformErrorCode::Cancelled => "the management request was cancelled",
        PlatformErrorCode::ResourceExhausted => {
            "management data exceeds an available resource limit"
        }
        PlatformErrorCode::PermissionDenied => "the management operation is not permitted",
        PlatformErrorCode::Unauthenticated => "authentication is required",
        PlatformErrorCode::InvalidArgument => "the management request is invalid",
        PlatformErrorCode::NotFound => "the requested management resource was not found",
        PlatformErrorCode::AlreadyExists => "the management resource already exists",
        PlatformErrorCode::IncompatibleContract => "the management contract is incompatible",
        PlatformErrorCode::StateConflict => "the catalog generation precondition was not satisfied",
        PlatformErrorCode::DependencyFailed => "a management dependency failed",
        PlatformErrorCode::CorruptArtifact => "the selected artifact is corrupt",
        PlatformErrorCode::RouteUnavailable => "the requested route is unavailable",
        PlatformErrorCode::AdmissionRejected => {
            "the management request was rejected during validation"
        }
        _ => "the management request failed internally",
    }
}

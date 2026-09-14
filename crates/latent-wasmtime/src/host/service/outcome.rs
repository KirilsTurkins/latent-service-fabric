use super::wit;
use latent_activation::ActivationOutcome;
use latent_core::{PlatformError, PlatformErrorCode};

pub(super) fn convert(outcome: ActivationOutcome) -> wit::InvocationOutcome {
    match outcome {
        ActivationOutcome::Succeeded(value) => {
            wit::InvocationOutcome::Success(wit::InvocationResult {
                payload: value.output,
                media_type: value.output_media_type,
                metadata: value.metadata.into_iter().collect(),
            })
        }
        ActivationOutcome::DeclaredError { error, .. } => {
            wit::InvocationOutcome::DeclaredError(wit::DeclaredError {
                code: error.code,
                message: error.message,
                payload: error.payload,
                media_type: error.media_type,
                metadata: error.metadata.into_iter().collect(),
            })
        }
        ActivationOutcome::Failed { error, .. } => {
            wit::InvocationOutcome::PlatformFailure(platform(error))
        }
    }
}
pub(super) fn rejected(error: &PlatformError) -> wit::InvocationOutcome {
    // Dispatch failures do not echo policy/provider details or guest strings.
    wit::InvocationOutcome::PlatformFailure(wit::PlatformError {
        code: code(error.code),
        message: "local service invocation rejected".into(),
        retryable: false,
        details: vec![],
    })
}
fn platform(error: PlatformError) -> wit::PlatformError {
    wit::PlatformError {
        code: code(error.code),
        message: error.message,
        retryable: error.retryable,
        details: error
            .details
            .into_iter()
            .map(|detail| wit::ErrorDetail {
                kind: detail.kind,
                fields: detail.fields.into_iter().collect(),
            })
            .collect(),
    }
}
fn code(code: PlatformErrorCode) -> wit::PlatformErrorCode {
    match code {
        PlatformErrorCode::Unavailable => wit::PlatformErrorCode::Unavailable,
        PlatformErrorCode::DeadlineExceeded => wit::PlatformErrorCode::DeadlineExceeded,
        PlatformErrorCode::Cancelled => wit::PlatformErrorCode::Cancelled,
        PlatformErrorCode::ResourceExhausted => wit::PlatformErrorCode::ResourceExhausted,
        PlatformErrorCode::PermissionDenied => wit::PlatformErrorCode::PermissionDenied,
        PlatformErrorCode::Unauthenticated => wit::PlatformErrorCode::Unauthenticated,
        PlatformErrorCode::InvalidArgument => wit::PlatformErrorCode::InvalidArgument,
        PlatformErrorCode::NotFound => wit::PlatformErrorCode::NotFound,
        PlatformErrorCode::AlreadyExists => wit::PlatformErrorCode::AlreadyExists,
        PlatformErrorCode::IncompatibleContract => wit::PlatformErrorCode::IncompatibleContract,
        PlatformErrorCode::StateConflict => wit::PlatformErrorCode::StateConflict,
        PlatformErrorCode::DependencyFailed => wit::PlatformErrorCode::DependencyFailed,
        PlatformErrorCode::GuestTrap => wit::PlatformErrorCode::GuestTrap,
        PlatformErrorCode::CorruptArtifact => wit::PlatformErrorCode::CorruptArtifact,
        PlatformErrorCode::RouteUnavailable => wit::PlatformErrorCode::RouteUnavailable,
        PlatformErrorCode::AdmissionRejected => wit::PlatformErrorCode::AdmissionRejected,
        _ => wit::PlatformErrorCode::Internal,
    }
}

use latent_core::{PlatformError, PlatformErrorCode};
use tonic::{Code, Status};

fn tonic_code(code: PlatformErrorCode) -> Code {
    match code {
        PlatformErrorCode::Unavailable | PlatformErrorCode::RouteUnavailable => Code::Unavailable,
        PlatformErrorCode::DeadlineExceeded => Code::DeadlineExceeded,
        PlatformErrorCode::Cancelled => Code::Cancelled,
        PlatformErrorCode::ResourceExhausted | PlatformErrorCode::AdmissionRejected => {
            Code::ResourceExhausted
        }
        PlatformErrorCode::PermissionDenied => Code::PermissionDenied,
        PlatformErrorCode::Unauthenticated => Code::Unauthenticated,
        PlatformErrorCode::InvalidArgument => Code::InvalidArgument,
        PlatformErrorCode::NotFound => Code::NotFound,
        PlatformErrorCode::AlreadyExists => Code::AlreadyExists,
        PlatformErrorCode::IncompatibleContract | PlatformErrorCode::DependencyFailed => {
            Code::FailedPrecondition
        }
        PlatformErrorCode::StateConflict => Code::Aborted,
        PlatformErrorCode::CorruptArtifact => Code::DataLoss,
        _ => Code::Internal,
    }
}

pub(super) fn public_platform_message(code: PlatformErrorCode) -> &'static str {
    match code {
        PlatformErrorCode::Unavailable => "the invocation service is unavailable",
        PlatformErrorCode::DeadlineExceeded => "the invocation deadline was exceeded",
        PlatformErrorCode::Cancelled => "the invocation was cancelled",
        PlatformErrorCode::ResourceExhausted => {
            "the invocation exceeded an available resource limit"
        }
        PlatformErrorCode::PermissionDenied => "the invocation is not permitted",
        PlatformErrorCode::Unauthenticated => "authentication is required",
        PlatformErrorCode::InvalidArgument => "the invocation request is invalid",
        PlatformErrorCode::NotFound => "the requested activation was not found",
        PlatformErrorCode::AlreadyExists => "the requested activation already exists",
        PlatformErrorCode::IncompatibleContract => {
            "the requested contract is not compatible with the selected revision"
        }
        PlatformErrorCode::StateConflict => "the invocation encountered a state conflict",
        PlatformErrorCode::DependencyFailed => "an invocation dependency failed",
        PlatformErrorCode::GuestTrap => "the guest failed during execution",
        PlatformErrorCode::CorruptArtifact => "the selected artifact is corrupt",
        PlatformErrorCode::RouteUnavailable => "no invocation route is currently available",
        PlatformErrorCode::AdmissionRejected => "the invocation was rejected during admission",
        _ => "the invocation failed internally",
    }
}

pub(super) fn boundary_error(code: PlatformErrorCode, message: &str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
// Consume the private diagnostics at the public boundary; callers use this as map_err.
#[allow(clippy::needless_pass_by_value)]
pub(super) fn platform_status(error: PlatformError) -> Status {
    Status::new(tonic_code(error.code), public_platform_message(error.code))
}

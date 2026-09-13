//! Fixed diagnostics; remote error text and local paths never become diagnostics.
mod details;
#[cfg(test)]
mod tests;

use latent_core::{PlatformError, PlatformErrorCode};
use latent_rpc::{control::v1 as proto, platform_error::TryIntoDomainPlatformError};
use prost::Message;
use serde_json::{json, Value};
use tonic::{Code, Status};

use crate::output::Category;

#[derive(Debug)]
pub struct Failure {
    pub category: Category,
    pub error: Value,
    pub data: Value,
    pub request_dispatched: bool,
    pub outcome_known: bool,
}
impl Failure {
    pub fn local(code: &'static str, message: &'static str) -> Self {
        Self::new(Category::LocalError, code, message)
    }
    pub fn protocol(code: &'static str, message: &'static str) -> Self {
        let mut failure = Self::new(Category::TransportError, code, message);
        failure.outcome_known = false;
        failure
    }
    pub fn transport(code: &'static str, message: &'static str) -> Self {
        Self::new(Category::TransportError, code, message)
    }
    pub fn interrupted(dispatched: bool) -> Self {
        let mut failure = Self::new(
            Category::Interrupted,
            "interrupted",
            "The client was interrupted.",
        );
        failure.request_dispatched = dispatched;
        failure.outcome_known = !dispatched;
        failure
    }
    fn new(category: Category, code: &'static str, message: &'static str) -> Self {
        Self {
            category,
            error: json!({"code": code, "message": message}),
            data: json!({}),
            request_dispatched: false,
            outcome_known: true,
        }
    }
    pub fn from_status(status: &Status) -> Self {
        let mut failure = Self::from_status_inner(status);
        match crate::management::phase2::audit_metadata(status.metadata()) {
            Ok(Some(ack)) => failure.data["auditAck"] = ack,
            Ok(None) => {}
            Err(error) => return error,
        }
        failure
    }
    fn from_status_inner(status: &Status) -> Self {
        let code = status.code();
        if !status.details().is_empty() {
            let decoded = decode_platform(status.details());
            let Ok(error) = decoded else {
                return Self::protocol(
                    "invalid-error-response",
                    "The node returned invalid error details.",
                );
            };
            // The typed code and gRPC status must describe the same failure.
            if tonic_code(error.code) != code {
                return Self::protocol(
                    "invalid-error-response",
                    "The node returned inconsistent error details.",
                );
            }
            let value = platform_value(&error);
            let committed = value["details"].as_array().is_some_and(|items| {
                items.iter().any(|item| {
                    item["kind"] == "deployment-mutation" && item["fields"]["committed"] == "true"
                })
            });
            return Self {
                category: if error.code == PlatformErrorCode::NotFound {
                    Category::NotFound
                } else {
                    Category::PlatformError
                },
                error: value,
                data: json!({}),
                request_dispatched: true,
                outcome_known: committed || !ambiguous(code),
            };
        }
        if code == Code::Unimplemented {
            let mut failure = Self::new(
                Category::PlatformError,
                "unimplemented",
                "The node does not implement this operation.",
            );
            failure.request_dispatched = true;
            return failure;
        }
        let platform = match code {
            Code::InvalidArgument => Some(PlatformErrorCode::InvalidArgument),
            Code::PermissionDenied => Some(PlatformErrorCode::PermissionDenied),
            Code::Unauthenticated => Some(PlatformErrorCode::Unauthenticated),
            Code::AlreadyExists => Some(PlatformErrorCode::AlreadyExists),
            Code::NotFound => Some(PlatformErrorCode::NotFound),
            Code::FailedPrecondition | Code::Aborted => Some(PlatformErrorCode::StateConflict),
            _ => None,
        };
        if let Some(code) = platform {
            return Self {
                category: if code == PlatformErrorCode::NotFound {
                    Category::NotFound
                } else {
                    Category::PlatformError
                },
                error: platform_value(&PlatformError {
                    code,
                    message: String::new(),
                    retryable: false,
                    details: Vec::new(),
                }),
                data: json!({}),
                request_dispatched: true,
                outcome_known: true,
            };
        }
        let mut failure = Self::protocol("rpc-failed", "The RPC did not return a usable result.");
        failure.error["grpcCode"] = json!(grpc_name(code));
        failure
    }
}

pub fn platform_value(error: &PlatformError) -> Value {
    json!({"code": error.code.wire_code(), "message": "The platform reported a failure.",
        "retryable": error.retryable, "details": details::sanitize(&error.details)})
}

fn decode_platform(bytes: &[u8]) -> Result<PlatformError, ()> {
    if bytes.len() > 8192 {
        return Err(());
    }
    let value = proto::PlatformError::decode(bytes).map_err(|_| ())?;
    if value.code.len() > 64
        || value.message.len() > 4096
        || value.detail_items.len() > 16
        || value.detail_items.iter().any(|d| {
            d.kind.len() > 128
                || d.fields.len() > 32
                || d.fields
                    .iter()
                    .any(|(k, v)| k.len() > 128 || v.len() > 1024)
        })
    {
        return Err(());
    }
    value.try_into_domain().map_err(|_| ())
}
fn ambiguous(code: Code) -> bool {
    matches!(
        code,
        Code::Unavailable
            | Code::DeadlineExceeded
            | Code::Cancelled
            | Code::Internal
            | Code::Unknown
    )
}
fn grpc_name(code: Code) -> &'static str {
    match code {
        Code::Cancelled => "cancelled",
        Code::Unknown => "unknown",
        Code::DeadlineExceeded => "deadline-exceeded",
        Code::Unimplemented => "unimplemented",
        Code::Internal => "internal",
        Code::Unavailable => "unavailable",
        Code::DataLoss => "data-loss",
        Code::OutOfRange => "out-of-range",
        Code::ResourceExhausted => "resource-exhausted",
        Code::Ok => "ok",
        Code::InvalidArgument => "invalid-argument",
        Code::NotFound => "not-found",
        Code::AlreadyExists => "already-exists",
        Code::PermissionDenied => "permission-denied",
        Code::Unauthenticated => "unauthenticated",
        Code::FailedPrecondition => "failed-precondition",
        Code::Aborted => "aborted",
    }
}

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

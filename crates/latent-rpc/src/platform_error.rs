//! Canonical conversions between domain platform errors and generated Protobuf types.

use std::fmt;

use latent_core::{
    ErrorDetail as DomainErrorDetail, PlatformError as DomainPlatformError, PlatformErrorCode,
};

use crate::{control::v1 as control, invocation::v1 as invocation};

/// Error returned when a generated message carries a platform code unknown to this build.
///
/// Unknown codes are rejected rather than mapped to `internal`, because coercion would
/// discard the sender's classification and could change retry or terminal-state behavior.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UnknownPlatformErrorCode {
    code: String,
}

impl UnknownPlatformErrorCode {
    fn new(code: String) -> Self {
        Self { code }
    }

    /// Returns the unrecognized wire value exactly as received.
    #[must_use]
    pub fn code(&self) -> &str {
        &self.code
    }

    /// Consumes the error and returns the unrecognized wire value.
    #[must_use]
    pub fn into_code(self) -> String {
        self.code
    }
}

impl fmt::Display for UnknownPlatformErrorCode {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "unknown platform error code: {}", self.code)
    }
}

impl std::error::Error for UnknownPlatformErrorCode {}

/// Converts one generated Protobuf platform error into the canonical domain shape.
pub trait TryIntoDomainPlatformError {
    /// Reconstructs the domain error or rejects an unknown stable code.
    fn try_into_domain(self) -> Result<DomainPlatformError, UnknownPlatformErrorCode>;
}

impl From<DomainPlatformError> for invocation::PlatformError {
    fn from(error: DomainPlatformError) -> Self {
        Self {
            code: error.code.wire_code().to_owned(),
            message: error.message,
            retryable: error.retryable,
            detail_items: error
                .details
                .into_iter()
                .map(|detail| invocation::ErrorDetail {
                    kind: detail.kind,
                    fields: detail.fields.into_iter().collect(),
                })
                .collect(),
        }
    }
}

impl From<&DomainPlatformError> for invocation::PlatformError {
    fn from(error: &DomainPlatformError) -> Self {
        Self::from(error.clone())
    }
}

impl TryIntoDomainPlatformError for invocation::PlatformError {
    fn try_into_domain(self) -> Result<DomainPlatformError, UnknownPlatformErrorCode> {
        domain_error(
            self.code,
            self.message,
            self.retryable,
            self.detail_items.into_iter().map(|detail| DomainErrorDetail {
                kind: detail.kind,
                fields: detail.fields.into_iter().collect(),
            }),
        )
    }
}

impl From<DomainPlatformError> for control::PlatformError {
    fn from(error: DomainPlatformError) -> Self {
        Self {
            code: error.code.wire_code().to_owned(),
            message: error.message,
            retryable: error.retryable,
            detail_items: error
                .details
                .into_iter()
                .map(|detail| control::ErrorDetail {
                    kind: detail.kind,
                    fields: detail.fields.into_iter().collect(),
                })
                .collect(),
        }
    }
}

impl From<&DomainPlatformError> for control::PlatformError {
    fn from(error: &DomainPlatformError) -> Self {
        Self::from(error.clone())
    }
}

impl TryIntoDomainPlatformError for control::PlatformError {
    fn try_into_domain(self) -> Result<DomainPlatformError, UnknownPlatformErrorCode> {
        domain_error(
            self.code,
            self.message,
            self.retryable,
            self.detail_items.into_iter().map(|detail| DomainErrorDetail {
                kind: detail.kind,
                fields: detail.fields.into_iter().collect(),
            }),
        )
    }
}

fn domain_error(
    wire_code: String,
    message: String,
    retryable: bool,
    details: impl IntoIterator<Item = DomainErrorDetail>,
) -> Result<DomainPlatformError, UnknownPlatformErrorCode> {
    let code = PlatformErrorCode::from_wire_code(&wire_code)
        .ok_or_else(|| UnknownPlatformErrorCode::new(wire_code))?;
    Ok(DomainPlatformError {
        code,
        message,
        retryable,
        details: details.into_iter().collect(),
    })
}

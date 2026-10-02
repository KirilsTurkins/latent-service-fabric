//! Trusted helpers preserve domain fields and may allocate copies. They are not
//! ingress resource limits. The service validates borrowed values first and
//! uses the private owned conversions, which move payloads and redact only
//! platform diagnostics.

use std::fmt;

use latent_activation::{
    ActivationOutcome, ActivationStatus, ActivationSuccess, ActivationSuccessSummary,
    RetainedActivationOutcome,
};
use latent_core::{
    ActivationPhase, ActivationTerminalState, BudgetConsumption, CancelDisposition, DeclaredError,
    ErrorDetail, PlatformError, PlatformErrorCode, ResourceBudget,
};
use latent_rpc::platform_error::TryIntoDomainPlatformError;

use super::{
    proto, public_platform_message, InvocationLimits, InvocationReceipt, InvocationRequest,
    InvocationResponse, InvocationRevision,
};

mod public_error;
mod shape;
use public_error::public_platform_error;

/// The same closed producer diagnostics used by invocation terminal responses.
pub(crate) fn sanitize_platform_error(
    value: proto::PlatformError,
    limits: &InvocationLimits,
) -> Result<proto::PlatformError, ()> {
    let error = value.try_into_domain().map_err(|_| ())?;
    Ok(public_platform_error(error, limits).into())
}
pub(super) use shape::{validate_response_shape, validate_status_shape};

#[cfg(test)]
mod tests;

include!("conversion_parts/conversion_01.rs");
include!("conversion_parts/conversion_02.rs");
include!("conversion_parts/conversion_03.rs");
include!("conversion_parts/conversion_04.rs");

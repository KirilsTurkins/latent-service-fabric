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
    InvocationResponse,
};

include!("conversion_parts/conversion_01.rs");
include!("conversion_parts/conversion_02.rs");
include!("conversion_parts/conversion_03.rs");
include!("conversion_parts/conversion_04.rs");

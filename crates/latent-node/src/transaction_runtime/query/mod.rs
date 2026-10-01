//! Fresh queries use the normal activation and protected native view owners.
//! The installed binding supplies scope and formats; it is never a grant.
mod admission;
mod completion;
mod selection;

pub use admission::{QueryAdmission, QueryOwners};
pub use selection::{QueryScope, QuerySelection};

use latent_core::{PlatformError, PlatformErrorCode};
use latent_executor::transaction::StateFailure;

fn failure(error: StateFailure) -> PlatformError {
    let code = match error {
        StateFailure::Conflict => PlatformErrorCode::StateConflict,
        StateFailure::PermissionDenied => PlatformErrorCode::PermissionDenied,
        StateFailure::ReadBudgetExhausted | StateFailure::WriteBudgetExhausted => {
            PlatformErrorCode::ResourceExhausted
        }
        StateFailure::Cancelled => PlatformErrorCode::Cancelled,
        _ => PlatformErrorCode::Unavailable,
    };
    PlatformError {
        code,
        message: "fresh-query-unavailable".into(),
        retryable: false,
        details: Vec::new(),
    }
}

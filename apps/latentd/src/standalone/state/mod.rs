//! One canonical state startup owner, created before catalog/policy exposure.
//! Installation constraints never create a namespace or deferred-effect grant.

mod bootstrap;
mod clock;
mod configuration;
mod kernel;
mod preparation;
mod runtime;
mod store;
mod validation;

pub(super) use bootstrap::StateBootstrap;
use clock::AdapterClock;
use kernel::{StateKernel, StateShutdownReport};
pub(super) use runtime::StandaloneStateRuntime;
pub use runtime::StateRetirementReport;

fn unavailable() -> latent_core::PlatformError {
    super::error(
        latent_core::PlatformErrorCode::Unavailable,
        "transaction startup owner is unavailable",
    )
}

//! One canonical state startup owner, created before catalog/policy exposure.
//! Installation constraints never create a namespace or deferred-effect grant.

mod bootstrap;
mod clock;
mod configuration;
pub(in crate::standalone) mod inspection;
mod installations;
pub use inspection::ConfiguredHttpEffectInspection;
pub use inspection::{
    NativeDeferredEffectHostInspection, NativeHttpCallerInspection, NativeTransactionHostInspection,
};
#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
pub(in crate::standalone) use installations::SignedFixture;
mod kernel;
mod maintenance;
mod preparation;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod recovery;
mod runtime;
mod stateless;
mod store;
mod validation;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub(in crate::standalone) use recovery::{recover, RecoveryOwners};
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub use recovery::{NativeRecoveryReport, NativeRecoveryRequest};

pub(super) use bootstrap::StateBootstrap;
use clock::AdapterClock;
pub(super) use installations::{InstalledHttpEffects, InstalledStateServices};
use kernel::{StateKernel, StateShutdownReport};
pub(super) use runtime::StandaloneStateRuntime;
pub use runtime::StateRetirementReport;
pub(in crate::standalone) use stateless::require_stateless_mode;

fn unavailable() -> latent_core::PlatformError {
    super::error(
        latent_core::PlatformErrorCode::Unavailable,
        "transaction startup owner is unavailable",
    )
}

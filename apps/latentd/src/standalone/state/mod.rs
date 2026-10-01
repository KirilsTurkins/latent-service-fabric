//! One installed state composition over the existing protected node owners.
mod authorization;
mod clock;
mod command;
mod effect_requirements;
mod effects;
mod inspection;
mod lifecycle;
mod request;
mod result;
mod role;
mod runtime;
mod selection;
mod validation;
pub use inspection::{NativeDeferredEffectHostInspection, NativeTransactionHostInspection};
pub use lifecycle::StateShutdownReport;
pub use request::StateRequest;
pub use runtime::StateRuntime;

pub(in crate::standalone) use inspection::inspect_host_configuration;
pub(crate) use selection::load_operations;
pub use selection::InstalledTransactionOperation;
pub(crate) use validation::validate_view;

fn denied() -> latent_core::PlatformError {
    super::error(
        latent_core::PlatformErrorCode::PermissionDenied,
        "installed-transaction-target-unavailable",
    )
}
fn unavailable() -> latent_core::PlatformError {
    super::error(
        latent_core::PlatformErrorCode::Unavailable,
        "transaction-runtime-recovery-required",
    )
}
fn capacity() -> latent_core::PlatformError {
    super::error(
        latent_core::PlatformErrorCode::ResourceExhausted,
        "transaction-native-capacity-unavailable",
    )
}

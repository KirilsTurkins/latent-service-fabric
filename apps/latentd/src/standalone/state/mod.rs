//! One installed state composition over the existing protected node owners.
mod authorization;
mod clock;
mod command;
mod effect_requirements;
mod effects;
mod inspection;
mod lifecycle;
mod recovery;
mod request;
mod result;
mod role;
mod runtime;
mod selection;
mod validation;
pub use inspection::{
    NativeDeferredEffectHostInspection, NativeHttpCallerInspection, NativeTransactionHostInspection,
};
pub use lifecycle::StateShutdownReport;
pub(in crate::standalone) use recovery::failure::Failure as StartupFailure;
pub use recovery::TransactionStoreDiagnosis;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub(in crate::standalone) use recovery::{recover_namespace, RecoveryOwners};
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub use recovery::{NativeRecoveryReport, NativeRecoveryRequest};
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

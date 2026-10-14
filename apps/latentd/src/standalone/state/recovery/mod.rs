//! Authenticated native offline actions on the current protected owners.
mod assets;
mod authority;
mod catalog;
mod codecs;
mod execution;
mod migration;
mod operation;
mod original_resume;
mod profile;
mod request;
mod restore;
mod restored;
mod scope;
mod selection;

pub use execution::NativeRecoveryReport;
pub(in crate::standalone) use operation::{recover, RecoveryOwners};
pub use request::NativeRecoveryRequest;

fn denied() -> latent_core::PlatformError {
    crate::standalone::error(
        latent_core::PlatformErrorCode::PermissionDenied,
        "native-recovery-refused",
    )
}
fn capacity() -> latent_core::PlatformError {
    crate::standalone::error(
        latent_core::PlatformErrorCode::ResourceExhausted,
        "native-recovery-capacity",
    )
}

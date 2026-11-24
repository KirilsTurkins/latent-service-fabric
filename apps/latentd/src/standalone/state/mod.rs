//! One canonical state startup owner, created before catalog/policy exposure.
//! Installation constraints never create a namespace or deferred-effect grant.

mod bootstrap;
mod clock;
mod configuration;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod inbox;
pub(in crate::standalone) mod inspection;
mod installations;
pub use inspection::{ConfiguredEventEffectInspection, ConfiguredHttpEffectInspection};
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

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub(crate) fn check_retained(
    settings: &crate::config::NodeSettings,
) -> Result<(), latent_core::PlatformError> {
    use latent_core::{ActivationClock, SystemActivationClock};
    use latent_state::{embedded::StoreError, store_identity::StoreIdentity};
    use std::sync::Arc;

    let state = settings.state.as_ref().ok_or_else(unavailable)?;
    if state.create_if_missing
        && latent_protected_files::ProtectedRoot::open(&state.store.root)?
            .check_empty()
            .is_ok()
    {
        return Ok(());
    }
    let clock: Arc<dyn ActivationClock> = Arc::new(SystemActivationClock);
    let mut bootstrap = StateBootstrap::new_state(state, &clock)?;
    let original = bootstrap.original();
    let quotas = validation::quotas(state);
    state
        .store
        .check_retained(
            bootstrap.take_memory()?,
            crate::config::state::STARTUP_VALIDATOR_BYTES,
            |view| {
                if StoreIdentity::inspect(view)?.as_ref() != Some(&state.store_identity) {
                    return Err(StoreError::UnsupportedFormat);
                }
                validation::validate(view, &state.store_identity, &quotas, &original)
            },
        )
        .map_err(|_| unavailable())
}

fn unavailable() -> latent_core::PlatformError {
    super::error(
        latent_core::PlatformErrorCode::Unavailable,
        "transaction startup owner is unavailable",
    )
}

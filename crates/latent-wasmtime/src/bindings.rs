//! Shared generated host bindings and the legacy signature validator.

pub use latent_component_bindings::host::echo::ServicePre;
pub use latent_component_bindings::host::runtime::latent;

use wasmtime::component::{HasSelf, Linker};

use crate::host::HostState;

/// Install only Phase 1 authority, even though the generated runtime world also
/// describes interfaces reserved for later phases.
pub(crate) fn install_context_log_clock(linker: &mut Linker<HostState>) -> wasmtime::Result<()> {
    latent::context::context::add_to_linker::<HostState, HasSelf<HostState>>(linker, |state| {
        state
    })?;
    latent::log::log::add_to_linker::<HostState, HasSelf<HostState>>(linker, |state| state)?;
    latent::clock::monotonic::add_to_linker::<HostState, HasSelf<HostState>>(linker, |state| {
        state
    })?;
    latent::clock::wall::add_to_linker::<HostState, HasSelf<HostState>>(linker, |state| state)
}

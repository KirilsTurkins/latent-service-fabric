//! Shared generated host bindings and the legacy signature validator.

pub use latent_component_bindings::host::echo::ServicePre;
pub use latent_component_bindings::host::runtime::latent;

use latent_core::{HostInterfaceBinding, PHASE3_HOST_ABI_V1};
use wasmtime::component::{HasSelf, Linker};

use crate::host::HostState;

// This is the explicit registration manifest for the linker calls below. It is
// intentionally not described as generated-binding introspection: the
// `wasmtime::component::bindgen!` output does not expose a stable interface-name
// manifest for this adapter to compare directly.
const DECLARED_BUILTIN_LINKER_INTERFACES: [&str; 4] = [
    "latent:context/context@0.1.0",
    "latent:log/log@0.1.0",
    "latent:clock/monotonic@0.1.0",
    "latent:clock/wall@0.1.0",
];

fn declared_linker_profile_is_exact() -> bool {
    PHASE3_HOST_ABI_V1.interfaces().len() == DECLARED_BUILTIN_LINKER_INTERFACES.len()
        && DECLARED_BUILTIN_LINKER_INTERFACES.iter().all(|interface| {
            PHASE3_HOST_ABI_V1
                .interface(interface)
                .is_some_and(|spec| spec.binding == HostInterfaceBinding::BuiltIn)
        })
}

/// Install only the exact interfaces declared for this built-in linker adapter.
/// Provider interfaces are added only after their bounded provider owners are
/// available.
pub(crate) fn install_context_log_clock(linker: &mut Linker<HostState>) -> wasmtime::Result<()> {
    if !declared_linker_profile_is_exact() {
        return Err(wasmtime::Error::msg(
            "declared linker registrations do not match the active host ABI profile",
        ));
    }
    latent::context::context::add_to_linker::<HostState, HasSelf<HostState>>(linker, |state| {
        state
    })?;
    latent::log::log::add_to_linker::<HostState, HasSelf<HostState>>(linker, |state| state)?;
    latent::clock::monotonic::add_to_linker::<HostState, HasSelf<HostState>>(linker, |state| {
        state
    })?;
    latent::clock::wall::add_to_linker::<HostState, HasSelf<HostState>>(linker, |state| state)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn declared_linker_registrations_match_active_profile_exactly() {
        assert!(declared_linker_profile_is_exact());
    }
}

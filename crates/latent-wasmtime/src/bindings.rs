//! Shared generated host bindings and the legacy signature validator.

pub use latent_component_bindings::host::echo::ServicePre;
pub use latent_component_bindings::host::runtime::latent;

use latent_core::{HostInterfaceBinding, PHASE3_HOST_ABI_V1};
use wasmtime::component::{HasSelf, Linker};

use crate::host::HostState;

const INSTALLED_HOST_INTERFACES: [&str; 4] = [
    "latent:context/context@0.1.0",
    "latent:log/log@0.1.0",
    "latent:clock/monotonic@0.1.0",
    "latent:clock/wall@0.1.0",
];

fn installed_profile_is_exact() -> bool {
    PHASE3_HOST_ABI_V1.interfaces().len() == INSTALLED_HOST_INTERFACES.len()
        && INSTALLED_HOST_INTERFACES.iter().all(|interface| {
            PHASE3_HOST_ABI_V1.interface(interface).is_some_and(|spec| {
                spec.binding == HostInterfaceBinding::BuiltIn
            })
        })
}

/// Install only the exact interfaces in the active host ABI profile. Provider
/// interfaces are added only after their bounded provider owners are available.
pub(crate) fn install_context_log_clock(linker: &mut Linker<HostState>) -> wasmtime::Result<()> {
    if !installed_profile_is_exact() {
        return Err(wasmtime::Error::msg(
            "compiled host bindings do not match the active host ABI profile",
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
    fn installed_bindings_match_active_profile_exactly() {
        assert!(installed_profile_is_exact());
    }
}

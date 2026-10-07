//! Scoped Phase 4 resources. Guest resource numbers only address this Store's
//! finite table; its already admitted host owns scope, authority and native IO.

mod convert;
mod state;
mod table;
pub(crate) use table::Access;

use super::HostState;
use latent_component_bindings::host::transaction::latent::{intents::staging, state::key_value};
use latent_executor::transaction as port;
use wasmtime::component::{HasSelf, Linker};

pub(crate) fn install(linker: &mut Linker<HostState>) -> wasmtime::Result<()> {
    key_value::add_to_linker::<HostState, HasSelf<HostState>>(linker, |state| state)?;
    staging::add_to_linker::<HostState, HasSelf<HostState>>(linker, |state| state)
}

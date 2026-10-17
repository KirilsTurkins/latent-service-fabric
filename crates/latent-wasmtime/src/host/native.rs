//! Conservative accepted child capacity; released only after actual Store drop.
use super::{runtime, HostState};
use latent_capabilities::broker::{AuditProviderOutcome, ProviderCall};
use latent_component_bindings::host::activation::latent::runtime::activation as wit;
use latent_core::PlatformError;
use latent_policy::capability::ResourceTarget;
use std::time::Instant;
use wasmtime::component::Linker;

pub(crate) const CAPABILITY: &str = "latent:runtime-native/threads@0.1.0";
pub(crate) const PROFILE: &str = "conservative-native-total-starts-v1";

fn authorize(state: &HostState) -> Result<ProviderCall, PlatformError> {
    runtime::authorize_for(state, CAPABILITY, "start", ResourceTarget::Context)
}

pub(crate) fn install(linker: &mut Linker<HostState>) -> wasmtime::Result<()> {
    linker.instance(CAPABILITY)?.func_wrap_async(
        "start",
        |mut store, (value,): (wit::Token,)| {
            Box::new(async move {
                let started = Instant::now();
                super::service::checkpoint(&mut store)?;
                let mut call = match authorize(store.data()) {
                    Ok(call) => call,
                    Err(error) => {
                        super::service::synchronize(&mut store)?;
                        store.data_mut().record_host_call(started);
                        return Ok((runtime::Completion::new(Err(runtime::convert(error)), None),));
                    }
                };
                let result = runtime::native_context(store.data_mut())
                    .and_then(|context| context.reserve_child(runtime::token(value)));
                let _ = call.record_provider_outcome(AuditProviderOutcome::HostCompleted);
                super::service::synchronize(&mut store)?;
                store.data_mut().record_host_call(started);
                Ok((runtime::Completion::new(
                    result.map_err(runtime::convert),
                    Some(call),
                ),))
            })
        },
    )?;
    Ok(())
}

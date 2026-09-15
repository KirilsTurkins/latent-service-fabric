//! Exact random WIT imports; all entropy comes from the installed broker owner.
use super::{service::synchronize, HostState};
use latent_capabilities::broker::random::{RandomError, RandomProvider, RANDOM_CAPABILITY};
use latent_component_bindings::host::phase3::latent::random::random as wit;
use std::{sync::Arc, time::Instant};
use wasmtime::component::Linker;

pub(crate) fn install(
    linker: &mut Linker<HostState>,
    provider: Arc<RandomProvider>,
) -> wasmtime::Result<()> {
    let bytes_provider = provider.clone();
    let mut instance = linker.instance(RANDOM_CAPABILITY)?;
    instance.func_wrap_async("bytes", move |mut store, (length,): (u32,)| {
        let provider = bytes_provider.clone();
        Box::new(async move {
            let started = Instant::now();
            checkpoint(&mut store)?;
            let pending = store
                .data()
                .capabilities
                .session
                .as_ref()
                .ok_or(RandomError::Unavailable)
                .and_then(|session| provider.bytes(session, length));
            synchronize(&mut store)?;
            let result = match pending {
                Ok(pending) => pending.await,
                Err(error) => Err(error),
            };
            checkpoint(&mut store)?;
            let result = result
                .map(|mut completion| {
                    // Keep the charge through canonical lowering and Store destruction.
                    let bytes = std::mem::take(&mut *completion.bytes);
                    store
                        .data_mut()
                        .capabilities
                        .retain_lowering(completion.owner);
                    bytes
                })
                .map_err(convert);
            synchronize(&mut store)?;
            store.data_mut().record_host_call(started);
            Ok((result,))
        })
    })?;
    instance.func_wrap_async("u64-value", move |mut store, (): ()| {
        let provider = provider.clone();
        Box::new(async move {
            let started = Instant::now();
            checkpoint(&mut store)?;
            let pending = store
                .data()
                .capabilities
                .session
                .as_ref()
                .ok_or(RandomError::Unavailable)
                .and_then(|session| provider.u64_value(session));
            synchronize(&mut store)?;
            let result = match pending {
                Ok(pending) => pending.await,
                Err(error) => Err(error),
            };
            checkpoint(&mut store)?;
            let result = result
                .map(|completion| {
                    let value = u64::from_le_bytes(
                        completion
                            .bytes
                            .as_slice()
                            .try_into()
                            .expect("fixed u64 output"),
                    );
                    store
                        .data_mut()
                        .capabilities
                        .retain_lowering(completion.owner);
                    value
                })
                .map_err(convert);
            synchronize(&mut store)?;
            store.data_mut().record_host_call(started);
            Ok((result,))
        })
    })?;
    Ok(())
}
fn convert(error: RandomError) -> wit::RandomError {
    match error {
        RandomError::InvalidLength => wit::RandomError::InvalidLength,
        RandomError::BudgetExhausted => wit::RandomError::BudgetExhausted,
        RandomError::Unavailable => wit::RandomError::Unavailable,
    }
}

fn checkpoint(store: &mut wasmtime::StoreContextMut<'_, HostState>) -> wasmtime::Result<()> {
    super::service::checkpoint(store)?;
    if let Some(session) = &store.data().capabilities.session {
        session
            .check_liveness()
            .map_err(super::capabilities::host_error)?;
    }
    Ok(())
}

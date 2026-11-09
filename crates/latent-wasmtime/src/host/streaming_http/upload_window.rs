//! Prepaid input over one already-authorized streaming upload.
use super::{checkpoint, convert_error, trap, wit, Error, HostState, HttpError, Kind, Value};
use crate::host::service::synchronize_without_host_clock;
use latent_capabilities::broker::streaming_http::{
    HttpWritePreparationError, UPLOAD_WINDOW_INTERFACE,
};
use latent_component_bindings::host::http_upload_window::latent::http0_5_0::upload_window as window;
use std::sync::Arc;
use wasmtime::{
    component::{Accessor, InlineConcurrentHost, Linker, Resource, ResourceType, WasmList},
    AsContextMut,
};

// The C profile already handles finite 4-KiB pieces. A smaller provider
// limit narrows this further; neither this interface nor its ticket grants a
// larger transfer, a retry, or another operation.
const MAXIMUM_WINDOW: usize = 4096;

fn stopped(stop: &Option<Arc<crate::containment::StopControl>>) -> Option<Error> {
    let Some(stop) = stop else {
        return Some(Error::InvalidState);
    };
    stop.observe().map(|kind| {
        Error::Http(match kind {
            latent_executor::GuestInterruptionKind::Cancelled => HttpError::Cancelled,
            latent_executor::GuestInterruptionKind::DeadlineExceeded => HttpError::DeadlineExceeded,
            latent_executor::GuestInterruptionKind::FuelExhausted
            | latent_executor::GuestInterruptionKind::MemoryExhausted => HttpError::BudgetExhausted,
        })
    })
}

pub(crate) fn install(linker: &mut Linker<HostState>) -> wasmtime::Result<()> {
    let mut host = linker.instance(UPLOAD_WINDOW_INTERFACE)?;
    host.resource(
        "upload",
        ResourceType::host::<wit::Upload>(),
        |mut store, rep| {
            store
                .data_mut()
                .capabilities
                .streams
                .remove(rep, Kind::Upload)
                .map_err(trap)
        },
    )?;
    host.func_wrap_concurrent_inline("prepare", Prepare)?;
    host.func_wrap_concurrent_inline("write", Write)?;
    Ok(())
}

fn preparation_error(error: HttpWritePreparationError) -> window::PreparationError {
    match error {
        HttpWritePreparationError::Unsupported => window::PreparationError::UnsupportedProvider,
        HttpWritePreparationError::Http(error) => {
            window::PreparationError::Http(convert_error(error))
        }
    }
}

pub(super) fn restore(
    access: &Accessor<HostState>,
    rep: u32,
    value: &mut Option<Value>,
) -> wasmtime::Result<Result<(), Error>> {
    access.with(|mut access| {
        let mut store = access.as_context_mut();
        checkpoint(&mut store)?;
        synchronize_without_host_clock(&mut store)?;
        Ok(store
            .data_mut()
            .capabilities
            .streams
            .restore_upload(rep, value))
    })
}

struct Prepare;
impl
    InlineConcurrentHost<
        HostState,
        (Resource<wit::Upload>, u32),
        (Result<window::Window, window::PreparationError>,),
    > for Prepare
{
    fn invoke<'a>(
        &'a self,
        access: &'a Accessor<HostState>,
        (target, maximum): (Resource<wit::Upload>, u32),
    ) -> impl std::future::Future<
        Output = wasmtime::Result<(Result<window::Window, window::PreparationError>,)>,
    > + Send
           + 'a {
        async move {
            let rep = target.rep();
            let mut detached = None;
            let mut stop = None;
            let taken = access.with(|mut access| {
                let mut store = access.as_context_mut();
                checkpoint(&mut store)?;
                synchronize_without_host_clock(&mut store)?;
                stop = store.data().runtime_stop.clone();
                let result = store
                    .data_mut()
                    .capabilities
                    .streams
                    .take(rep, Kind::Upload, false);
                Ok::<_, wasmtime::Error>(match result {
                    Ok(value) => {
                        detached = Some(value);
                        Ok(())
                    }
                    Err(error) => Err(error),
                })
            })?;
            if let Err(error) = taken {
                let error = stopped(&stop).unwrap_or(error);
                return Ok((Err(window::PreparationError::Http(convert_error(error))),));
            }
            let mut owner = match detached.take() {
                Some(Value::Upload(upload)) => super::table::WindowedUpload {
                    prepared: None,
                    upload,
                    generation: 0,
                },
                Some(Value::WindowedUpload(owner)) => owner,
                _ => return Err(trap(Error::InvalidState)),
            };
            // This call can invoke provider/clock hooks. It is deliberately
            // outside Accessor::with and retains the same original upload.
            let root_stop = stopped(&stop);
            let result = if let Some(error) = root_stop {
                Err(window::PreparationError::Http(convert_error(error)))
            } else if owner.prepared.is_some() {
                Err(window::PreparationError::Http(convert_error(
                    Error::InvalidState,
                )))
            } else if let Some(generation) = owner.generation.checked_add(1) {
                let requested = (maximum as usize).min(MAXIMUM_WINDOW);
                match owner.upload.prepare_write(requested) {
                    Ok(prepared) => {
                        let capacity = prepared.capacity();
                        if capacity == 0
                            || capacity > requested
                            || !owner.upload.owns_prepared_write(&prepared)
                        {
                            drop(prepared);
                            Err(window::PreparationError::Http(convert_error(
                                Error::InvalidState,
                            )))
                        } else {
                            let maximum_bytes = capacity as u32;
                            owner.prepared = Some(prepared);
                            owner.generation = generation;
                            Ok(window::Window {
                                generation,
                                maximum_bytes,
                            })
                        }
                    }
                    Err(error) => Err(preparation_error(error)),
                }
            } else {
                Err(window::PreparationError::Http(convert_error(Error::Http(
                    HttpError::BudgetExhausted,
                ))))
            };
            let mut held = Some(Value::WindowedUpload(owner));
            if restore(access, rep, &mut held)?.is_err() {
                // `held` remains outside the Store and drops its prepaid bytes
                // before its upload on this failure path.
                return Ok((Err(window::PreparationError::Http(convert_error(
                    root_stop.unwrap_or(Error::InvalidState),
                ))),));
            }
            Ok((result,))
        }
    }
}

struct Write;
impl
    InlineConcurrentHost<
        HostState,
        (Resource<wit::Upload>, u64, WasmList<u8>),
        (Result<(), wit::HttpError>,),
    > for Write
{
    fn invoke<'a>(
        &'a self,
        access: &'a Accessor<HostState>,
        (target, generation, bytes): (Resource<wit::Upload>, u64, WasmList<u8>),
    ) -> impl std::future::Future<Output = wasmtime::Result<(Result<(), wit::HttpError>,)>> + Send + 'a
    {
        async move {
            let rep = target.rep();
            let mut detached = None;
            let mut stop = None;
            let captured = access.with(|mut access| {
                let mut store = access.as_context_mut();
                checkpoint(&mut store)?;
                synchronize_without_host_clock(&mut store)?;
                stop = store.data().runtime_stop.clone();
                let capacity = match store
                    .data_mut()
                    .capabilities
                    .streams
                    .window_capacity(rep, generation)
                {
                    Ok(capacity) => capacity,
                    Err(error) => return Ok::<_, wasmtime::Error>(Err(error)),
                };
                if bytes.len() == 0 || bytes.len() > capacity {
                    return Ok(Err(Error::Http(HttpError::InvalidRequest)));
                }
                let value =
                    match store
                        .data_mut()
                        .capabilities
                        .streams
                        .take(rep, Kind::Upload, false)
                    {
                        Ok(value) => value,
                        Err(error) => return Ok(Err(error)),
                    };
                detached = Some(value);
                let Some(Value::WindowedUpload(owner)) = detached.as_mut() else {
                    return Ok(Err(Error::InvalidState));
                };
                let Some(prepared) = owner.prepared.as_mut() else {
                    return Ok(Err(Error::InvalidState));
                };
                // No provider, clock or allocation callback runs while Store
                // memory is borrowed. The private buffer was already paid.
                if !prepared.capture(bytes.as_le_slice(&store)) {
                    return Ok(Err(Error::InvalidState));
                }
                Ok(Ok(()))
            })?;
            if let Err(error) = captured {
                let error = stopped(&stop).unwrap_or(error);
                if detached.is_some() && restore(access, rep, &mut detached)?.is_err() {
                    return Ok((Err(convert_error(error)),));
                }
                return Ok((Err(convert_error(error)),));
            }
            let Some(Value::WindowedUpload(mut owner)) = detached.take() else {
                return Err(trap(Error::InvalidState));
            };
            if let Some(error) = stopped(&stop) {
                // No send has begun. Retire the captured buffer while the
                // original upload is still held, then restore only that owner.
                drop(owner.prepared.take());
                let mut held = Some(Value::WindowedUpload(owner));
                if restore(access, rep, &mut held)?.is_err() {
                    return Ok((Err(convert_error(error)),));
                }
                return Ok((Err(convert_error(error)),));
            }
            let input = owner
                .prepared
                .take()
                .ok_or_else(|| trap(Error::InvalidState))?;
            if !owner.upload.owns_prepared_write(&input) {
                drop(input);
                let mut held = Some(Value::WindowedUpload(owner));
                if restore(access, rep, &mut held)?.is_err() {
                    return Ok((Err(convert_error(Error::InvalidState)),));
                }
                return Ok((Err(convert_error(Error::InvalidState)),));
            }
            // The provider and its original operation may call host code; the
            // actual future and send are created only after leaving the Store.
            let result = owner.upload.write_prepared(input).await;
            let mut held = Some(Value::WindowedUpload(owner));
            if restore(access, rep, &mut held)?.is_err() {
                // The write may already have reached its transport. Do not
                // report a safely retryable refusal when restore is uncertain.
                return Ok((Err(wit::HttpError::Uncertain),));
            }
            Ok((result.map_err(convert_error),))
        }
    }
}

//! Explicit v0.4 extension over the same original, affine streaming owners.
use super::table::Reserved;
use super::{
    checkpoint, convert_error, convert_request, resources, synchronize, trap, wit, Arc,
    AsContextMut, Error, HostState, HttpError, Instant, Kind, Resource, StreamingHttpInvoker,
    Value,
};
use latent_capabilities::broker::streaming_http::{
    HttpPhaseError as Phase, PHASE_TIMING_CAPABILITY,
};
use latent_component_bindings::host::http_phases::latent::http0_4_0::phase_timing as phase_wit;

pub(crate) fn install(
    linker: &mut wasmtime::component::Linker<HostState>,
    invoker: Arc<dyn StreamingHttpInvoker>,
) -> wasmtime::Result<()> {
    let mut host = linker.instance(PHASE_TIMING_CAPABILITY)?;
    resources(&mut host)?;
    open(&mut host, invoker)?;
    finish(&mut host)?;
    read(&mut host)?;
    super::upload::write(&mut host)?;
    super::body::chunk_bytes(&mut host)?;
    super::body::trailers(&mut host)?;
    super::upload::abort_upload(&mut host)?;
    super::body::abort_body(&mut host)?;
    Ok(())
}

fn convert_phase_error(error: Phase) -> phase_wit::PhaseError {
    match error {
        Phase::Http(error) => phase_wit::PhaseError::Http(convert_error(error)),
        Phase::ConnectTimeout => phase_wit::PhaseError::ConnectTimeout,
        Phase::ReadTimeout {
            external_completion_uncertain,
        } => phase_wit::PhaseError::ReadTimeout(external_completion_uncertain),
        Phase::Unsupported => phase_wit::PhaseError::UnsupportedPhaseTiming,
    }
}

fn open(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
    invoker: Arc<dyn StreamingHttpInvoker>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent(
        "open",
        move |access, (request, timeout): (wit::Request, Option<u32>)| {
            let invoker = Arc::clone(&invoker);
            Box::pin(async move {
                let started = Instant::now();
                let opening = access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = (|| {
                        let request = convert_request(request).map_err(Phase::from)?;
                        let capabilities = &mut store.data_mut().capabilities;
                        let session = capabilities
                            .session
                            .as_ref()
                            .ok_or(HttpError::PermissionDenied)?;
                        capabilities.streams.initialize(session)?;
                        let reservation = capabilities.streams.reserve_guarded(Kind::Upload)?;
                        match invoker.start_with_connect_timeout(session, request, timeout) {
                            Ok(future) => Ok(Reserved {
                                value: future,
                                reservation,
                            }),
                            Err(error) => Err(error),
                        }
                    })();
                    synchronize(&mut store)?;
                    Ok::<_, wasmtime::Error>(result)
                })?;
                let completion = match opening {
                    Ok(mut pending) => {
                        let result = pending.value.as_mut().await;
                        // Keep successful output ahead of the guard as well.
                        drop(pending.value);
                        Ok(Reserved {
                            value: result,
                            reservation: pending.reservation,
                        })
                    }
                    Err(error) => Err(error),
                };
                access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = completion.and_then(|pending| {
                        let rep = pending.reservation.rep();
                        let table = &mut store.data_mut().capabilities.streams;
                        match pending.value {
                            Ok(upload) => {
                                table.put(rep, Kind::Upload, Value::Upload(upload))?;
                                Ok(Resource::<wit::Upload>::new_own(rep))
                            }
                            Err(error) => Err(error),
                        }
                    });
                    synchronize(&mut store)?;
                    store.data_mut().record_host_call(started);
                    Ok((result.map_err(convert_phase_error),))
                })
            })
        },
    )?;
    Ok(())
}

fn finish(host: &mut wasmtime::component::LinkerInstance<'_, HostState>) -> wasmtime::Result<()> {
    host.func_wrap_concurrent(
        "finish",
        |access, (target, timeout): (Resource<wit::Upload>, Option<u32>)| {
            Box::pin(async move {
                let started = Instant::now();
                let upload = access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = store.data_mut().capabilities.streams.take(
                        target.rep(),
                        Kind::Upload,
                        true,
                    );
                    synchronize(&mut store)?;
                    Ok::<_, wasmtime::Error>(result)
                })?;
                let body = match upload {
                    Ok(Value::Upload(upload)) => upload.finish_with_read_timeout(timeout).await,
                    Ok(_) => Err(Phase::from(Error::InvalidState)),
                    Err(error) => Err(Phase::from(error)),
                };
                access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = body.and_then(|body| {
                        let table = &mut store.data_mut().capabilities.streams;
                        let rep = table.reserve(Kind::Body)?;
                        let result = phase_wit::Response {
                            status: body.head().status(),
                            reason_phrase: body.head().reason_phrase().map(<[u8]>::to_vec),
                            headers: body
                                .head()
                                .headers()
                                .map(|(name, value)| wit::Header {
                                    name: name.into(),
                                    value: value.into(),
                                })
                                .collect(),
                            body_media_type: body.head().body_media_type().map(str::to_owned),
                            body: Resource::<wit::Body>::new_own(rep),
                        };
                        table.put(
                            rep,
                            Kind::Body,
                            Value::Body {
                                value: body,
                                trailers_delivered: false,
                            },
                        )?;
                        Ok(result)
                    });
                    synchronize(&mut store)?;
                    store.data_mut().record_host_call(started);
                    Ok((result.map_err(convert_phase_error),))
                })
            })
        },
    )?;
    Ok(())
}

fn read(host: &mut wasmtime::component::LinkerInstance<'_, HostState>) -> wasmtime::Result<()> {
    host.func_wrap_concurrent(
        "read",
        |access, (source, maximum, timeout): (Resource<wit::Body>, u32, Option<u32>)| {
            Box::pin(async move {
                let started = Instant::now();
                let rep = source.rep();
                let body = access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = (|| {
                        let reservation = store
                            .data_mut()
                            .capabilities
                            .streams
                            .reserve_guarded(Kind::Chunk)?;
                        match store
                            .data_mut()
                            .capabilities
                            .streams
                            .take(rep, Kind::Body, false)
                        {
                            Ok(value) => Ok(Reserved { value, reservation }),
                            Err(error) => Err(Phase::from(error)),
                        }
                    })();
                    synchronize(&mut store)?;
                    Ok::<_, wasmtime::Error>(result)
                })?;
                let result = match body {
                    Ok(mut pending) => {
                        let Value::Body { value, .. } = &mut pending.value else {
                            return Err(trap(Error::InvalidState));
                        };
                        let result = value.read_with_timeout(maximum as usize, timeout).await;
                        Ok(Reserved {
                            value: (pending.value, result),
                            reservation: pending.reservation,
                        })
                    }
                    Err(error) => Err(Phase::from(error)),
                };
                access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = result.and_then(|pending| {
                        let chunk = pending.reservation.rep();
                        let (body, result) = pending.value;
                        let table = &mut store.data_mut().capabilities.streams;
                        table.put(rep, Kind::Body, body)?;
                        match result {
                            Ok(Some(value)) => {
                                table.put(
                                    chunk,
                                    Kind::Chunk,
                                    Value::Chunk {
                                        value,
                                        delivered: false,
                                    },
                                )?;
                                Ok(Some(Resource::<wit::Chunk>::new_own(chunk)))
                            }
                            other => {
                                table.remove(chunk, Kind::Chunk)?;
                                other.map(|_| None)
                            }
                        }
                    });
                    synchronize(&mut store)?;
                    store.data_mut().record_host_call(started);
                    Ok((result.map_err(convert_phase_error),))
                })
            })
        },
    )?;
    Ok(())
}

use super::{
    checkpoint, convert_error, synchronize, trap, wit, AsContextMut, Error, HostState, Instant,
    Kind, Resource, Value,
};

pub(super) fn read(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent(
        "read",
        |access, (source, maximum): (Resource<wit::Body>, u32)| {
            Box::pin(async move {
                let started = Instant::now();
                let rep = source.rep();
                let body = access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = (|| {
                        let chunk = store.data_mut().capabilities.streams.reserve(Kind::Chunk)?;
                        match store
                            .data_mut()
                            .capabilities
                            .streams
                            .take(rep, Kind::Body, false)
                        {
                            Ok(value) => Ok((chunk, value)),
                            Err(error) => {
                                store
                                    .data_mut()
                                    .capabilities
                                    .streams
                                    .remove(chunk, Kind::Chunk)?;
                                Err(error)
                            }
                        }
                    })();
                    synchronize(&mut store)?;
                    Ok::<_, wasmtime::Error>(result)
                })?;
                let result = match body {
                    Ok((
                        chunk,
                        Value::Body {
                            mut value,
                            trailers_delivered,
                        },
                    )) => {
                        let result = value.read(maximum as usize).await;
                        Ok((chunk, value, trailers_delivered, result))
                    }
                    Ok(_) => return Err(trap(Error::InvalidState)),
                    Err(error) => Err(error),
                };
                access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = result.and_then(|(chunk, body, trailers_delivered, result)| {
                        let table = &mut store.data_mut().capabilities.streams;
                        table.put(
                            rep,
                            Kind::Body,
                            Value::Body {
                                value: body,
                                trailers_delivered,
                            },
                        )?;
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
                    Ok((result.map_err(convert_error),))
                })
            })
        },
    )?;
    Ok(())
}

pub(super) fn chunk_bytes(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent(
        "chunk-bytes",
        |access, (value,): (Resource<wit::Chunk>,)| {
            Box::pin(async move {
                access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = store
                        .data_mut()
                        .capabilities
                        .streams
                        .chunk_bytes(value.rep());
                    synchronize(&mut store)?;
                    Ok((result.map_err(convert_error),))
                })
            })
        },
    )?;
    Ok(())
}

pub(super) fn trailers(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent("trailers", |access, (source,): (Resource<wit::Body>,)| {
        Box::pin(async move {
            access.with(|mut access| {
                let mut store = access.as_context_mut();
                checkpoint(&mut store)?;
                let result = store.data_mut().capabilities.streams.trailers(source.rep());
                synchronize(&mut store)?;
                Ok((result.map_err(convert_error),))
            })
        })
    })?;
    Ok(())
}

pub(super) fn abort_body(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent("abort-body", |access, (target,): (Resource<wit::Body>,)| {
        Box::pin(async move {
            access.with(|mut access| {
                let mut store = access.as_context_mut();
                let result = store
                    .data_mut()
                    .capabilities
                    .streams
                    .remove(target.rep(), Kind::Body);
                checkpoint(&mut store)?;
                synchronize(&mut store)?;
                Ok((result.map_err(convert_error),))
            })
        })
    })?;
    Ok(())
}

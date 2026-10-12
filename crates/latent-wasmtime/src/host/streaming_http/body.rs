use super::table::Reserved;
use super::{
    AsContextMut, Error, HostState, Instant, Kind, Resource, Value, checkpoint, convert_error,
    synchronize, trap, wit,
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
                            Err(error) => Err(error),
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
                        let result = value.read(maximum as usize).await;
                        Ok(Reserved {
                            value: (pending.value, result),
                            reservation: pending.reservation,
                        })
                    }
                    Err(error) => Err(error),
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

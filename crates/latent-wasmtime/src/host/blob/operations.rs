use super::{
    checkpoint, convert, synchronize, trap, wit, AsContextMut, Error, HostState, Instant, Kind,
    Resource, Value,
};

pub(super) fn write(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent(
        "write",
        |access, (rep, offset, bytes): (u64, u64, Vec<u8>)| {
            Box::pin(async move {
                let started = Instant::now();
                let writer = access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let value = store
                        .data_mut()
                        .capabilities
                        .blobs
                        .take(rep, Kind::Writer, false);
                    synchronize(&mut store)?;
                    Ok::<_, wasmtime::Error>(value)
                })?;
                let result = match writer {
                    Ok(Value::Writer(mut writer)) => {
                        let result = match writer.write(offset, bytes) {
                            Ok(future) => future.await,
                            Err(e) => Err(e),
                        };
                        Ok((writer, result))
                    }
                    Ok(_) => return Err(trap(Error::InvalidState)),
                    Err(e) => Err(e),
                };
                access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = result.and_then(|(writer, result)| {
                        store.data_mut().capabilities.blobs.put(
                            rep,
                            Kind::Writer,
                            Value::Writer(writer),
                        )?;
                        result
                    });
                    synchronize(&mut store)?;
                    store.data_mut().record_host_call(started);
                    Ok((result.map_err(convert),))
                })
            })
        },
    )?;
    Ok(())
}
pub(super) fn read(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent("read", |access, (rep, offset, length): (u64, u64, u32)| {
        Box::pin(async move {
            let started = Instant::now();
            let reader = access.with(|mut access| {
                let mut store = access.as_context_mut();
                checkpoint(&mut store)?;
                let value = (|| {
                    let table = &mut store.data_mut().capabilities.blobs;
                    let chunk = table.reserve(Kind::Chunk)?;
                    match table.take(rep, Kind::Reader, false) {
                        Ok(value) => Ok((value, chunk)),
                        Err(e) => {
                            table.remove(u64::from(chunk), Kind::Chunk)?;
                            Err(e)
                        }
                    }
                })();
                synchronize(&mut store)?;
                Ok::<_, wasmtime::Error>(value)
            })?;
            let result = match reader {
                Ok((Value::Reader(mut reader), chunk)) => {
                    let result = match reader.read(offset, length) {
                        Ok(future) => future.await,
                        Err(e) => Err(e),
                    };
                    Ok((reader, chunk, result))
                }
                Ok(_) => return Err(trap(Error::InvalidState)),
                Err(e) => Err(e),
            };
            access.with(|mut access| {
                let mut store = access.as_context_mut();
                checkpoint(&mut store)?;
                let result = result.and_then(|(reader, chunk, result)| {
                    let table = &mut store.data_mut().capabilities.blobs;
                    if let Err(error) = table.put(rep, Kind::Reader, Value::Reader(reader)) {
                        // A concurrent close may retire the reader while its
                        // physical read finishes. Retire the reserved chunk too.
                        table.remove(u64::from(chunk), Kind::Chunk)?;
                        return Err(error);
                    }
                    match result {
                        Ok(value) => {
                            table.put(
                                u64::from(chunk),
                                Kind::Chunk,
                                Value::Chunk {
                                    value,
                                    delivered: false,
                                },
                            )?;
                            Ok(Resource::<wit::Chunk>::new_own(chunk))
                        }
                        Err(e) => {
                            table.remove(u64::from(chunk), Kind::Chunk)?;
                            Err(e)
                        }
                    }
                });
                synchronize(&mut store)?;
                store.data_mut().record_host_call(started);
                Ok((result.map_err(convert),))
            })
        })
    })?;
    Ok(())
}
pub(super) fn seal(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent("seal", |access, (rep,): (u64,)| {
        Box::pin(async move {
            let started = Instant::now();
            let writer = access.with(|mut access| {
                let mut store = access.as_context_mut();
                checkpoint(&mut store)?;
                let value = store
                    .data_mut()
                    .capabilities
                    .blobs
                    .take(rep, Kind::Writer, true);
                synchronize(&mut store)?;
                Ok::<_, wasmtime::Error>(value)
            })?;
            let result = match writer {
                Ok(Value::Writer(writer)) => match writer.seal() {
                    Ok(future) => future.await,
                    Err(e) => Err(e),
                },
                Ok(_) => return Err(trap(Error::InvalidState)),
                Err(e) => Err(e),
            };
            access.with(|mut access| {
                let mut store = access.as_context_mut();
                checkpoint(&mut store)?;
                let result = result.map(|sealed| {
                    store
                        .data_mut()
                        .capabilities
                        .retain_pool_lowering(sealed.owner);
                    wit::BlobReference {
                        digest: sealed.reference.digest,
                        size: sealed.reference.size,
                        media_type: sealed.reference.media_type,
                    }
                });
                synchronize(&mut store)?;
                store.data_mut().record_host_call(started);
                Ok((result.map_err(convert),))
            })
        })
    })?;
    Ok(())
}
pub(super) fn close(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent("close", |access, (rep,): (u64,)| {
        Box::pin(async move {
            access.with(|mut access| {
                let mut store = access.as_context_mut();
                let result = store.data_mut().capabilities.blobs.close(rep);
                checkpoint(&mut store)?;
                synchronize(&mut store)?;
                Ok((result.map_err(convert),))
            })
        })
    })?;
    Ok(())
}
pub(super) fn chunk_bytes(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent(
        "chunk-bytes",
        |access, (chunk,): (Resource<wit::Chunk>,)| {
            Box::pin(async move {
                access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = store.data_mut().capabilities.blobs.bytes(chunk.rep());
                    synchronize(&mut store)?;
                    Ok((result.map_err(convert),))
                })
            })
        },
    )?;
    Ok(())
}

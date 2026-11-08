use super::{
    checkpoint, convert, synchronize, trap, wit, AsContextMut, Error, HostState, Instant, Kind,
    Resource, Value,
};

use wasmtime::component::{Accessor, InlineConcurrentHost, WasmList};

pub(super) fn write(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent_inline("write", Write)?;
    Ok(())
}
struct Write;
impl InlineConcurrentHost<HostState, (u64, u64, WasmList<u8>), (Result<u64, wit::BlobError>,)>
    for Write
{
    fn invoke<'a>(
        &'a self,
        access: &'a Accessor<HostState>,
        (rep, offset, bytes): (u64, u64, WasmList<u8>),
    ) -> impl std::future::Future<Output = wasmtime::Result<(Result<u64, wit::BlobError>,)>> + Send + 'a
    {
        async move {
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
                    let result = {
                        let opening = {
                            let original_writer = writer.as_mut();
                            access.with(move |mut access| {
                                let store = access.as_context_mut();
                                // write_from's source lifetime is independent
                                // of its future's writer borrow. Only the paid
                                // copied IoBuffer survives this Store borrow.
                                Ok::<_, wasmtime::Error>(
                                    original_writer.write_from(offset, bytes.as_le_slice(&store)),
                                )
                            })?
                        };
                        match opening {
                            Ok(future) => future.await,
                            Err(e) => Err(e),
                        }
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
        }
    }
}

pub(super) fn read(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent_inline("read", Read)?;
    Ok(())
}
struct Read;
impl
    InlineConcurrentHost<
        HostState,
        (u64, u64, u32),
        (Result<Resource<wit::Chunk>, wit::BlobError>,),
    > for Read
{
    fn invoke<'a>(
        &'a self,
        access: &'a Accessor<HostState>,
        (rep, offset, length): (u64, u64, u32),
    ) -> impl std::future::Future<
        Output = wasmtime::Result<(Result<Resource<wit::Chunk>, wit::BlobError>,)>,
    > + Send
           + 'a {
        async move {
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
        }
    }
}

pub(super) fn seal(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent_inline("seal", Seal)?;
    Ok(())
}
struct Seal;
impl InlineConcurrentHost<HostState, (u64,), (Result<wit::BlobReference, wit::BlobError>,)>
    for Seal
{
    fn invoke<'a>(
        &'a self,
        access: &'a Accessor<HostState>,
        (rep,): (u64,),
    ) -> impl std::future::Future<
        Output = wasmtime::Result<(Result<wit::BlobReference, wit::BlobError>,)>,
    > + Send
           + 'a {
        async move {
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
                if result.is_ok() {
                    store.data_mut().capabilities.prepare_pool_lowering()?;
                }
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
        }
    }
}

pub(super) fn close(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent_inline("close", Close)?;
    Ok(())
}
struct Close;
impl InlineConcurrentHost<HostState, (u64,), (Result<bool, wit::BlobError>,)> for Close {
    fn invoke<'a>(
        &'a self,
        access: &'a Accessor<HostState>,
        (rep,): (u64,),
    ) -> impl std::future::Future<Output = wasmtime::Result<(Result<bool, wit::BlobError>,)>> + Send + 'a
    {
        async move {
            access.with(|mut access| {
                let mut store = access.as_context_mut();
                let result = store.data_mut().capabilities.blobs.close(rep);
                checkpoint(&mut store)?;
                synchronize(&mut store)?;
                Ok((result.map_err(convert),))
            })
        }
    }
}

pub(super) fn chunk_bytes(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent_inline("chunk-bytes", ChunkBytes)?;
    Ok(())
}
struct ChunkBytes;
impl
    InlineConcurrentHost<
        HostState,
        (Resource<wit::Chunk>,),
        (Result<crate::host::io_copy::ChunkBytes, wit::BlobError>,),
    > for ChunkBytes
{
    fn invoke<'a>(
        &'a self,
        access: &'a Accessor<HostState>,
        (chunk,): (Resource<wit::Chunk>,),
    ) -> impl std::future::Future<
        Output = wasmtime::Result<(Result<crate::host::io_copy::ChunkBytes, wit::BlobError>,)>,
    > + Send
           + 'a {
        async move {
            access.with(|mut access| {
                let mut store = access.as_context_mut();
                checkpoint(&mut store)?;
                let result = store
                    .data_mut()
                    .capabilities
                    .blobs
                    .bytes(chunk.rep())
                    .map(crate::host::io_copy::ChunkBytes);
                synchronize(&mut store)?;
                Ok((result.map_err(convert),))
            })
        }
    }
}

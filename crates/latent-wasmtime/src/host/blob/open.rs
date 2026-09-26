use super::{
    checkpoint, convert, synchronize, wit, Arc, AsContextMut, BlobInvoker, BlobReference, Error,
    HostState, Instant, Kind, Value,
};

pub(super) fn create(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
    invoker: Arc<dyn BlobInvoker>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent(
        "create",
        move |access, (media_type, expected_size): (String, Option<u64>)| {
            let invoker = invoker.clone();
            Box::pin(async move {
                let started = Instant::now();
                let start = access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = (|| {
                        let capabilities = &mut store.data_mut().capabilities;
                        let session = capabilities
                            .session
                            .as_ref()
                            .ok_or(Error::PermissionDenied)?;
                        capabilities.blobs.initialize(session)?;
                        let rep = capabilities.blobs.reserve(Kind::Writer)?;
                        match invoker.create(session, media_type, expected_size) {
                            Ok(future) => Ok((rep, future)),
                            Err(error) => {
                                capabilities.blobs.remove(u64::from(rep), Kind::Writer)?;
                                Err(error)
                            }
                        }
                    })();
                    synchronize(&mut store)?;
                    Ok::<_, wasmtime::Error>(result)
                })?;
                let result = match start {
                    Ok((rep, future)) => Ok((rep, future.await)),
                    Err(e) => Err(e),
                };
                access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = result.and_then(|(rep, result)| {
                        let table = &mut store.data_mut().capabilities.blobs;
                        match result {
                            Ok(value) => {
                                table.put(u64::from(rep), Kind::Writer, Value::Writer(value))?;
                                Ok(u64::from(rep))
                            }
                            Err(error) => {
                                table.remove(u64::from(rep), Kind::Writer)?;
                                Err(error)
                            }
                        }
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
pub(super) fn open(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
    invoker: Arc<dyn BlobInvoker>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent(
        "open",
        move |access, (reference,): (wit::BlobReference,)| {
            let invoker = invoker.clone();
            Box::pin(async move {
                let started = Instant::now();
                let start = access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = (|| {
                        let capabilities = &mut store.data_mut().capabilities;
                        let session = capabilities
                            .session
                            .as_ref()
                            .ok_or(Error::PermissionDenied)?;
                        capabilities.blobs.initialize(session)?;
                        let rep = capabilities.blobs.reserve(Kind::Reader)?;
                        match invoker.open(
                            session,
                            BlobReference {
                                digest: reference.digest,
                                size: reference.size,
                                media_type: reference.media_type,
                            },
                        ) {
                            Ok(future) => Ok((rep, future)),
                            Err(error) => {
                                capabilities.blobs.remove(u64::from(rep), Kind::Reader)?;
                                Err(error)
                            }
                        }
                    })();
                    synchronize(&mut store)?;
                    Ok::<_, wasmtime::Error>(result)
                })?;
                let result = match start {
                    Ok((rep, future)) => Ok((rep, future.await)),
                    Err(e) => Err(e),
                };
                access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = result.and_then(|(rep, result)| {
                        let table = &mut store.data_mut().capabilities.blobs;
                        match result {
                            Ok(value) => {
                                table.put(u64::from(rep), Kind::Reader, Value::Reader(value))?;
                                Ok(u64::from(rep))
                            }
                            Err(error) => {
                                table.remove(u64::from(rep), Kind::Reader)?;
                                Err(error)
                            }
                        }
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

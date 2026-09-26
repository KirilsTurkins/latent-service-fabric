use super::{
    checkpoint, convert_error, convert_request, synchronize, trap, wit, Arc, AsContextMut, Error,
    HostState, HttpError, Instant, Kind, Resource, StreamingHttpInvoker, Value,
};

pub(super) fn open(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
    invoker: Arc<dyn StreamingHttpInvoker>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent("open", move |access, (request,): (wit::Request,)| {
        let invoker = Arc::clone(&invoker);
        Box::pin(async move {
            let started = Instant::now();
            let opening = access.with(|mut access| {
                let mut store = access.as_context_mut();
                checkpoint(&mut store)?;
                let result = (|| {
                    let request = convert_request(request)?;
                    let capabilities = &mut store.data_mut().capabilities;
                    let session = capabilities
                        .session
                        .as_ref()
                        .ok_or(HttpError::PermissionDenied)?;
                    capabilities.streams.initialize(session)?;
                    let rep = capabilities.streams.reserve(Kind::Upload)?;
                    match invoker.start(session, request) {
                        Ok(future) => Ok((rep, future)),
                        Err(error) => {
                            capabilities.streams.remove(rep, Kind::Upload)?;
                            Err(error)
                        }
                    }
                })();
                synchronize(&mut store)?;
                Ok::<_, wasmtime::Error>(result)
            })?;
            let completion = match opening {
                Ok((rep, future)) => Ok((rep, future.await)),
                Err(error) => Err(error),
            };
            access.with(|mut access| {
                let mut store = access.as_context_mut();
                checkpoint(&mut store)?;
                let result = completion.and_then(|(rep, result)| {
                    let table = &mut store.data_mut().capabilities.streams;
                    match result {
                        Ok(upload) => {
                            table.put(rep, Kind::Upload, Value::Upload(upload))?;
                            Ok(Resource::<wit::Upload>::new_own(rep))
                        }
                        Err(error) => {
                            table.remove(rep, Kind::Upload)?;
                            Err(error)
                        }
                    }
                });
                synchronize(&mut store)?;
                store.data_mut().record_host_call(started);
                Ok((result.map_err(convert_error),))
            })
        })
    })?;
    Ok(())
}

pub(super) fn write(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent(
        "write",
        |access, (target, bytes): (Resource<wit::Upload>, Vec<u8>)| {
            Box::pin(async move {
                let started = Instant::now();
                let rep = target.rep();
                let upload = access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let value =
                        store
                            .data_mut()
                            .capabilities
                            .streams
                            .take(rep, Kind::Upload, false);
                    synchronize(&mut store)?;
                    Ok::<_, wasmtime::Error>(value)
                })?;
                let result = match upload {
                    Ok(Value::Upload(mut upload)) => {
                        let result = upload.write(bytes).await;
                        Ok((upload, result))
                    }
                    Ok(_) => return Err(trap(Error::InvalidState)),
                    Err(error) => Err(error),
                };
                access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = result.and_then(|(upload, result)| {
                        store.data_mut().capabilities.streams.put(
                            rep,
                            Kind::Upload,
                            Value::Upload(upload),
                        )?;
                        result
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

pub(super) fn finish(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent("finish", |access, (target,): (Resource<wit::Upload>,)| {
        Box::pin(async move {
            let started = Instant::now();
            let upload = access.with(|mut access| {
                let mut store = access.as_context_mut();
                checkpoint(&mut store)?;
                let result =
                    store
                        .data_mut()
                        .capabilities
                        .streams
                        .take(target.rep(), Kind::Upload, true);
                synchronize(&mut store)?;
                Ok::<_, wasmtime::Error>(result)
            })?;
            let body = match upload {
                Ok(Value::Upload(upload)) => upload.finish().await,
                Ok(_) => Err(Error::InvalidState),
                Err(error) => Err(error),
            };
            access.with(|mut access| {
                let mut store = access.as_context_mut();
                checkpoint(&mut store)?;
                let result = body.and_then(|body| {
                    let table = &mut store.data_mut().capabilities.streams;
                    let rep = table.reserve(Kind::Body)?;
                    let result = wit::Response {
                        status: body.head().status(),
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
                Ok((result.map_err(convert_error),))
            })
        })
    })?;
    Ok(())
}

pub(super) fn abort_upload(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent(
        "abort-upload",
        |access, (target,): (Resource<wit::Upload>,)| {
            Box::pin(async move {
                access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    let result = store
                        .data_mut()
                        .capabilities
                        .streams
                        .remove(target.rep(), Kind::Upload);
                    checkpoint(&mut store)?;
                    synchronize(&mut store)?;
                    Ok((result.map_err(convert_error),))
                })
            })
        },
    )?;
    Ok(())
}

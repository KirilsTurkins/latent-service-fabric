use super::table::Reserved;
use super::{
    checkpoint, convert_error, convert_request, synchronize, trap, wit, Arc, AsContextMut, Error,
    HostState, HttpError, Instant, Kind, Resource, StreamingHttpInvoker, Value,
};

use wasmtime::component::{Accessor, InlineConcurrentHost};

pub(super) fn open(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
    invoker: Arc<dyn StreamingHttpInvoker>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent_inline("open", Open { invoker })?;
    Ok(())
}

struct Open {
    invoker: Arc<dyn StreamingHttpInvoker>,
}
impl
    InlineConcurrentHost<
        HostState,
        (wit::Request,),
        (Result<Resource<wit::Upload>, wit::HttpError>,),
    > for Open
{
    fn invoke<'a>(
        &'a self,
        access: &'a Accessor<HostState>,
        (request,): (wit::Request,),
    ) -> impl std::future::Future<
        Output = wasmtime::Result<(Result<Resource<wit::Upload>, wit::HttpError>,)>,
    > + Send
           + 'a {
        let invoker = Arc::clone(&self.invoker);
        async move {
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
                    let reservation = capabilities.streams.reserve_guarded(Kind::Upload)?;
                    match invoker.start(session, request) {
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
                    let result = (&mut pending.value).await;
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
                Ok((result.map_err(convert_error),))
            })
        }
    }
}

pub(super) fn write(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent_inline("write", Write)?;
    Ok(())
}

struct Write;
impl
    InlineConcurrentHost<HostState, (Resource<wit::Upload>, Vec<u8>), (Result<(), wit::HttpError>,)>
    for Write
{
    fn invoke<'a>(
        &'a self,
        access: &'a Accessor<HostState>,
        (target, bytes): (Resource<wit::Upload>, Vec<u8>),
    ) -> impl std::future::Future<Output = wasmtime::Result<(Result<(), wit::HttpError>,)>> + Send + 'a
    {
        async move {
            let started = Instant::now();
            let rep = target.rep();
            let mut detached = None;
            let upload = access.with(|mut access| {
                let mut store = access.as_context_mut();
                checkpoint(&mut store)?;
                let value = store
                    .data_mut()
                    .capabilities
                    .streams
                    .take(rep, Kind::Upload, false);
                let value = match value {
                    Ok(value) => {
                        detached = Some(value);
                        Ok(())
                    }
                    Err(error) => Err(error),
                };
                synchronize(&mut store)?;
                Ok::<_, wasmtime::Error>(value)
            })?;
            let upload = upload.and_then(|()| detached.take().ok_or(Error::InvalidState));
            let result = match upload {
                Ok(Value::Upload(mut upload)) => {
                    let result = upload.write(bytes).await;
                    Ok((upload, result))
                }
                #[cfg(feature = "http-upload-window")]
                Ok(Value::WindowedUpload(mut owner)) => {
                    // A legacy write invalidates an unconsumed preparation;
                    // the generation remains and can never be reused.
                    drop(owner.prepared.take());
                    let result = owner.upload.write(bytes).await;
                    let mut held = Some(Value::WindowedUpload(owner));
                    if super::upload_window::restore(access, rep, &mut held)?.is_err() {
                        return Ok((Err(wit::HttpError::Uncertain),));
                    }
                    return Ok((result.map_err(convert_error),));
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
        }
    }
}

pub(super) fn finish(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent_inline("finish", Finish)?;
    Ok(())
}

struct Finish;
impl
    InlineConcurrentHost<
        HostState,
        (Resource<wit::Upload>,),
        (Result<wit::Response, wit::HttpError>,),
    > for Finish
{
    fn invoke<'a>(
        &'a self,
        access: &'a Accessor<HostState>,
        (target,): (Resource<wit::Upload>,),
    ) -> impl std::future::Future<Output = wasmtime::Result<(Result<wit::Response, wit::HttpError>,)>>
           + Send
           + 'a {
        async move {
            let started = Instant::now();
            let mut detached = None;
            let upload = access.with(|mut access| {
                let mut store = access.as_context_mut();
                checkpoint(&mut store)?;
                let result =
                    store
                        .data_mut()
                        .capabilities
                        .streams
                        .take(target.rep(), Kind::Upload, true);
                let result = match result {
                    Ok(value) => {
                        detached = Some(value);
                        Ok(())
                    }
                    Err(error) => Err(error),
                };
                synchronize(&mut store)?;
                Ok::<_, wasmtime::Error>(result)
            })?;
            let upload = upload.and_then(|()| detached.take().ok_or(Error::InvalidState));
            let body = match upload {
                Ok(Value::Upload(upload)) => upload.finish().await,
                #[cfg(feature = "http-upload-window")]
                Ok(Value::WindowedUpload(mut owner)) => {
                    drop(owner.prepared.take());
                    owner.upload.finish().await
                }
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
        }
    }
}

pub(super) fn abort_upload(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent_inline("abort-upload", AbortUpload)?;
    Ok(())
}

struct AbortUpload;
impl InlineConcurrentHost<HostState, (Resource<wit::Upload>,), (Result<(), wit::HttpError>,)>
    for AbortUpload
{
    fn invoke<'a>(
        &'a self,
        access: &'a Accessor<HostState>,
        (target,): (Resource<wit::Upload>,),
    ) -> impl std::future::Future<Output = wasmtime::Result<(Result<(), wit::HttpError>,)>> + Send + 'a
    {
        async move {
            #[cfg(feature = "http-upload-window")]
            let mut detached = None;
            let result = access.with(|mut access| {
                let mut store = access.as_context_mut();
                #[cfg(feature = "http-upload-window")]
                let windowed = store
                    .data_mut()
                    .capabilities
                    .streams
                    .has_windowed_upload(target.rep())
                    .unwrap_or(false);
                #[cfg(feature = "http-upload-window")]
                let result = if windowed {
                    store
                        .data_mut()
                        .capabilities
                        .streams
                        .detach_remove_upload(target.rep())
                        .map(|value| detached = value)
                } else {
                    store
                        .data_mut()
                        .capabilities
                        .streams
                        .remove(target.rep(), Kind::Upload)
                };
                #[cfg(not(feature = "http-upload-window"))]
                let result = store
                    .data_mut()
                    .capabilities
                    .streams
                    .remove(target.rep(), Kind::Upload);
                checkpoint(&mut store)?;
                #[cfg(feature = "http-upload-window")]
                if windowed {
                    crate::host::service::synchronize_without_host_clock(&mut store)?;
                } else {
                    synchronize(&mut store)?;
                }
                #[cfg(not(feature = "http-upload-window"))]
                synchronize(&mut store)?;
                Ok((result.map_err(convert_error),))
            });
            #[cfg(feature = "http-upload-window")]
            drop(detached);
            result
        }
    }
}

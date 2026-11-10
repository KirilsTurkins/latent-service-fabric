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
            complete_open(access, completion, started)
        }
    }
}

pub(super) fn complete_open(
    access: &Accessor<HostState>,
    completion: Result<
        Reserved<Result<Box<dyn latent_capabilities::broker::streaming_http::HttpUpload>, Error>>,
        Error,
    >,
    started: Instant,
) -> wasmtime::Result<(Result<Resource<wit::Upload>, wit::HttpError>,)> {
    // A failed checkpoint must not drop the provider upload or its guard
    // while Accessor::with still holds the Store. Transfer it only after the
    // checkpoint succeeds; successful publication retains its existing order.
    let mut completion = Some(completion);
    access.with(|mut access| {
        let mut store = access.as_context_mut();
        checkpoint(&mut store)?;
        let result = completion
            .take()
            .expect("one open completion")
            .and_then(|pending| {
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

pub(super) fn write(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent_inline("write", Write)?;
    Ok(())
}

pub(super) struct Write;
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
            // Keep the original upload outside Store access if the following
            // synchronization refuses or unwinds after the table take.
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
                Ok(_) => return Err(trap(Error::InvalidState)),
                Err(error) => Err(error),
            };
            complete_write(access, rep, result, started)
        }
    }
}

pub(super) fn complete_write(
    access: &Accessor<HostState>,
    rep: u32,
    result: Result<
        (
            Box<dyn latent_capabilities::broker::streaming_http::HttpUpload>,
            Result<(), Error>,
        ),
        Error,
    >,
    started: Instant,
) -> wasmtime::Result<(Result<(), wit::HttpError>,)> {
    // Keep the completed provider upload out of the Store callback until the
    // checkpoint succeeds. Its destructor may synchronously access that Store.
    let mut result = Some(result);
    let mut rejected = None;
    let completion = access.with(|mut access| {
        let mut store = access.as_context_mut();
        checkpoint(&mut store)?;
        let result = result
            .take()
            .expect("one write completion")
            .and_then(|(upload, result)| {
                let table = &mut store.data_mut().capabilities.streams;
                match table.put_upload_recoverable(rep, upload) {
                    Ok(()) => result,
                    Err((error, upload)) => {
                        rejected = Some(upload);
                        Err(error)
                    }
                }
            });
        synchronize(&mut store)?;
        store.data_mut().record_host_call(started);
        Ok((result.map_err(convert_error),))
    });
    // A stale/closed row can reject publication after the provider completed.
    // Its original upload must not be destroyed while this Store is borrowed.
    drop(rejected);
    completion
}

pub(super) fn finish(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent_inline("finish", Finish)?;
    Ok(())
}

pub(super) struct Finish;
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
            // Keep the original upload outside Store access if the following
            // synchronization refuses or unwinds after the table take.
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
                Ok(_) => Err(Error::InvalidState),
                Err(error) => Err(error),
            };
            complete_finish(access, body, started)
        }
    }
}

pub(super) fn complete_finish(
    access: &Accessor<HostState>,
    body: Result<Box<dyn latent_capabilities::broker::streaming_http::HttpBody>, Error>,
    started: Instant,
) -> wasmtime::Result<(Result<wit::Response, wit::HttpError>,)> {
    // A response may own a live provider exchange. Keep it outside the Store
    // callback until a table row is reserved and can accept that same body.
    let mut retained = None;
    let input = body.map(|body| retained = Some(body));
    let completion = access.with(|mut access| {
        let mut store = access.as_context_mut();
        checkpoint(&mut store)?;
        let result = input.and_then(|()| {
            let table = &mut store.data_mut().capabilities.streams;
            let rep = table.reserve(Kind::Body)?;
            let body = retained.as_ref().expect("one finish body");
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
            let body = retained.take().expect("one finish body");
            match table.put_body_recoverable(rep, body) {
                Ok(()) => Ok(result),
                Err((error, body)) => {
                    retained = Some(body);
                    Err(error)
                }
            }
        });
        synchronize(&mut store)?;
        store.data_mut().record_host_call(started);
        Ok((result.map_err(convert_error),))
    });
    drop(retained);
    completion
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
        async move { complete_abort_upload(access, target.rep()) }
    }
}

pub(super) fn complete_abort_upload(
    access: &Accessor<HostState>,
    rep: u32,
) -> wasmtime::Result<(Result<(), wit::HttpError>,)> {
    // Provider teardown may synchronously wake work that accesses this Store.
    // Move the original value out before any checkpoint or synchronization.
    let mut removed = None;
    let completion = access.with(|mut access| {
        let mut store = access.as_context_mut();
        let result = store
            .data_mut()
            .capabilities
            .streams
            .remove_recoverable(rep, Kind::Upload)
            .map(|value| removed = value);
        checkpoint(&mut store)?;
        synchronize(&mut store)?;
        Ok((result.map_err(convert_error),))
    });
    drop(removed);
    completion
}

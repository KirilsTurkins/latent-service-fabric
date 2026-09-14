//! Owned resources are local to a fresh Store and retain accepted I/O ownership.
use super::{
    service::{checkpoint, synchronize},
    HostState,
};
use latent_capabilities::broker::{
    http::{HttpError, HttpHeader, HttpMethod, HttpRequest},
    streaming_http::{
        StreamingHttpError as Error, StreamingHttpInvoker, StreamingHttpRequest,
        STREAMING_HTTP_CAPABILITY,
    },
};
use latent_component_bindings::host::streaming::latent::http0_3_0::streaming as wit;
use std::{sync::Arc, time::Instant};
use wasmtime::{
    component::{Linker, Resource, ResourceType},
    AsContextMut,
};
mod body;
pub(super) mod table;
mod upload;
use table::{Kind, Value};
pub(crate) fn install(
    linker: &mut Linker<HostState>,
    invoker: Arc<dyn StreamingHttpInvoker>,
) -> wasmtime::Result<()> {
    let mut host = linker.instance(STREAMING_HTTP_CAPABILITY)?;
    resources(&mut host)?;
    upload::open(&mut host, invoker)?;
    upload::write(&mut host)?;
    upload::finish(&mut host)?;
    body::read(&mut host)?;
    body::chunk_bytes(&mut host)?;
    body::trailers(&mut host)?;
    upload::abort_upload(&mut host)?;
    body::abort_body(&mut host)?;
    Ok(())
}
pub(super) fn resources(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
) -> wasmtime::Result<()> {
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
    host.resource(
        "body",
        ResourceType::host::<wit::Body>(),
        |mut store, rep| {
            store
                .data_mut()
                .capabilities
                .streams
                .remove(rep, Kind::Body)
                .map_err(trap)
        },
    )?;
    host.resource(
        "chunk",
        ResourceType::host::<wit::Chunk>(),
        |mut store, rep| {
            store
                .data_mut()
                .capabilities
                .streams
                .remove(rep, Kind::Chunk)
                .map_err(trap)
        },
    )?;
    Ok(())
}
fn convert_request(request: wit::Request) -> Result<StreamingHttpRequest, Error> {
    if request.headers.capacity() > 64 {
        return Err(HttpError::RequestTooLarge.into());
    }
    Ok(StreamingHttpRequest {
        body_length: request.body_length,
        metadata: HttpRequest {
            method: match request.method {
                wit::Method::Get => HttpMethod::Get,
                wit::Method::Head => HttpMethod::Head,
                wit::Method::Post => HttpMethod::Post,
                wit::Method::Put => HttpMethod::Put,
                wit::Method::Patch => HttpMethod::Patch,
                wit::Method::Delete => HttpMethod::Delete,
                wit::Method::Options => HttpMethod::Options,
            },
            url: request.url,
            headers: request
                .headers
                .into_iter()
                .map(|h| HttpHeader {
                    name: h.name,
                    value: h.value,
                })
                .collect(),
            body: None,
            body_media_type: request.body_media_type,
            idempotency_key: request.idempotency_key,
            timeout_millis: request.timeout_millis,
        },
    })
}
fn trap(_: Error) -> wasmtime::Error {
    wasmtime::Error::msg("invalid streaming HTTP resource")
}
fn convert_error(error: Error) -> wit::HttpError {
    match error {
        Error::InvalidState => wit::HttpError::InvalidState,
        Error::UnexpectedEof => wit::HttpError::UnexpectedEof,
        Error::UnsupportedEncoding => wit::HttpError::UnsupportedEncoding,
        Error::Http(error) => match error {
            HttpError::InvalidUrl => wit::HttpError::InvalidUrl,
            HttpError::InvalidRequest => wit::HttpError::InvalidRequest,
            HttpError::PermissionDenied => wit::HttpError::PermissionDenied,
            HttpError::RequestTooLarge => wit::HttpError::RequestTooLarge,
            HttpError::ResponseTooLarge => wit::HttpError::ResponseTooLarge,
            HttpError::DeadlineExceeded => wit::HttpError::DeadlineExceeded,
            HttpError::Cancelled => wit::HttpError::Cancelled,
            HttpError::BudgetExhausted => wit::HttpError::BudgetExhausted,
            HttpError::DnsFailed => wit::HttpError::DnsFailed,
            HttpError::TlsFailed => wit::HttpError::TlsFailed,
            HttpError::ConnectionFailed => wit::HttpError::ConnectionFailed,
            HttpError::Unavailable => wit::HttpError::Unavailable,
            HttpError::Uncertain => wit::HttpError::Uncertain,
        },
    }
}

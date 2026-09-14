//! Concurrent canonical HTTP imports retain their affine operation through lowering.
use super::{
    service::{checkpoint, synchronize},
    HostState,
};
use latent_capabilities::broker::http::{
    HttpCompletion, HttpError, HttpHeader, HttpMethod, HttpRequest, OutboundHttpInvoker,
    HTTP_CAPABILITY,
};
use latent_component_bindings::host::phase3::latent::http::client as wit;
use std::{sync::Arc, time::Instant};
use wasmtime::{component::Linker, AsContextMut};

pub(crate) fn install(
    linker: &mut Linker<HostState>,
    invoker: Arc<dyn OutboundHttpInvoker>,
) -> wasmtime::Result<()> {
    linker.instance(HTTP_CAPABILITY)?.func_wrap_concurrent(
        "send",
        move |access, (request,): (wit::Request,)| {
            let invoker = Arc::clone(&invoker);
            Box::pin(async move {
                let started = Instant::now();
                let invocation = access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let invocation = convert_request(request).and_then(|request| {
                        store
                            .data()
                            .capabilities
                            .http_start(invoker.as_ref(), request)
                    });
                    synchronize(&mut store)?;
                    Ok::<_, wasmtime::Error>(invocation)
                })?;
                let completion = match invocation {
                    Ok(future) => future.await,
                    Err(error) => Err(error),
                };
                access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = match completion {
                        Ok(HttpCompletion { response, owner }) => {
                            let result = response
                                .map(|response| wit::Response {
                                    status: response.status(),
                                    headers: response
                                        .headers()
                                        .map(|(name, value)| wit::Header {
                                            name: name.to_owned(),
                                            value: value.to_owned(),
                                        })
                                        .collect(),
                                    body: response.body().to_vec(),
                                    body_media_type: response.body_media_type().map(str::to_owned),
                                })
                                .map_err(convert_error);
                            store.data_mut().capabilities.retain_pool_lowering(owner);
                            result
                        }
                        Err(error) => Err(convert_error(error)),
                    };
                    synchronize(&mut store)?;
                    store.data_mut().record_host_call(started);
                    Ok((result,))
                })
            })
        },
    )?;
    Ok(())
}
fn convert_request(request: wit::Request) -> Result<HttpRequest, HttpError> {
    // Wasmtime hostcall fuel bounds canonical lifting before this adapter runs;
    // the provider then intersects these hard bounds with its configured limits.
    if request.headers.len() > 64 || request.headers.capacity() > 64 {
        return Err(HttpError::RequestTooLarge);
    }
    Ok(HttpRequest {
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
            .map(|header| HttpHeader {
                name: header.name,
                value: header.value,
            })
            .collect(),
        body: request.body,
        body_media_type: request.body_media_type,
        idempotency_key: request.idempotency_key,
        timeout_millis: request.timeout_millis,
    })
}
fn convert_error(error: HttpError) -> wit::HttpError {
    match error {
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
    }
}

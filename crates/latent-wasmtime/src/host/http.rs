//! Concurrent canonical HTTP imports retain their affine operation through lowering.
use super::{
    service::{checkpoint, synchronize},
    HostState,
};
use latent_capabilities::broker::http::{
    HttpCompletion, HttpError, HttpMethod, HttpRequestSource, HttpTextField, OutboundHttpInvoker,
    HTTP_CAPABILITY,
};
use latent_component_bindings::host::phase3::latent::http::client as wit;
use std::{sync::Arc, time::Instant};
use wasmtime::{
    component::{Linker, WasmList, WasmStr},
    AsContext, AsContextMut, StoreContext,
};

pub(crate) fn install(
    linker: &mut Linker<HostState>,
    invoker: Arc<dyn OutboundHttpInvoker>,
) -> wasmtime::Result<()> {
    linker.instance(HTTP_CAPABILITY)?.func_wrap_concurrent(
        "send",
        move |access, (request,): (RequestInput,)| {
            let invoker = Arc::clone(&invoker);
            Box::pin(async move {
                let started = Instant::now();
                let invocation = access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    // The admitted owner scopes this entire Store, including calls
                    // before acquiring or after dropping a guest state resource.
                    // Deny immediate effects before provider start or its budgets.
                    let invocation = if store.data().transaction.is_attached() {
                        Err(HttpError::PermissionDenied)
                    } else {
                        (|| {
                            if request.headers.len() > 64 {
                                return Err(HttpError::RequestTooLarge);
                            }
                            // Decode only fixed borrowed descriptors here; no payload storage.
                            let mut headers: [Option<HeaderInput>; 64] =
                                std::array::from_fn(|_| None);
                            for (index, slot) in
                                headers[..request.headers.len()].iter_mut().enumerate()
                            {
                                *slot = Some(
                                    request
                                        .headers
                                        .get(&mut store, index)
                                        .ok_or(HttpError::InvalidRequest)?
                                        .map_err(|_| HttpError::InvalidRequest)?,
                                );
                            }
                            let mut source = RequestSource {
                                store: store.as_context(),
                                request,
                                headers,
                            };
                            store
                                .data()
                                .capabilities
                                .http_start(invoker.as_ref(), &mut source)
                        })()
                    };
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
                        Ok(completion) => {
                            store.data_mut().capabilities.prepare_pool_lowering()?;
                            let HttpCompletion { response, owner } = completion;
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
#[derive(wasmtime::component::ComponentType, wasmtime::component::Lift)]
#[component(record)]
struct HeaderInput {
    name: WasmStr,
    value: WasmStr,
}
#[derive(wasmtime::component::ComponentType, wasmtime::component::Lift)]
#[component(record)]
struct RequestInput {
    method: wit::Method,
    url: WasmStr,
    headers: WasmList<HeaderInput>,
    body: Option<WasmList<u8>>,
    #[component(name = "body-media-type")]
    body_media_type: Option<WasmStr>,
    #[component(name = "idempotency-key")]
    idempotency_key: Option<WasmStr>,
    #[component(name = "timeout-millis")]
    timeout_millis: Option<u64>,
}
struct RequestSource<'a> {
    store: StoreContext<'a, HostState>,
    request: RequestInput,
    headers: [Option<HeaderInput>; 64],
}
impl RequestSource<'_> {
    fn field(&self, field: HttpTextField) -> Result<Option<&WasmStr>, HttpError> {
        Ok(match field {
            HttpTextField::Url => Some(&self.request.url),
            HttpTextField::HeaderName(index) => Some(
                &self
                    .headers
                    .get(index)
                    .and_then(Option::as_ref)
                    .ok_or(HttpError::InvalidRequest)?
                    .name,
            ),
            HttpTextField::HeaderValue(index) => Some(
                &self
                    .headers
                    .get(index)
                    .and_then(Option::as_ref)
                    .ok_or(HttpError::InvalidRequest)?
                    .value,
            ),
            HttpTextField::BodyMediaType => self.request.body_media_type.as_ref(),
            HttpTextField::IdempotencyKey => self.request.idempotency_key.as_ref(),
        })
    }
}
impl HttpRequestSource for RequestSource<'_> {
    fn method(&self) -> HttpMethod {
        match self.request.method {
            wit::Method::Get => HttpMethod::Get,
            wit::Method::Head => HttpMethod::Head,
            wit::Method::Post => HttpMethod::Post,
            wit::Method::Put => HttpMethod::Put,
            wit::Method::Patch => HttpMethod::Patch,
            wit::Method::Delete => HttpMethod::Delete,
            wit::Method::Options => HttpMethod::Options,
        }
    }
    fn timeout_millis(&self) -> Option<u64> {
        self.request.timeout_millis
    }
    fn header_count(&self) -> usize {
        self.request.headers.len()
    }
    fn text_len(&mut self, field: HttpTextField) -> Result<Option<usize>, HttpError> {
        self.field(field)?
            .map(|value| {
                value
                    .utf8_view(self.store.as_context())
                    .map(|v| v.len())
                    .map_err(|_| HttpError::InvalidRequest)
            })
            .transpose()
    }
    fn write_text(&mut self, field: HttpTextField, output: &mut [u8]) -> Result<(), HttpError> {
        self.field(field)?
            .ok_or(HttpError::InvalidRequest)?
            .utf8_view(self.store.as_context())
            .and_then(|view| view.write_into(output))
            .map_err(|_| HttpError::InvalidRequest)
    }
    fn body_len(&self) -> Option<usize> {
        self.request.body.as_ref().map(WasmList::len)
    }
    fn write_body(&mut self, output: &mut [u8]) -> Result<(), HttpError> {
        let bytes = self
            .request
            .body
            .as_ref()
            .ok_or(HttpError::InvalidRequest)?
            .as_le_slice(self.store.as_context());
        if output.len() != bytes.len() {
            return Err(HttpError::InvalidRequest);
        }
        output.copy_from_slice(bytes);
        Ok(())
    }
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

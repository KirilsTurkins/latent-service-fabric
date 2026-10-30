//! One accepted request owns the real driver through upload and response EOF.
use super::{wire, Inner};
use crate::{
    execute::{request, response, RequestOwner},
    network::{self, Network},
    HttpError,
};
use latent_capabilities::broker::{
    http::HttpMethod,
    io::{IoFuture, IoMemory, IoTransfer, IoTransferOptions},
    pools::{PoolAdmission, PoolCall, PooledConnection, ProviderClient},
    streaming_http::{
        HttpBody, HttpPhaseError, HttpPhaseFuture, HttpUpload, StreamingHttpError as Error,
        PHASE_TIMING_CAPABILITY, STREAMING_HTTP_CAPABILITY,
    },
    AuditProviderOutcome, CapabilityCallCost, CapabilityStreamBudget,
};
use latent_core::BudgetDimension;
use latent_policy::capability::ResourceTarget;
use std::{
    future::Future,
    pin::Pin,
    sync::{atomic::Ordering, Arc},
    task::Poll,
};
type Reply = http::Response<hyper::body::Incoming>;
/// Actual transport and request allocations always drop before their charges.
pub(super) struct Exchange {
    pub socket: Option<PooledConnection<Network>>,
    pub response: Option<Reply>,
    reply: Option<IoFuture<'static, Result<Reply, hyper::Error>>>,
    sender: wire::Sender,
    pub input: Option<Arc<IoMemory>>,
    _scratch: [IoMemory; 3],
    pub transfer: IoTransfer,
    pub call: PoolCall,
    pub inner: Arc<Inner>,
    pub head: bool,
    received: bool,
    wrote: Arc<std::sync::atomic::AtomicBool>,
}
struct Upload {
    state: Option<Exchange>,
    length: Option<u64>,
}
fn make_reply(
    (sender, request): (
        &mut hyper::client::conn::http1::SendRequest<wire::RequestBody>,
        http::Request<wire::RequestBody>,
    ),
) -> impl std::future::Future<Output = Result<Reply, hyper::Error>> + Send + 'static {
    sender.send_request(request)
}
pub(super) async fn open(
    inner: Arc<Inner>,
    input: RequestOwner,
    length: Option<u64>,
    client: Arc<ProviderClient<Network>>,
    admission: PoolAdmission,
) -> Result<Box<dyn HttpUpload>, Error> {
    let limits = inner.streaming.expect("stream profile");
    let ready = admission.wait().await?;
    let cost = cost(&inner, &input, length)?;
    let capability = if inner.phase_timing {
        PHASE_TIMING_CAPABILITY
    } else {
        STREAMING_HTTP_CAPABILITY
    };
    let mut call = ready
        .dispatch(
            capability,
            "open",
            ResourceTarget::Http {
                origin: &input.destination.origin,
                method: input.request.method.as_str(),
                path: input.destination.url.path(),
            },
            &[],
            cost,
        )
        .await?;
    let opening = async {
        // The exact Hyper reply future is prepaid before channel/request,
        // connection or send_request effects. Its sender arrives only later.
        let reply_future = call.prepare_io_future_with(make_reply)?;
        let transfer = call.io().transfer(IoTransferOptions {
            maximum_chunk_bytes: limits.maximum_chunk_bytes,
            maximum_outstanding_chunks: limits.maximum_outstanding_chunks,
        })?;
        let scratch = [
            call.io().reserve_scratch(32768, 1024)?,
            call.io().reserve_scratch(32768, 1024)?,
            call.io().reserve_scratch(
                4 * inner.config.limits.maximum_header_bytes
                    + inner.config.limits.maximum_headers * 128,
                2048,
            )?,
        ];
        let (sender, body) = wire::channel(length);
        let wire = request::build_with_body(
            &inner,
            &input.request,
            &input.destination,
            body,
            length,
            "identity",
            true,
        )?;
        let destination = &inner.config.destinations[input.destination.index];
        let answers = inner
            .resolver
            .resolve(
                &inner.pools,
                &client,
                &call,
                destination,
                input.destination.index,
            )
            .await?;
        let reason = if inner.phase_timing {
            Some(call.io().buffer(
                latent_capabilities::broker::http::MAXIMUM_HTTP_REASON_BYTES,
                128,
            )?)
        } else {
            None
        };
        let mut socket = network::connect_with_reason(
            &inner.pools,
            &client,
            &call,
            destination,
            &answers,
            &inner.tls,
            network::ResponseSettings {
                maximum_headers: inner.config.limits.maximum_headers,
                reason,
            },
        )
        .await?;
        let Network::Http(connection) = socket.resource() else {
            unreachable!("HTTP connection")
        };
        connection.wrote.store(false, Ordering::Release);
        let wrote = Arc::clone(&connection.wrote);
        connection.input = Some(input.request.memory().clone());
        let reply: IoFuture<'static, _> = reply_future.finish((&mut connection.sender, wire));
        Ok::<_, Error>((transfer, scratch, sender, socket, wrote, reply))
    }
    .await;
    let (transfer, scratch, sender, socket, wrote, reply) = match opening {
        Ok(opened) => opened,
        Err(error) => {
            call.io_mut()
                .record_provider_outcome(AuditProviderOutcome::Rejected)?;
            call.io_mut().finish_audit().await;
            return Err(error);
        }
    };
    Ok(Box::new(Upload {
        state: Some(Exchange {
            socket: Some(socket),
            response: None,
            reply: Some(reply),
            sender,
            input: Some(Arc::clone(
                input
                    .request
                    .memory()
                    .legacy()
                    .expect("streaming remains preallocated"),
            )),
            _scratch: scratch,
            transfer,
            call,
            inner,
            head: input.request.method == HttpMethod::Head,
            received: false,
            wrote,
        }),
        length,
    }))
}
impl Exchange {
    async fn progress(&mut self, drained: bool) -> Result<(), Error> {
        self.call.io().checkpoint()?;
        let connection = match self.socket.as_mut().ok_or(Error::InvalidState)?.resource() {
            Network::Http(c) => c,
            Network::Dns(_) => unreachable!("HTTP"),
        };
        let reply = &mut self.reply;
        let response = &mut self.response;
        let transfer = &self.transfer;
        let result = self
            .call
            .io()
            .wait_for(network::drive(
                &mut connection.driver,
                std::future::poll_fn(|cx| {
                    if let Some(future) = reply {
                        if let Poll::Ready(value) = Pin::new(future).poll(cx) {
                            *reply = None;
                            return Poll::Ready(value.map(|value| {
                                *response = Some(value);
                            }));
                        }
                    }
                    if response.is_some() || drained && transfer.outstanding_chunks() == 0 {
                        Poll::Ready(Ok(()))
                    } else {
                        Poll::Pending
                    }
                }),
            ))
            .await;
        let result = result
            .map_err(Error::from)
            .and_then(|r| r.map_err(Error::from))
            .and_then(|r| r.map_err(|_| HttpError::ConnectionFailed.into()));
        if let Some(reply) = &self.response {
            response::validate(reply.headers(), self.inner.config.limits)?;
            if !(200..=599).contains(&reply.status().as_u16()) {
                return Err(HttpError::ConnectionFailed.into());
            }
            if !self.received {
                self.call
                    .io_mut()
                    .record_provider_outcome(AuditProviderOutcome::HttpResponseReceived)?;
                self.received = true;
            }
        }
        if result.is_err() && !self.received && self.wrote.load(Ordering::Acquire) {
            return Err(HttpError::Uncertain.into());
        }
        result
    }
    pub async fn terminal_audit(&mut self) {
        self.call.io_mut().finish_audit().await;
    }
}
impl Drop for Exchange {
    fn drop(&mut self) {
        if !self.received {
            let outcome = if self.wrote.load(Ordering::Acquire) {
                AuditProviderOutcome::Unknown
            } else {
                AuditProviderOutcome::Rejected
            };
            let _ = self.call.io_mut().record_provider_outcome(outcome);
        }
    }
}
impl HttpUpload for Upload {
    fn write(&mut self, bytes: Vec<u8>) -> IoFuture<'_, Result<(), Error>> {
        let Some(state) = self.state.as_ref() else {
            return IoFuture::failed(Error::InvalidState);
        };
        let prepared = match state.call.prepare_io_future_with(Self::write_future) {
            Ok(prepared) => prepared,
            Err(error) => return IoFuture::failed(error.into()),
        };
        prepared.finish((self, bytes))
    }
    fn finish(self: Box<Self>) -> IoFuture<'static, Result<Box<dyn HttpBody>, Error>> {
        let Some(state) = self.state.as_ref() else {
            return IoFuture::failed(Error::InvalidState);
        };
        let prepared = match state.call.prepare_io_future_with(Self::finish_inner) {
            Ok(prepared) => prepared,
            Err(error) => return IoFuture::failed(error.into()),
        };
        prepared.finish(self)
    }
    fn finish_with_read_timeout(
        self: Box<Self>,
        timeout_millis: Option<u32>,
    ) -> HttpPhaseFuture<'static, Box<dyn HttpBody>> {
        if timeout_millis.is_none_or(|millis| millis == 0) {
            return HttpPhaseFuture::legacy(self.finish());
        }
        let Some(state) = self.state.as_ref() else {
            return HttpPhaseFuture::ready(Err(Error::InvalidState.into()));
        };
        if !state.inner.phase_timing {
            return HttpPhaseFuture::ready(Err(HttpPhaseError::Unsupported));
        }
        let deadline =
            match super::phase::Deadline::new(state.call.io().stop_handle(), timeout_millis) {
                Ok(deadline) => deadline,
                Err(error) => return HttpPhaseFuture::ready(Err(error)),
            };
        let prepared = match state.call.prepare_io_future_with(finish_with_deadline) {
            Ok(prepared) => prepared,
            Err(error) => return HttpPhaseFuture::ready(Err(error.into())),
        };
        let wrote = Arc::clone(&state.wrote);
        // Keep the original prepaid input until the wrapper's final checkpoint.
        let original_owner = state.input.clone();
        let pending = self.finish();
        HttpPhaseFuture::Direct(prepared.finish(TimedFinish {
            pending,
            deadline,
            wrote,
            original_owner,
        }))
    }
}
impl Upload {
    fn write_future<'a>(
        (this, bytes): (&'a mut Self, Vec<u8>),
    ) -> impl std::future::Future<Output = Result<(), Error>> + Send + 'a {
        this.write_inner(bytes)
    }
    async fn write_inner(&mut self, bytes: Vec<u8>) -> Result<(), Error> {
        let state = self.state.as_mut().ok_or(Error::InvalidState)?;
        state.call.io().checkpoint()?;
        if state.response.is_some() {
            return Err(Error::InvalidState);
        }
        if self.length.is_some_and(|n| {
            state
                .transfer
                .accepted_input_bytes()
                .saturating_add(bytes.len() as u64)
                > n
        }) {
            return Err(HttpError::RequestTooLarge.into());
        }
        // Admission and resident capacity precede queueing/polling the driver.
        let chunk = state.transfer.input(bytes)?;
        state.sender.send(chunk)?;
        let result = state.progress(true).await;
        if result.is_err() {
            self.state = None;
        }
        result
    }
    async fn finish_inner(mut self: Box<Self>) -> Result<Box<dyn HttpBody>, Error> {
        let mut state = self.state.take().ok_or(Error::InvalidState)?;
        state.call.io().checkpoint()?;
        if self
            .length
            .is_some_and(|n| n != state.transfer.accepted_input_bytes())
        {
            return Err(Error::UnexpectedEof);
        }
        state.sender.end();
        state.progress(false).await?;
        let capture_reason = state.inner.phase_timing;
        super::response::begin(state, capture_reason)
            .map(|body| Box::new(body) as Box<dyn HttpBody>)
    }
}
struct TimedFinish {
    pending: IoFuture<'static, Result<Box<dyn HttpBody>, Error>>,
    deadline: super::phase::Deadline,
    wrote: Arc<std::sync::atomic::AtomicBool>,
    original_owner: Option<Arc<IoMemory>>,
}
async fn finish_with_deadline(args: TimedFinish) -> Result<Box<dyn HttpBody>, HttpPhaseError> {
    let original_owner = args.original_owner;
    let result = args
        .deadline
        .wait(
            args.pending,
            HttpPhaseError::ReadTimeout {
                external_completion_uncertain: true,
            },
        )
        .await;
    drop(original_owner);
    match result {
        Ok(result) => result.map_err(Into::into),
        Err(HttpPhaseError::ReadTimeout { .. }) => Err(HttpPhaseError::ReadTimeout {
            external_completion_uncertain: args.wrote.load(Ordering::Acquire),
        }),
        Err(error) => Err(error),
    }
}

fn cost(
    inner: &Inner,
    input: &RequestOwner,
    length: Option<u64>,
) -> Result<CapabilityCallCost, Error> {
    let limits = inner.streaming.expect("stream profile");
    let metadata_digest = request::digest(&input.request, &input.destination)?;
    // The digest commits metadata, framing and allowance, never future body bytes.
    let length_bytes = length.unwrap_or(limits.maximum_input_bytes).to_le_bytes();
    let mut framing = [0u8; 17];
    framing[0] = u8::from(length.is_some());
    framing[1..9].copy_from_slice(&length_bytes);
    framing[9..].copy_from_slice(&limits.maximum_output_bytes.to_le_bytes());
    let digest = metadata_digest.with_context(&framing)?;
    let reason_metadata = if inner.phase_timing {
        // The original head and its canonical-ABI result copy coexist during
        // finish. Prepay both bounded capacities before provider dispatch.
        2 * (latent_capabilities::broker::http::MAXIMUM_HTTP_REASON_BYTES + 128)
    } else {
        0
    };
    Ok(CapabilityCallCost::new(
        4 * inner.config.limits.maximum_header_bytes
            + inner.config.limits.maximum_headers * 128
            + 2048
            + reason_metadata,
    )
    .with_typed_input_bytes(input.logical)
    .with_typed_request_digest(digest)
    .with_stream_budget(CapabilityStreamBudget::new(
        length.unwrap_or(limits.maximum_input_bytes),
        limits.maximum_output_bytes,
    )?)
    .with_charge(BudgetDimension::OutboundRequests, 1)?)
}

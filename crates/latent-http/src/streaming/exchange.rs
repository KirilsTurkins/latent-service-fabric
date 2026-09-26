//! One accepted request owns the real driver through upload and response EOF.
use super::{wire, Inner};
use crate::{
    execute::{request, response, RequestOwner},
    network::{self, Network},
    HttpError,
};
use latent_capabilities::broker::{
    http::HttpMethod,
    io::{IoMemory, IoTransfer, IoTransferOptions},
    pools::{PoolAdmission, PoolCall, PooledConnection, ProviderClient},
    streaming_http::{
        HttpBody, HttpUpload, StreamingHttpError as Error, STREAMING_HTTP_CAPABILITY,
    },
    AuditProviderOutcome, CapabilityCallCost, CapabilityStreamBudget,
};
use latent_core::{BoxFuture, BudgetDimension};
use latent_policy::capability::ResourceTarget;
use std::{
    sync::{atomic::Ordering, Arc},
    task::Poll,
};
type Reply = http::Response<hyper::body::Incoming>;
/// Actual transport and request allocations always drop before their charges.
pub(super) struct Exchange {
    pub socket: Option<PooledConnection<Network>>,
    pub response: Option<Reply>,
    reply: Option<BoxFuture<'static, Result<Reply, hyper::Error>>>,
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
    let mut call = ready
        .dispatch(
            STREAMING_HTTP_CAPABILITY,
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
        let mut socket = network::connect(
            &inner.pools,
            &client,
            &call,
            destination,
            &answers,
            &inner.tls,
            inner.config.limits.maximum_headers,
        )
        .await?;
        let Network::Http(connection) = socket.resource() else {
            unreachable!("HTTP connection")
        };
        connection.wrote.store(false, Ordering::Release);
        let wrote = Arc::clone(&connection.wrote);
        connection.input = Some(Arc::clone(&input.memory));
        let reply: BoxFuture<'static, _> = Box::pin(connection.sender.send_request(wire));
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
            input: Some(Arc::clone(&input.memory)),
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
                        if let Poll::Ready(value) = future.as_mut().poll(cx) {
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
    fn write(&mut self, bytes: Vec<u8>) -> BoxFuture<'_, Result<(), Error>> {
        Box::pin(async move {
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
        })
    }
    fn finish(mut self: Box<Self>) -> BoxFuture<'static, Result<Box<dyn HttpBody>, Error>> {
        Box::pin(async move {
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
            super::response::begin(state).map(|body| Box::new(body) as Box<dyn HttpBody>)
        })
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
    Ok(CapabilityCallCost::new(
        4 * inner.config.limits.maximum_header_bytes
            + inner.config.limits.maximum_headers * 128
            + 2048,
    )
    .with_typed_input_bytes(input.logical)
    .with_typed_request_digest(digest)
    .with_stream_budget(CapabilityStreamBudget::new(
        length.unwrap_or(limits.maximum_input_bytes),
        limits.maximum_output_bytes,
    )?)
    .with_charge(BudgetDimension::OutboundRequests, 1)?)
}

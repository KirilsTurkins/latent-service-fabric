//! Immediate operations: every hop has its own policy/audit acceptance barrier.
use crate::{
    destination::{self, Destination},
    network::{self, Network},
    provider::Inner,
    HttpError,
};
use latent_capabilities::broker::{
    http::{HttpCompletion, HttpRequest, HttpResponse, HTTP_CAPABILITY},
    io::IoMemory,
    pools::{PoolAdmission, PoolCall, ProviderClient},
    AuditProviderOutcome, CapabilityCallCost,
};
use latent_core::BudgetDimension;
use latent_policy::capability::ResourceTarget;
use std::sync::{atomic::Ordering, Arc};
pub(crate) mod request;
pub(crate) mod response;

/// Field order also protects an unpolled or cancelled invocation: owned typed
/// input and its selector drop before their original staged-byte reservation.
pub(crate) struct RequestOwner {
    pub request: HttpRequest,
    pub destination: Destination,
    pub memory: Arc<IoMemory>,
    pub logical: usize,
}

#[expect(
    clippy::too_many_lines,
    reason = "redirect ownership must drop the previous response, call and input before the next queue wait"
)]
pub(crate) async fn run(
    inner: Arc<Inner>,
    mut input: RequestOwner,
    mut client: Arc<ProviderClient<Network>>,
    mut admission: PoolAdmission,
) -> Result<HttpCompletion, HttpError> {
    let follows = input.request.method.follows_redirects()
        && input.request.body.as_ref().is_none_or(Vec::is_empty);
    let mut credentials_allowed = true;
    for hop in 0..=inner.config.limits.maximum_redirects {
        let ready = admission.wait().await?;
        let cost = CapabilityCallCost::new(inner.config.limits.output_reservation())
            .with_typed_input_bytes(input.logical)
            .with_typed_request_digest(request::digest(&input.request, &input.destination)?)
            .with_charge(BudgetDimension::OutboundRequests, 1)?;
        let mut call = ready
            .dispatch(
                HTTP_CAPABILITY,
                "send",
                ResourceTarget::Http {
                    origin: &input.destination.origin,
                    method: input.request.method.as_str(),
                    path: input.destination.url.path(),
                },
                &[],
                cost,
            )
            .await?;
        let result = exchange(
            &inner,
            &mut call,
            &client,
            &mut input.request,
            &input.destination,
            &input.memory,
            credentials_allowed,
        )
        .await;
        // The socket is closed or parked only after its request/response owners
        // are gone. Audit durability is separate from provider acceptance.
        call.io_mut().finish_audit().await;
        let response = match result {
            Ok(response) => response,
            Err(error) => {
                return Ok(HttpCompletion {
                    response: Err(error),
                    owner: call,
                })
            }
        };
        if !follows
            || hop == inner.config.limits.maximum_redirects
            || !matches!(response.status(), 301 | 302 | 303 | 307 | 308)
        {
            return Ok(HttpCompletion {
                response: Ok(response),
                owner: call,
            });
        }
        let mut locations = response.headers().filter(|(name, _)| *name == "location");
        let Some((_, location)) = locations.next() else {
            drop(locations);
            return Ok(HttpCompletion {
                response: Ok(response),
                owner: call,
            });
        };
        if locations.next().is_some() || location.len() > 2048 {
            return Ok(HttpCompletion {
                response: Err(HttpError::InvalidUrl),
                owner: call,
            });
        }
        let url = input
            .destination
            .url
            .join(location)
            .map_err(|_| HttpError::InvalidUrl)?;
        let next = destination::parse(url.as_str(), &inner.config)?;
        if !inner.config.destinations[input.destination.index]
            .redirect_destinations
            .contains(&next.index)
        {
            return Ok(HttpCompletion {
                response: Err(HttpError::PermissionDenied),
                owner: call,
            });
        }
        if next.origin != input.destination.origin {
            // Strip every guest header, including application-specific secrets.
            // Never reintroduce credentials if a chain later returns to origin.
            input.request.headers.clear();
            input.request.body_media_type = None;
            input.request.idempotency_key = None;
            credentials_allowed = false;
        }
        input.request.url = next.url.as_str().to_owned();
        let size = crate::headers::validate(
            &input.request,
            &inner.config.destinations[next.index],
            inner.config.limits,
        )?;
        let next_client = inner.client(next.index)?;
        let next_admission = inner.pools.admit_followup(&next_client, &call)?;
        let next_memory = Arc::new(next_admission.reserve_input(size.retained, 4096)?);
        // No wait can hold the old running permit (including a one-slot pool).
        drop(locations);
        drop(response);
        drop(call);
        input.memory = next_memory;
        admission = next_admission;
        client = next_client;
        input.destination = next;
        input.logical = size.logical;
    }
    unreachable!("finite redirect loop always returns its last response")
}
async fn exchange(
    inner: &Inner,
    call: &mut PoolCall,
    client: &Arc<ProviderClient<Network>>,
    request: &mut HttpRequest,
    destination: &Destination,
    memory: &Arc<IoMemory>,
    credentials_allowed: bool,
) -> Result<HttpResponse, HttpError> {
    let mut wrote = None;
    let mut received = false;
    let result = async {
        let _headers = call
            .io()
            .reserve_scratch(2 * inner.config.limits.maximum_header_bytes + 8192, 1024)?;
        let wire = request::build(
            inner,
            request,
            destination,
            Arc::clone(memory),
            credentials_allowed,
        )?;
        let configured = &inner.config.destinations[destination.index];
        let answers = inner
            .resolver
            .resolve(&inner.pools, client, call, configured, destination.index)
            .await?;
        let mut socket = network::connect(
            &inner.pools,
            client,
            call,
            configured,
            &answers,
            &inner.tls,
            inner.config.limits.maximum_headers,
        )
        .await?;
        let Network::Http(connection) = socket.resource() else {
            unreachable!("HTTP connection")
        };
        connection.wrote.store(false, Ordering::Release);
        wrote = Some(Arc::clone(&connection.wrote));
        connection.input = Some(Arc::clone(memory));
        let reply = call
            .io()
            .wait_for(network::drive(
                &mut connection.driver,
                connection.sender.send_request(wire),
            ))
            .await??
            .map_err(|_| HttpError::ConnectionFailed)?;
        if !(200..=599).contains(&reply.status().as_u16()) {
            return Err(HttpError::ConnectionFailed);
        }
        response::validate(reply.headers(), inner.config.limits)?;
        received = true;
        call.io_mut()
            .record_provider_outcome(AuditProviderOutcome::HttpResponseReceived)?;
        let reply = response::read(
            call,
            connection,
            reply,
            inner.config.limits,
            request.method == latent_capabilities::broker::http::HttpMethod::Head,
        )
        .await?;
        // Finishing a known response need not wait for an idle peer. Polling
        // readiness drives only already-ready work; a pending driver is closed.
        let ready =
            std::future::poll_fn(|cx| std::task::Poll::Ready(connection.sender.poll_ready(cx)))
                .await;
        let reusable = matches!(ready, std::task::Poll::Ready(Ok(())))
            && connection.driver.is_some()
            && Arc::strong_count(memory) == 2;
        if reusable {
            connection.input = None;
            let _ = socket.park();
        }
        // Otherwise actual socket/driver/Bytes owners drop before this returns.
        Ok(reply)
    }
    .await;
    if !received {
        let possible = wrote.is_some_and(|w| w.load(Ordering::Acquire));
        call.io_mut().record_provider_outcome(if possible {
            AuditProviderOutcome::Unknown
        } else {
            AuditProviderOutcome::Rejected
        })?;
        if possible && result.is_err() {
            return Err(HttpError::Uncertain);
        }
    }
    result
}

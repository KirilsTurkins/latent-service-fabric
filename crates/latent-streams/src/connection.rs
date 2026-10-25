//! Socket ownership is affine even when its readiness handle is shared. The
//! pool connection survives every pending Arc<TcpStream> and is never parked.
use crate::{error, provider::Inner, StreamError, StreamErrorCode, StreamResolution, StreamUsage};
use latent_capabilities::broker::{
    io::{IoCall, IoInputChunk, IoOutputChunk, IoTransfer, IoTransferOptions},
    network::{
        OutboundStream, StreamInterest, StreamObservation, StreamReadiness, StreamScope,
        StreamShutdown, StreamState, MAXIMUM_CHUNK_BYTES, STREAM_CAPABILITY,
    },
    pools::{
        ConnectionReservation, PoolAdmission, PoolCall, PooledConnection, ProviderClient,
        ProviderMetadata, StreamKernelOwnership,
    },
    AuditProviderOutcome, CapabilityAuditDurability, CapabilityCallCost, CapabilityRequestDigest,
    CapabilityStreamBudget, ProviderCall,
};
use latent_core::{budget::HostMemoryReservation, BoxFuture, BudgetDimension};
use latent_network::{canonical, NetworkError};
use latent_policy::capability::{ResourceTarget, StreamEndpoint};
use std::{
    future::Future,
    io,
    net::SocketAddr,
    pin::Pin,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
use tokio::{
    io::Interest,
    net::{TcpSocket, TcpStream},
    sync::Notify,
};

// One accepted readiness/DNS/connect future stays owned by the original IoCall.
// Only its pinned authority is inspected periodically; network work is never
// restarted or replayed when a policy or provider publication changes.
async fn wait_current<F: Future>(
    call: &IoCall,
    deadline: Instant,
    future: F,
) -> Result<F::Output, latent_core::PlatformError> {
    let deadline = deadline.min(call.deadline());
    call.wait_for(tokio::time::timeout_at(deadline.into(), async {
        tokio::pin!(future);
        loop {
            current_until(|| call.recheck_authority(), deadline).await?;
            tokio::select! {
                biased;
                result = &mut future => {
                    current_until(|| call.recheck_authority(), deadline).await?;
                    return Ok(result);
                }
                () = tokio::time::sleep(Duration::from_millis(10)) => {}
            }
        }
    }))
    .await?
    .map_err(|_| expired())?
}

async fn current_until(
    mut inspect: impl FnMut() -> Result<(), latent_core::PlatformError>,
    deadline: Instant,
) -> Result<(), latent_core::PlatformError> {
    loop {
        if Instant::now() >= deadline {
            return Err(expired());
        }
        match inspect() {
            Err(failure)
                if latent_capabilities::broker::is_authority_bookkeeping_busy(&failure) =>
            {
                // Inspect only the same accepted authority. The original
                // future, transfer, socket and deadline remain unchanged.
                tokio::time::sleep_until(
                    deadline
                        .min(Instant::now() + Duration::from_millis(10))
                        .into(),
                )
                .await;
            }
            result => return result,
        }
    }
}

async fn recheck_provider(call: &mut ProviderCall) -> Result<(), latent_core::PlatformError> {
    let deadline = call.deadline();
    current_until(|| call.recheck_authority(), deadline).await
}

async fn recheck_io(call: &IoCall, deadline: Instant) -> Result<(), latent_core::PlatformError> {
    call.wait_for(current_until(
        || call.recheck_authority(),
        deadline.min(call.deadline()),
    ))
    .await?
}

fn expired() -> latent_core::PlatformError {
    latent_core::PlatformError {
        code: latent_core::PlatformErrorCode::DeadlineExceeded,
        message: "outbound-stream-deadline".into(),
        retryable: false,
        details: Vec::new(),
    }
}

pub(crate) struct Socket {
    stream: Option<Arc<crate::transport::Transport>>,
    _tls_native: Option<HostMemoryReservation>,
    _tls_metadata: Option<ProviderMetadata>,
    _native: Option<SocketMemory>,
    _metadata: Option<ProviderMetadata>,
    _dns_native: Option<SocketMemory>,
    #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
    _dns_transport: Option<Arc<crate::kernel::native::StreamSocket>>,
    _dns_metadata: Option<ProviderMetadata>,
    kernel_mode: crate::kernel::Mode,
    // Fixed internal selection, never serialized or supplied by the caller.
    protected_selected: bool,
    _kernel_scope: Arc<StreamScope>,
    // Only the original pool's explicit quarantine may retain a lost registry
    // owner. This is the SAME Connection/PoolCall/IoCall, never replacement work.
    _quarantined_connection: Option<Arc<Connection>>,
}
impl Socket {
    // The ONLY registered callback is this fixed private host function. No
    // guest function, closure, receipt field or timeout is accepted as proof.
    fn retire_quarantined(&mut self) -> bool {
        if !self.protected_selected {
            return false;
        }
        if let Some(connection) = &self._quarantined_connection {
            let Ok(state) = connection.state.try_lock() else {
                return false;
            };
            if !state.closing || state.pending != 0 {
                return false;
            }
        }
        #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
        {
            // These are SAME original Arc/identity/Scope owners, not a second
            // context table. RETIRED validates slot/generation/lease/sequence.
            let dns = self
                ._dns_transport
                .as_ref()
                .is_none_or(|socket| socket.retire_step());
            let tcp = self.stream.as_ref().is_none_or(|stream| {
                stream.protected_owner() && stream.retire_step() && stream.protected_retired()
            });
            dns && tcp
        }
        #[cfg(not(all(target_os = "linux", any(test, feature = "development-outbound"))))]
        {
            false
        }
    }
}
enum SocketMemory {
    Logical(HostMemoryReservation),
    Kernel(StreamKernelOwnership),
}
impl SocketMemory {
    fn reserve(
        scope: &Arc<StreamScope>,
        call: &PoolCall,
        bytes: u64,
        mode: crate::kernel::Mode,
    ) -> Result<Self, latent_core::PlatformError> {
        if mode.retains_unproved() {
            call.reserve_stream_kernel_ownership(scope, bytes)
                .map(Self::Kernel)
        } else {
            scope.reserve_host_memory(bytes).map(Self::Logical)
        }
    }
    fn confirm(&mut self) {
        match self {
            Self::Logical(memory) => memory.confirm(),
            Self::Kernel(owner) => owner.confirm(),
        }
    }
}
struct Connecting {
    future: Pin<Box<dyn Future<Output = io::Result<TcpStream>> + Send>>,
}
// Declared before every actual resolver/socket future. Unwinding, cancellation,
// failed currentness and ordinary errors all drop those futures before moving
// these exact original leases into the bounded non-reusable client owner table.
struct SocketOwner {
    reservation: Option<ConnectionReservation<Socket>>,
    value: Option<Socket>,
    armed: bool,
}
impl SocketOwner {
    fn value(&mut self) -> &mut Socket {
        self.value.as_mut().expect("socket preparation")
    }
    fn connected(mut self) -> Result<PhysicalSocket, StreamError> {
        let reservation = self.reservation.take().expect("original dial reservation");
        let value = self.value.take().expect("original socket owners");
        match reservation.connected_retaining_on_error(value) {
            Ok(connection) => Ok(PhysicalSocket(Some(connection))),
            Err((error, reservation, value)) => {
                self.reservation = Some(reservation);
                self.value = Some(value);
                Err(error.into())
            }
        }
    }
}
impl Drop for SocketOwner {
    fn drop(&mut self) {
        #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
        if let Some(dns) = self.value.as_ref().and_then(|v| v._dns_transport.as_ref()) {
            dns.retire_step();
        }
        if self.armed
            && self
                .value
                .as_ref()
                .is_some_and(|v| v.kernel_mode.retains_unproved())
        {
            if self
                .value
                .as_ref()
                .and_then(|value| value.stream.as_ref())
                .is_some_and(|transport| transport.protected_retired())
            {
                return; // Actual original context retired; normal field Drop is permitted.
            }
            let mut value = self.value.take().expect("original socket owners");
            if !value
                .stream
                .as_ref()
                .is_some_and(|transport| transport.protected_owner())
            {
                drop(value.stream.take());
            }
            let reservation = self.reservation.take().expect("original dial reservation");
            if value.protected_selected {
                reservation.quarantine_stream(value, Socket::retire_quarantined);
            } else {
                reservation.quarantine(value); // Old unproved profile stays permanent.
            }
        }
    }
}
struct PhysicalSocket(Option<PooledConnection<Socket>>);
impl PhysicalSocket {
    fn quarantine_with_connection(mut self, owner: Arc<Connection>) {
        let mut original = self.0.take().expect("original physical wrapper");
        original.resource()._quarantined_connection = Some(owner);
        if original.resource().protected_selected {
            original.quarantine_stream(Socket::retire_quarantined);
        } else {
            original.quarantine();
        } // SAME original finite client quarantine table.
    }
    fn resource(&mut self) -> &mut Socket {
        self.0.as_mut().expect("physical socket owner").resource()
    }
}
impl Drop for PhysicalSocket {
    fn drop(&mut self) {
        let Some(mut original) = self.0.take() else {
            return;
        };
        if original.resource().kernel_mode.retains_unproved() {
            let protected = original
                .resource()
                .stream
                .as_ref()
                .is_some_and(|s| s.protected_owner());
            let retired = protected
                && original
                    .resource()
                    .stream
                    .as_ref()
                    .is_some_and(|s| s.protected_retired());
            if !retired {
                if !protected {
                    drop(original.resource().stream.take());
                }
                if original.resource().protected_selected {
                    original.quarantine_stream(Socket::retire_quarantined);
                } else {
                    original.quarantine();
                }
            }
        }
    }
}
#[expect(
    clippy::struct_excessive_bools,
    reason = "independent EOF, half-close, cancellation, and observed-write facts"
)]
struct State {
    socket: Option<PhysicalSocket>,
    pending: usize,
    busy: [bool; 3],
    closing: bool,
    quarantined: bool,
    failure: Option<StreamErrorCode>,
    read_eof: bool,
    write_shut: bool,
    accepted_write: u64,
    delivered_read: u64,
    attempted_write: bool,
    last_progress: Instant,
}
pub(crate) struct Connection {
    state: Mutex<State>,
    changed: Notify,
    endpoint: StreamEndpoint,
    deadline: Instant,
    idle: Duration,
    transfer: IoTransfer,
    call: PoolCall,
    scope: Arc<StreamScope>,
    owner_memory: HostMemoryReservation,
    registry: crate::connection_registry::RegistryWeak,
    _owner_metadata: Arc<ProviderMetadata>,
}
struct Handle {
    connection: Arc<Connection>,
}
/// Drop the last copied socket reference before releasing a pending-operation
/// count. `Connection::finish` takes the physical wrapper only after this edge.
struct Pending {
    socket: Arc<crate::transport::Transport>,
    _guard: PendingGuard,
    deadline: Instant,
}
struct PendingGuard {
    connection: Arc<Connection>,
    direction: usize,
}
struct ChunkOwner {
    _connection: Arc<Connection>,
    _window: latent_capabilities::broker::network::StreamChunkReservation,
}
impl Drop for PendingGuard {
    fn drop(&mut self) {
        self.connection.finish(self.direction);
    }
}

pub(crate) async fn connect(
    inner: Arc<Inner>,
    scope: StreamScope,
    index: usize,
    client: Arc<ProviderClient<Socket>>,
    admission: PoolAdmission,
    requested_deadline: Instant,
) -> Result<Box<dyn OutboundStream>, StreamError> {
    let scope = Arc::new(scope);
    let ready = admission.wait().await?;
    let destination = &inner.config.destinations[index];
    let maximum = inner.config.limits.maximum_transfer_bytes;
    let cost = CapabilityCallCost::new(0)
        .with_stream_budget(CapabilityStreamBudget::new(maximum, maximum)?)
        .with_charge(BudgetDimension::OutboundRequests, 1)?;
    let mut call = ready
        .dispatch(
            STREAM_CAPABILITY,
            "connect",
            ResourceTarget::Stream {
                endpoint: &destination.endpoint,
            },
            &[],
            cost,
        )
        .await?;
    scope.dispatched_connect()?;
    let deadline = requested_deadline.min(call.io().deadline());
    let result = create_socket(&inner, &scope, index, &client, &call, deadline).await;
    call.io_mut().record_provider_outcome(if result.is_ok() {
        AuditProviderOutcome::HostCompleted
    } else {
        AuditProviderOutcome::Unknown
    })?;
    if call.io_mut().finish_audit().await == CapabilityAuditDurability::OutcomeUnknown {
        return Err(error(StreamErrorCode::Uncertain));
    }
    let (socket, validity) = result?;
    let transfer = call.io().transfer_with_host_memory(IoTransferOptions {
        maximum_chunk_bytes: MAXIMUM_CHUNK_BYTES,
        maximum_outstanding_chunks: 4,
    })?;
    let owner_metadata = inner.pools.reserve_protocol_metadata(16 * 1024)?;
    let owner_memory = scope.reserve_host_memory(16 * 1024)?;
    // Both new Arc layouts stay inside the original prepaid 16-KiB owner.
    if crate::connection_registry::arc_bytes::<Connection>()
        + crate::connection_registry::arc_bytes::<ProviderMetadata>()
        > 16 * 1024
    {
        return Err(error(StreamErrorCode::Exhausted));
    }
    let owner_metadata = Arc::new(owner_metadata);
    let mut connection = Arc::new(Connection {
        state: Mutex::new(State {
            socket: Some(socket),
            pending: 0,
            busy: [false; 3],
            closing: false,
            quarantined: false,
            failure: None,
            read_eof: false,
            write_shut: false,
            accepted_write: 0,
            delivered_read: 0,
            attempted_write: false,
            last_progress: Instant::now(),
        }),
        changed: Notify::new(),
        endpoint: destination.endpoint.clone(),
        deadline: deadline.min(validity),
        idle: Duration::from_millis(u64::from(inner.config.limits.idle_timeout_millis)),
        transfer,
        call,
        scope,
        owner_memory,
        registry: inner.connections.downgrade(),
        _owner_metadata: owner_metadata,
    });
    // Move the confirmed owner reservation into the real Arc; it cannot be
    // refunded by a facade while a pending operation still retains the Arc.
    Arc::get_mut(&mut connection)
        .expect("new owner")
        .owner_memory
        .confirm();
    inner.connections.register(&connection)?;
    Ok(Box::new(Handle { connection }))
}

#[expect(
    clippy::too_many_lines,
    reason = "one original reservation owns DNS, socket, TLS handshaking and retirement"
)]
async fn create_socket(
    inner: &Inner,
    scope: &Arc<StreamScope>,
    index: usize,
    client: &Arc<ProviderClient<Socket>>,
    call: &PoolCall,
    deadline: Instant,
) -> Result<(PhysicalSocket, Instant), StreamError> {
    let destination = &inner.config.destinations[index];
    let reservation = client.reserve_connection_wait(call).await?;
    let mut owned = SocketOwner {
        reservation: Some(reservation),
        value: Some(Socket {
            stream: None,
            _tls_native: None,
            _tls_metadata: None,
            _native: None,
            _metadata: None,
            _dns_native: None,
            #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
            _dns_transport: None,
            _dns_metadata: None,
            kernel_mode: inner.kernel_mode,
            #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
            protected_selected: inner.native_bank.is_some(),
            #[cfg(not(all(target_os = "linux", any(test, feature = "development-outbound"))))]
            protected_selected: false,
            _kernel_scope: Arc::clone(scope),
            _quarantined_connection: None,
        }),
        armed: false,
    };
    // Prepay DNS packet/socket ownership before the resolver can allocate its
    // UDP/TCP state. Unknown final kernel retirement retains the same bundle;
    // only the historical logical reference stops at owned-future destruction.
    let (address, valid_until) = match &destination.resolution {
        StreamResolution::Static { addresses } => (
            *addresses
                .first()
                .ok_or_else(|| error(StreamErrorCode::Denied))?,
            deadline,
        ),
        StreamResolution::Dns { server, .. } => {
            #[cfg(not(all(target_os = "linux", any(test, feature = "development-outbound"))))]
            let _ = server;
            owned.value()._dns_native = Some(SocketMemory::reserve(
                scope,
                call,
                64 * 1024,
                inner.kernel_mode,
            )?);
            owned.value()._dns_metadata = Some(inner.pools.reserve_protocol_metadata(64 * 1024)?);
            let resolver = inner.resolvers[index]
                .as_ref()
                .ok_or_else(|| error(StreamErrorCode::DnsFailed))?;
            owned.armed = true;
            #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
            let protected = if let Some(bank) = &inner.native_bank {
                let original = match owned.value()._dns_native.take() {
                    Some(SocketMemory::Kernel(original)) => original,
                    _ => return Err(error(StreamErrorCode::Denied)),
                };
                let socket = crate::kernel::native::StreamSocket::prepare_dns(
                    Arc::clone(bank),
                    original,
                    *server,
                    deadline,
                )?;
                // Original pool/quarantine owns this Arc BEFORE any constructor
                // or UDP/TCP future. Cancellation never drops an entered loan.
                owned.value()._dns_transport = Some(Arc::clone(&socket));
                let mut transport =
                    crate::kernel::native::StreamDnsExchange::new(Arc::clone(&socket), *server);
                let result = wait_current(
                    call.io(),
                    deadline,
                    resolver.resolve_with_expiry_using(deadline.into(), &mut || {}, &mut transport),
                )
                .await;
                // Close ACK is not occupancy return. Both successful answers
                // and failed queries keep this SAME admission until RETIRED.
                socket.retire_step();
                let retired = wait_current(
                    call.io(),
                    deadline,
                    std::future::poll_fn(|_| {
                        if socket.retire_step() {
                            std::task::Poll::Ready(())
                        } else {
                            std::task::Poll::Pending
                        }
                    }),
                )
                .await;
                // Preserve the original resolution/authority failure even if
                // cleanup cannot finish; SocketOwner retains the SAME loan.
                let protocol_may_have_applied = transport.may_have_applied();
                let answers = result
                    .map_err(|authority| {
                        // wait_current can fail its POST-future authority check.
                        // Preserve that code, plus effects of actual earlier DNS IO.
                        StreamError::from(authority).uncertain(protocol_may_have_applied)
                    })?
                    .map_err(|network| {
                        transport.take_failure().map_or_else(
                            || network_error(network).uncertain(protocol_may_have_applied),
                            |mut native| {
                                // Retain actual private native code/uncertainty. This
                                // prefix counts DNS protocol bytes, NOT app plaintext.
                                native.may_have_applied |=
                                    protocol_may_have_applied || native.accepted_prefix_bytes != 0;
                                native.accepted_prefix_bytes = 0;
                                native
                            },
                        )
                    })?;
                retired.map_err(|authority| {
                    StreamError::from(authority).uncertain(protocol_may_have_applied)
                })?;
                drop(transport);
                drop(owned.value()._dns_transport.take());
                Some(answers)
            } else {
                None
            };
            #[cfg(not(all(target_os = "linux", any(test, feature = "development-outbound"))))]
            let protected: Option<latent_network::dns::ResolvedAnswers> = None;
            let answers = match protected {
                Some(answers) => answers,
                None => {
                    let dns_memory = owned
                        .value()
                        ._dns_native
                        .as_mut()
                        .expect("original DNS allowance");
                    wait_current(
                        call.io(),
                        deadline,
                        resolver.resolve_with_expiry_observed(deadline.into(), &mut || {
                            dns_memory.confirm()
                        }),
                    )
                    .await?
                    .map_err(network_error)?
                }
            };
            let first = answers
                .answers
                .iter()
                .next()
                .ok_or_else(|| error(StreamErrorCode::DnsFailed))?;
            (first, answers.valid_until.into_std())
        }
    };
    if !inner.kernel_mode.retains_unproved() {
        // Historical logical-only references retain their original semantics.
        drop(owned.value()._dns_native.take());
        drop(owned.value()._dns_metadata.take());
    }
    if Instant::now() >= valid_until || !destination.addresses.permits(address) {
        return Err(error(StreamErrorCode::Denied));
    }
    recheck_io(call.io(), deadline.min(valid_until)).await?;
    owned.value()._metadata = Some(inner.pools.reserve_protocol_metadata(96 * 1024)?);
    owned.value()._native = Some(SocketMemory::reserve(
        scope,
        call,
        96 * 1024,
        inner.kernel_mode,
    )?);
    let tls_allowance = inner.tls[index]
        .as_ref()
        .map(|_| {
            Ok::<_, StreamError>((
                scope.reserve_host_memory(
                    u64::try_from(crate::tls::CONNECTION_ALLOWANCE).expect("fixed TLS allowance"),
                )?,
                inner
                    .pools
                    .reserve_protocol_metadata(crate::tls::CONNECTION_ALLOWANCE)?,
            ))
        })
        .transpose()?;
    if let Some((memory, metadata)) = tls_allowance {
        owned.value()._tls_native = Some(memory);
        owned.value()._tls_metadata = Some(metadata);
    }
    #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
    if let Some(bank) = &inner.native_bank {
        let original = match owned.value()._native.take() {
            Some(SocketMemory::Kernel(original)) => original,
            _ => return Err(error(StreamErrorCode::Denied)),
        };
        let peer = SocketAddr::new(canonical(address), destination.endpoint.port);
        let socket = crate::kernel::native::StreamSocket::prepare(
            Arc::clone(bank),
            original,
            peer,
            deadline.min(valid_until),
        )?;
        if let Some(memory) = owned.value()._tls_native.as_mut() {
            memory.confirm();
        }
        let transport = Arc::new(crate::transport::Transport::protected(
            Arc::clone(&socket),
            inner.tls[index].as_ref().map(Arc::clone),
            destination.endpoint.host.clone(),
        )?);
        // SAME original PooledConnection/Scope custody is attached BEFORE any
        // protected constructor syscall can execute, including failed birth.
        owned.value().stream = Some(Arc::clone(&transport));
        owned.armed = true;
        let connected =
            wait_current(call.io(), deadline.min(valid_until), socket.connect(peer)).await?;
        if let Err(fault) = connected {
            socket.retire_step(); // One real cleanup attempt, never a refund proof.
            return Err(fault);
        }
        if transport.host_tls() {
            loop {
                recheck_io(call.io(), deadline.min(valid_until)).await?;
                let Some(interest) = transport.handshake_step()? else {
                    break;
                };
                wait_current(
                    call.io(),
                    deadline.min(valid_until),
                    transport.ready(interest),
                )
                .await?
                .map_err(|_| error(StreamErrorCode::TlsFailed))?;
            }
        }
        return Ok((owned.connected()?, valid_until));
    }
    owned.armed = true;
    let socket = if address.is_ipv4() {
        TcpSocket::new_v4()
    } else {
        TcpSocket::new_v6()
    }
    .map_err(|_| error(StreamErrorCode::ConnectFailed))?;
    owned
        .value()
        ._native
        .as_mut()
        .expect("original socket allowance")
        .confirm();
    socket
        .set_send_buffer_size(16 * 1024)
        .map_err(|_| error(StreamErrorCode::ConnectFailed))?;
    socket
        .set_recv_buffer_size(32 * 1024)
        .map_err(|_| error(StreamErrorCode::ConnectFailed))?;
    let actual = socket
        .send_buffer_size()
        .and_then(|send| {
            socket
                .recv_buffer_size()
                .map(|receive| u64::from(send) + u64::from(receive))
        })
        .map_err(|_| error(StreamErrorCode::ConnectFailed))?;
    if actual > 96 * 1024 {
        return Err(error(StreamErrorCode::Exhausted));
    }
    let peer = SocketAddr::new(address, destination.endpoint.port);
    let mut connecting = Connecting {
        future: Box::pin(socket.connect(peer)),
    };
    recheck_io(call.io(), deadline.min(valid_until)).await?;
    let stream = wait_current(
        call.io(),
        deadline.min(valid_until),
        connecting.future.as_mut(),
    )
    .await?
    .map_err(|_| error(StreamErrorCode::ConnectFailed))?;
    let peer = stream
        .peer_addr()
        .map_err(|_| error(StreamErrorCode::ConnectFailed))?;
    if canonical(peer.ip()) != address
        || peer.port() != destination.endpoint.port
        || !destination.addresses.permits(peer.ip())
    {
        return Err(error(StreamErrorCode::Denied));
    }
    stream
        .set_nodelay(true)
        .map_err(|_| error(StreamErrorCode::ConnectFailed))?;
    if let Some(memory) = owned.value()._tls_native.as_mut() {
        memory.confirm();
    }
    let transport = match &inner.tls[index] {
        Some(tls) => crate::transport::Transport::tls(
            stream,
            Arc::clone(tls),
            destination.endpoint.host.clone(),
        )?,
        None => crate::transport::Transport::tcp(stream),
    };
    if transport.host_tls() {
        loop {
            recheck_io(call.io(), deadline.min(valid_until)).await?;
            let Some(interest) = transport.handshake_step()? else {
                break;
            };
            wait_current(
                call.io(),
                deadline.min(valid_until),
                transport.ready(interest),
            )
            .await?
            .map_err(|_| error(StreamErrorCode::TlsFailed))?;
        }
    }
    owned.value().stream = Some(Arc::new(transport));
    Ok((owned.connected()?, valid_until))
}

impl Connection {
    pub(crate) fn metadata_billing(&self) -> Arc<ProviderMetadata> {
        Arc::clone(&self._owner_metadata)
    }

    // The last copied transport reference retires before PendingGuard calls
    // finish. Only a now-empty original physical wrapper may release custody.
    fn release_retiring_if_done(&self) {
        let done = self
            .state
            .try_lock()
            .is_ok_and(|state| state.closing && state.pending == 0 && state.socket.is_none());
        if done {
            self.registry.release(self);
        }
    }

    pub(crate) fn maintenance_step(self: &Arc<Self>, now: Instant) {
        self.release_retiring_if_done();
        let transport = {
            let Ok(mut state) = self.state.try_lock() else {
                return;
            };
            state
                .socket
                .as_mut()
                .and_then(|physical| physical.resource().stream.as_ref().map(Arc::clone))
        };
        if let Some(transport) = transport {
            transport.maintenance();
        }
        self.drain_closed();
        let expired = match self.state.try_lock() {
            Ok(state) => {
                !state.closing && now >= self.deadline.min(state.last_progress + self.idle)
            }
            Err(std::sync::TryLockError::WouldBlock) => return,
            Err(std::sync::TryLockError::Poisoned(poisoned)) => {
                drop(poisoned.into_inner());
                self.abort(StreamErrorCode::Exhausted);
                return;
            }
        };
        if expired {
            self.abort(StreamErrorCode::Timeout);
            return;
        }
        if let Err(failure) = self.call.io().recheck_authority() {
            if !latent_capabilities::broker::is_authority_bookkeeping_busy(&failure) {
                self.abort(StreamError::from(failure).code);
            }
        }
    }

    fn pending(
        self: &Arc<Self>,
        direction: usize,
        timeout: Option<u32>,
    ) -> Result<Pending, StreamError> {
        self.call
            .io()
            .checkpoint()
            .map_err(|failure| self.terminal_error(failure.into()))?;
        if timeout.is_some_and(|value| value == 0 || value > 10_000) {
            return Err(error(StreamErrorCode::InvalidInput));
        }
        let mut state = self
            .state
            .lock()
            .map_err(|_| error(StreamErrorCode::Exhausted))?;
        if state.closing {
            return Err(
                error(state.failure.unwrap_or(StreamErrorCode::InvalidState))
                    .uncertain(state.attempted_write),
            );
        }
        if state.busy[direction] || (direction == 1 && state.write_shut) {
            return Err(error(StreamErrorCode::InvalidState));
        }
        let now = Instant::now();
        let mut deadline = self.deadline.min(state.last_progress + self.idle);
        if let Some(value) = timeout {
            deadline = deadline.min(now + Duration::from_millis(u64::from(value)));
        }
        if now >= deadline {
            return Err(error(StreamErrorCode::Timeout).uncertain(state.attempted_write));
        }
        let socket = Arc::clone(
            &state
                .socket
                .as_mut()
                .ok_or_else(|| error(StreamErrorCode::InvalidState))?
                .resource()
                .stream
                .as_ref()
                .expect("live socket transport"),
        );
        state.pending += 1;
        state.busy[direction] = true;
        Ok(Pending {
            socket,
            _guard: PendingGuard {
                connection: Arc::clone(self),
                direction,
            },
            deadline,
        })
    }
    fn drain_closed(&self) {
        let transport = {
            let Ok(mut state) = self.state.try_lock() else {
                return;
            };
            if !state.closing || state.pending != 0 {
                return;
            }
            state
                .socket
                .as_mut()
                .and_then(|physical| physical.resource().stream.as_ref().map(Arc::clone))
        };
        let released = transport
            .as_ref()
            .is_none_or(|transport| transport.retire_step());
        drop(transport); // No copied transport remains when wrapper is removed.
        if !released {
            return;
        }
        let physical = {
            let mut state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            if state.closing && state.pending == 0 {
                state.socket.take()
            } else {
                None
            }
        };
        drop(physical);
        self.release_retiring_if_done();
        self.changed.notify_waiters();
    }
    fn finish(&self, direction: usize) {
        {
            let mut state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.pending -= 1;
            state.busy[direction] = false;
        }
        self.drain_closed();
        self.changed.notify_waiters();
    }
    pub(crate) fn abort(self: &Arc<Self>, reason: StreamErrorCode) {
        self.stop(Some(reason));
    }
    fn stop(self: &Arc<Self>, reason: Option<StreamErrorCode>) {
        // SAME registry slot takes strong custody before admission closes.
        // Refusal never fabricates a release: original physical Drop still
        // follows its same mode-specific quarantine contract.
        if !self.registry.retain(self) {
            // Registry teardown/missing identity cannot become an ordinary
            // release. Move the SAME full original owner into its original
            // paid client quarantine; no callbacks or Drop under state lock.
            let physical = {
                let mut state = self
                    .state
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                state.closing = true;
                state.quarantined = true;
                state.failure = Some(StreamErrorCode::Uncertain);
                state.socket.take()
            };
            self.call.io().stop_handle().stop();
            if let Some(physical) = physical {
                physical.quarantine_with_connection(Arc::clone(self));
            }
            self.changed.notify_waiters();
            return;
        }
        {
            let mut state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.closing = true;
            if state.failure.is_none() {
                state.failure = reason;
            }
        }
        self.call.io().stop_handle().stop();
        self.drain_closed();
        self.changed.notify_waiters();
    }
    fn observe(&self) -> StreamObservation {
        let state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let phase = if state.closing {
            if state.socket.is_some() {
                StreamState::Stopping
            } else if state.failure.is_some() {
                StreamState::Failed
            } else {
                StreamState::Closed
            }
        } else {
            match (state.read_eof, state.write_shut) {
                (false, false) => StreamState::Open,
                (true, false) => StreamState::ReadEof,
                (false, true) => StreamState::WriteShut,
                (true, true) => StreamState::ReadEofWriteShut,
            }
        };
        StreamObservation {
            state: phase,
            accepted_write_bytes: state.accepted_write,
            delivered_read_bytes: state.delivered_read,
            application_write_attempted: state.attempted_write,
        }
    }
    pub(crate) fn usage(&self) -> Result<StreamUsage, StreamError> {
        let state = self.state.try_lock().map_err(crate::snapshot_lock_error)?;
        Ok(StreamUsage {
            owners: 1,
            connections: usize::from(state.socket.is_some()),
            pending_operations: state.pending,
            retained_chunks: self.transfer.outstanding_chunks(),
            #[cfg(any(test, feature = "development-outbound"))]
            input_budget_bytes: self.transfer.accepted_input_bytes(),
            accepted_write_bytes: state.accepted_write,
            delivered_read_bytes: state.delivered_read,
            retired: false,
        })
    }
    async fn authorize(
        self: &Arc<Self>,
        operation: &str,
        cost: CapabilityCallCost,
    ) -> Result<ProviderCall, StreamError> {
        let result: Result<ProviderCall, StreamError> = async {
            let prepared = self.scope.with_session(|session| {
                session.prepare_owned_dispatch(
                    STREAM_CAPABILITY,
                    operation,
                    ResourceTarget::Stream {
                        endpoint: &self.endpoint,
                    },
                    &[],
                    cost,
                )
            })?;
            prepared
                .dispatch(|call| {
                    call.require_host_mode()?;
                    Ok::<_, latent_core::PlatformError>(call)
                })
                .await?
                .map_err(Into::into)
        }
        .await;
        result.map_err(|failure| {
            self.abort(failure.code);
            self.terminal_error(failure)
        })
    }
    fn terminal_error(&self, mut failure: StreamError) -> StreamError {
        let state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        failure.code = state.failure.unwrap_or(failure.code);
        failure.uncertain(state.attempted_write)
    }
    async fn wait<F: Future>(
        &self,
        pending: &Pending,
        call_deadline: Instant,
        future: F,
    ) -> Result<F::Output, StreamError> {
        let deadline = pending.deadline.min(call_deadline);
        wait_current(self.call.io(), deadline, future)
            .await
            .map_err(Into::into)
    }
    async fn audit(&self, mut call: ProviderCall, success: bool) -> Result<(), StreamError> {
        call.record_provider_outcome(if success {
            AuditProviderOutcome::HostCompleted
        } else {
            AuditProviderOutcome::Unknown
        })?;
        if call.finish_audit().await == CapabilityAuditDurability::OutcomeUnknown {
            return Err(error(StreamErrorCode::Uncertain)
                .uncertain(self.observe().application_write_attempted));
        }
        Ok(())
    }
}

impl OutboundStream for Handle {
    fn read(
        &self,
        maximum: usize,
        timeout: Option<u32>,
    ) -> Result<BoxFuture<'static, Result<Option<IoOutputChunk>, StreamError>>, StreamError> {
        if maximum == 0 || maximum > MAXIMUM_CHUNK_BYTES {
            return Err(error(StreamErrorCode::InvalidInput));
        }
        let pending = self.connection.pending(0, timeout)?;
        let window = self.connection.scope.reserve_chunk(maximum * 2)?;
        let mut buffer = self.connection.transfer.output_buffer(maximum)?;
        buffer.retain_owner(Arc::new(ChunkOwner {
            _connection: Arc::clone(&self.connection),
            _window: window,
        }))?;
        let connection = Arc::clone(&self.connection);
        Ok(Box::pin(async move {
            let mut call = connection
                .authorize("read", CapabilityCallCost::new(maximum))
                .await?;
            connection.scope.charge_transfer(maximum)?;
            let result = connection
                .wait(&pending, call.deadline(), async {
                    loop {
                        recheck_provider(&mut call).await?;
                        match pending.socket.try_read(buffer.spare_mut()?) {
                            Ok(None) => pending
                                .socket
                                .readable()
                                .await
                                .map_err(|_| error(StreamErrorCode::IoFailed))?,
                            Ok(Some(count)) => break Ok(count),
                            Err(error) => break Err(error),
                        }
                    }
                })
                .await
                .and_then(|value| value);
            let count = match result {
                Ok(count) => count,
                Err(failure) => {
                    connection.abort(failure.code);
                    connection.audit(call, false).await?;
                    return Err(connection.terminal_error(failure));
                }
            };
            {
                let mut state = connection
                    .state
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                state.read_eof |= count == 0;
                state.delivered_read += count as u64;
                if count != 0 {
                    state.last_progress = Instant::now();
                }
            }
            buffer.advance_written(count)?;
            let result = if count == 0 {
                None
            } else {
                Some(buffer.finish()?)
            };
            connection.audit(call, true).await?;
            Ok(result)
        }))
    }
    fn write(
        &self,
        bytes: Vec<u8>,
        timeout: Option<u32>,
    ) -> Result<BoxFuture<'static, Result<u32, StreamError>>, StreamError> {
        let maximum = bytes.capacity();
        let mut bytes = Some(bytes);
        self.write_from(maximum, timeout, &mut || {
            Ok(bytes.take().expect("single producer"))
        })
    }
    fn write_from(
        &self,
        maximum: usize,
        timeout: Option<u32>,
        produce: &mut dyn FnMut() -> Result<Vec<u8>, latent_core::PlatformError>,
    ) -> Result<BoxFuture<'static, Result<u32, StreamError>>, StreamError> {
        if maximum == 0 || maximum > MAXIMUM_CHUNK_BYTES {
            return Err(error(StreamErrorCode::InvalidInput));
        }
        let pending = self.connection.pending(1, timeout)?;
        let window = self.connection.scope.reserve_chunk(maximum)?;
        let mut input: IoInputChunk = self.connection.transfer.input_with(maximum, produce)?;
        let cost = CapabilityCallCost::new(0)
            .with_typed_input_bytes(input.as_ref().len())
            .with_typed_request_digest(CapabilityRequestDigest::from_parts(&[input.as_ref()])?);
        input.retain_owner(Arc::new(ChunkOwner {
            _connection: Arc::clone(&self.connection),
            _window: window,
        }))?;
        let connection = Arc::clone(&self.connection);
        Ok(Box::pin(async move {
            let mut call = connection.authorize("write", cost).await?;
            connection.scope.charge_transfer(input.as_ref().len())?;
            let mut accepted_prefix = 0u32;
            let result = connection
                .wait(&pending, call.deadline(), async {
                    loop {
                        recheck_provider(&mut call).await?;
                        connection
                            .state
                            .lock()
                            .unwrap_or_else(std::sync::PoisonError::into_inner)
                            .attempted_write = true;
                        match pending.socket.try_write(input.as_ref()) {
                            Ok(None) => pending
                                .socket
                                .writable()
                                .await
                                .map_err(|_| error(StreamErrorCode::IoFailed))?,
                            Ok(Some(count)) => {
                                accepted_prefix = u32::try_from(count).expect("bounded chunk");
                                // Flush only this accepted plaintext prefix.
                                // No new write or retry occurs while waiting.
                                loop {
                                    recheck_provider(&mut call).await?;
                                    if pending.socket.flush_pending()? {
                                        break;
                                    }
                                    pending
                                        .socket
                                        .writable()
                                        .await
                                        .map_err(|_| error(StreamErrorCode::IoFailed))?;
                                }
                                break Ok(count);
                            }
                            Err(error) => break Err(error),
                        }
                    }
                })
                .await
                .and_then(|value| value);
            let count = match result {
                Ok(count) if count != 0 => count,
                Ok(_) => {
                    connection.abort(StreamErrorCode::IoFailed);
                    connection.audit(call, false).await?;
                    return Err(error(StreamErrorCode::IoFailed).uncertain(true));
                }
                Err(mut failure) => {
                    failure.accepted_prefix_bytes =
                        failure.accepted_prefix_bytes.max(accepted_prefix);
                    if failure.accepted_prefix_bytes != 0 {
                        connection
                            .state
                            .lock()
                            .unwrap_or_else(std::sync::PoisonError::into_inner)
                            .accepted_write += u64::from(failure.accepted_prefix_bytes);
                    }
                    connection.abort(failure.code);
                    connection.audit(call, false).await?;
                    return Err(connection.terminal_error(failure));
                }
            };
            {
                let mut state = connection
                    .state
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                state.accepted_write += count as u64;
                state.last_progress = Instant::now();
            }
            if let Err(mut failure) = connection.audit(call, true).await {
                failure.accepted_prefix_bytes = u32::try_from(count).expect("bounded chunk");
                return Err(failure.uncertain(true));
            }
            Ok(u32::try_from(count).expect("bounded chunk"))
        }))
    }
    fn ready(
        &self,
        interest: StreamInterest,
        timeout: Option<u32>,
    ) -> Result<BoxFuture<'static, Result<StreamReadiness, StreamError>>, StreamError> {
        let pending = self.connection.pending(2, timeout)?;
        let connection = Arc::clone(&self.connection);
        Ok(Box::pin(async move {
            let call = connection
                .authorize("ready", CapabilityCallCost::new(0))
                .await?;
            let selected = match interest {
                StreamInterest::Readable => Interest::READABLE,
                StreamInterest::Writable => Interest::WRITABLE,
                StreamInterest::Either => Interest::READABLE | Interest::WRITABLE,
            };
            if matches!(interest, StreamInterest::Readable | StreamInterest::Either)
                && pending.socket.buffered_readable()?
            {
                connection.audit(call, true).await?;
                return Ok(StreamReadiness {
                    readable: true,
                    writable: false,
                });
            }
            let result = connection
                .wait(&pending, call.deadline(), pending.socket.ready(selected))
                .await
                .and_then(|value| value.map_err(|_| error(StreamErrorCode::IoFailed)));
            match result {
                Ok(ready) => {
                    connection.audit(call, true).await?;
                    Ok(StreamReadiness {
                        readable: ready.is_readable() || ready.is_read_closed(),
                        writable: ready.is_writable() || ready.is_write_closed(),
                    })
                }
                Err(failure) => {
                    connection.abort(failure.code);
                    connection.audit(call, false).await?;
                    Err(failure.uncertain(connection.observe().application_write_attempted))
                }
            }
        }))
    }
    fn inspect(&self) -> StreamObservation {
        self.connection.observe()
    }
    fn shutdown(
        &self,
        how: StreamShutdown,
    ) -> Result<BoxFuture<'static, Result<StreamObservation, StreamError>>, StreamError> {
        if how == StreamShutdown::Receive
            || (how == StreamShutdown::Send
                && self.connection.endpoint.transport
                    == latent_policy::capability::StreamTransport::HostTls)
        {
            return Err(error(StreamErrorCode::Unsupported));
        }
        let pending = self.connection.pending(1, None)?;
        let connection = Arc::clone(&self.connection);
        Ok(Box::pin(async move {
            let mut call = connection
                .authorize("shutdown", CapabilityCallCost::new(0))
                .await?;
            let current = connection
                .wait(&pending, call.deadline(), recheck_provider(&mut call))
                .await
                .and_then(|value| value.map_err(Into::into));
            if let Err(failure) = current {
                connection.abort(failure.code);
                connection.audit(call, false).await?;
                return Err(connection.terminal_error(failure));
            }
            if how == StreamShutdown::Both {
                connection.stop(None);
            } else {
                connection
                    .wait(&pending, call.deadline(), async {
                        loop {
                            recheck_provider(&mut call).await?;
                            if pending.socket.shutdown_send()?.is_some() {
                                break Ok::<_, StreamError>(());
                            }
                            pending
                                .socket
                                .writable()
                                .await
                                .map_err(|_| error(StreamErrorCode::IoFailed))?;
                        }
                    })
                    .await??;
                connection
                    .state
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .write_shut = true;
            }
            connection.audit(call, true).await?;
            drop(pending);
            Ok(connection.observe())
        }))
    }
    fn close(self: Box<Self>) -> BoxFuture<'static, Result<StreamObservation, StreamError>> {
        let connection = Arc::clone(&self.connection);
        connection.stop(None);
        drop(self);
        Box::pin(async move {
            let call = connection
                .authorize("close", CapabilityCallCost::new(0))
                .await?;
            loop {
                let changed = connection.changed.notified();
                tokio::pin!(changed);
                changed.as_mut().enable();
                if {
                    let usage = connection.usage()?;
                    usage.pending_operations == 0 && usage.connections == 0
                } {
                    break;
                }
                if tokio::time::timeout_at(connection.deadline.into(), changed)
                    .await
                    .is_err()
                {
                    return Err(error(StreamErrorCode::Uncertain)
                        .uncertain(connection.observe().application_write_attempted));
                }
            }
            let quarantined = connection
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .quarantined;
            if quarantined {
                connection.audit(call, false).await?;
                return Err(error(StreamErrorCode::Uncertain)
                    .uncertain(connection.observe().application_write_attempted));
            }
            connection.audit(call, true).await?;
            Ok(connection.observe())
        })
    }
}
impl Drop for Handle {
    fn drop(&mut self) {
        if !self
            .connection
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .closing
        {
            self.connection.abort(StreamErrorCode::Cancelled);
        }
    }
}
pub(crate) fn network_error(error: NetworkError) -> StreamError {
    crate::error(match error {
        NetworkError::InvalidConfiguration => StreamErrorCode::InvalidInput,
        NetworkError::PermissionDenied => StreamErrorCode::Denied,
        NetworkError::DnsFailed => StreamErrorCode::DnsFailed,
        NetworkError::DeadlineExceeded => StreamErrorCode::Timeout,
        NetworkError::ResourceExhausted => StreamErrorCode::Exhausted,
        NetworkError::Closed => StreamErrorCode::Revoked,
    })
}

// This observer exposes no socket or authority in normal/provider binaries.
#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
impl Connection {
    pub(crate) fn kernel_reference_identity(&self) -> [u64; 3] {
        use std::os::fd::AsRawFd;
        let mut state = self.state.lock().unwrap();
        let socket = state.socket.as_mut().unwrap().resource();
        let tcp = socket
            .stream
            .as_ref()
            .expect("live socket transport")
            .host_tcp()
            .expect("historical ordinary-socket identity only");
        let (local, peer) = (tcp.local_addr().unwrap(), tcp.peer_addr().unwrap());
        assert_eq!(local.ip(), std::net::Ipv4Addr::LOCALHOST);
        assert_eq!(peer.ip(), std::net::Ipv4Addr::LOCALHOST);
        let link = std::fs::read_link(format!("/proc/self/fd/{}", tcp.as_raw_fd())).unwrap();
        let inode = link
            .to_str()
            .unwrap()
            .strip_prefix("socket:[")
            .unwrap()
            .strip_suffix(']')
            .unwrap()
            .parse::<u64>()
            .unwrap();
        [u64::from(local.port()), u64::from(peer.port()), inode]
    }
}

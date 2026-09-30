//! Socket ownership is affine even when its readiness handle is shared. The
//! pool connection survives every pending Arc<TcpStream> and is never parked.
use crate::{error, provider::Inner, StreamError, StreamErrorCode, StreamResolution, StreamUsage};
use latent_capabilities::broker::{
    io::{IoCall, IoInputChunk, IoOutputChunk, IoTransfer, IoTransferOptions},
    network::{
        OutboundStream, StreamInterest, StreamObservation, StreamReadiness, StreamScope,
        StreamShutdown, StreamState, MAXIMUM_CHUNK_BYTES, STREAM_CAPABILITY,
    },
    pools::{PoolAdmission, PoolCall, PooledConnection, ProviderClient, ProviderMetadata},
    AuditProviderOutcome, CapabilityAuditDurability, CapabilityCallCost, CapabilityRequestDigest,
    CapabilityStreamBudget, ProviderCall,
};
use latent_core::{budget::HostMemoryReservation, BoxFuture, BudgetDimension};
use latent_network::{canonical, NetworkError};
use latent_policy::capability::{ResourceTarget, StreamEndpoint};
use std::{
    future::Future,
    io,
    net::{Shutdown, SocketAddr},
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
    stream: Arc<TcpStream>,
    _native: HostMemoryReservation,
    _metadata: ProviderMetadata,
}
struct Connecting {
    future: Pin<Box<dyn Future<Output = io::Result<TcpStream>> + Send>>,
    native: Option<HostMemoryReservation>,
    metadata: Option<ProviderMetadata>,
}
#[expect(
    clippy::struct_excessive_bools,
    reason = "independent EOF, half-close, cancellation, and observed-write facts"
)]
struct State {
    socket: Option<PooledConnection<Socket>>,
    pending: usize,
    busy: [bool; 3],
    closing: bool,
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
    scope: StreamScope,
    owner_memory: HostMemoryReservation,
    _owner_metadata: ProviderMetadata,
}
struct Handle {
    connection: Arc<Connection>,
}
/// Drop the last copied socket reference before releasing a pending-operation
/// count. `Connection::finish` takes the physical wrapper only after this edge.
struct Pending {
    socket: Arc<TcpStream>,
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
    let mut connection = Arc::new(Connection {
        state: Mutex::new(State {
            socket: Some(socket),
            pending: 0,
            busy: [false; 3],
            closing: false,
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
        _owner_metadata: owner_metadata,
    });
    // Move the confirmed owner reservation into the real Arc; it cannot be
    // refunded by a facade while a pending operation still retains the Arc.
    Arc::get_mut(&mut connection)
        .expect("new owner")
        .owner_memory
        .confirm();
    let mut registry = inner
        .connections
        .lock()
        .map_err(|_| error(StreamErrorCode::Exhausted))?;
    let slot = registry
        .iter_mut()
        .find(|slot| slot.strong_count() == 0)
        .ok_or_else(|| error(StreamErrorCode::Exhausted))?;
    *slot = Arc::downgrade(&connection);
    drop(registry);
    Ok(Box::new(Handle { connection }))
}

async fn create_socket(
    inner: &Inner,
    scope: &StreamScope,
    index: usize,
    client: &Arc<ProviderClient<Socket>>,
    call: &PoolCall,
    deadline: Instant,
) -> Result<(PooledConnection<Socket>, Instant), StreamError> {
    let destination = &inner.config.destinations[index];
    let reservation = client.reserve_connection_wait(call).await?;
    // DNS packet/socket state is prepaid temporarily and released only after
    // the resolver future (including a pending TCP fallback) is destroyed.
    let (address, valid_until) = match &destination.resolution {
        StreamResolution::Static { addresses } => (
            *addresses
                .first()
                .ok_or_else(|| error(StreamErrorCode::Denied))?,
            deadline,
        ),
        StreamResolution::Dns { .. } => {
            let _dns_memory = scope.reserve_host_memory(64 * 1024)?;
            let _dns_metadata = inner.pools.reserve_protocol_metadata(64 * 1024)?;
            let resolver = inner.resolvers[index]
                .as_ref()
                .ok_or_else(|| error(StreamErrorCode::DnsFailed))?;
            let answers = wait_current(
                call.io(),
                deadline,
                resolver.resolve_with_expiry(deadline.into()),
            )
            .await?
            .map_err(network_error)?;
            let first = answers
                .answers
                .iter()
                .next()
                .ok_or_else(|| error(StreamErrorCode::DnsFailed))?;
            (first, answers.valid_until.into_std())
        }
    };
    if Instant::now() >= valid_until || !destination.addresses.permits(address) {
        return Err(error(StreamErrorCode::Denied));
    }
    recheck_io(call.io(), deadline.min(valid_until)).await?;
    let metadata = inner.pools.reserve_protocol_metadata(96 * 1024)?;
    let mut native = scope.reserve_host_memory(96 * 1024)?;
    let socket = if address.is_ipv4() {
        TcpSocket::new_v4()
    } else {
        TcpSocket::new_v6()
    }
    .map_err(|_| error(StreamErrorCode::ConnectFailed))?;
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
    native.confirm();
    let peer = SocketAddr::new(address, destination.endpoint.port);
    let mut connecting = Connecting {
        future: Box::pin(socket.connect(peer)),
        native: Some(native),
        metadata: Some(metadata),
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
    let socket = Socket {
        stream: Arc::new(stream),
        _native: connecting.native.take().expect("socket memory"),
        _metadata: connecting.metadata.take().expect("socket metadata"),
    };
    Ok((reservation.connected(socket)?, valid_until))
}

impl Connection {
    pub(crate) fn maintenance_step(&self, now: Instant) {
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
                .stream,
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
    fn finish(&self, direction: usize) {
        let physical = {
            let mut state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.pending -= 1;
            state.busy[direction] = false;
            if state.closing && state.pending == 0 {
                state.socket.take()
            } else {
                None
            }
        };
        drop(physical);
        self.changed.notify_waiters();
    }
    pub(crate) fn abort(&self, reason: StreamErrorCode) {
        self.stop(Some(reason));
    }
    fn stop(&self, reason: Option<StreamErrorCode>) {
        let physical = {
            let mut state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.closing = true;
            if state.failure.is_none() {
                state.failure = reason;
            }
            if state.pending == 0 {
                state.socket.take()
            } else {
                None
            }
        };
        self.call.io().stop_handle().stop();
        drop(physical);
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
        let state = self
            .state
            .try_lock()
            .map_err(|_| error(StreamErrorCode::Exhausted))?;
        Ok(StreamUsage {
            owners: 1,
            connections: usize::from(state.socket.is_some()),
            pending_operations: state.pending,
            retained_chunks: self.transfer.outstanding_chunks(),
            accepted_write_bytes: state.accepted_write,
            delivered_read_bytes: state.delivered_read,
            retired: false,
        })
    }
    async fn authorize(
        &self,
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
                        pending
                            .socket
                            .readable()
                            .await
                            .map_err(|_| error(StreamErrorCode::IoFailed))?;
                        recheck_provider(&mut call).await?;
                        match pending.socket.try_read(buffer.spare_mut()?) {
                            Err(failure) if failure.kind() == io::ErrorKind::WouldBlock => {}
                            value => break value.map_err(|_| error(StreamErrorCode::IoFailed)),
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
            let result = connection
                .wait(&pending, call.deadline(), async {
                    loop {
                        pending
                            .socket
                            .writable()
                            .await
                            .map_err(|_| error(StreamErrorCode::IoFailed))?;
                        recheck_provider(&mut call).await?;
                        connection
                            .state
                            .lock()
                            .unwrap_or_else(std::sync::PoisonError::into_inner)
                            .attempted_write = true;
                        match pending.socket.try_write(input.as_ref()) {
                            Err(failure) if failure.kind() == io::ErrorKind::WouldBlock => {}
                            value => break value.map_err(|_| error(StreamErrorCode::IoFailed)),
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
        if how == StreamShutdown::Receive {
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
                socket2::SockRef::from(pending.socket.as_ref())
                    .shutdown(Shutdown::Write)
                    .map_err(|_| error(StreamErrorCode::IoFailed))?;
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
                if connection.usage()?.pending_operations == 0 {
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

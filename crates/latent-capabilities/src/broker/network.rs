//! Closed stream boundary. Descriptors cannot mint a session or destination grant.
use super::{io::IoOutputChunk, CapabilitySession};
use latent_core::{BoxFuture, PlatformError, PlatformErrorCode};
use latent_policy::capability::StreamEndpoint;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};

pub const STREAM_CAPABILITY: &str = "latent:network/streams@0.1.0";
pub const STREAM_PROFILE: &str = "lsf-outbound-streams-v1";
pub const MAXIMUM_CHUNK_BYTES: usize = 16 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StreamErrorCode {
    InvalidInput,
    InvalidState,
    Unsupported,
    Denied,
    Revoked,
    Exhausted,
    DnsFailed,
    TlsFailed,
    ConnectFailed,
    Timeout,
    Cancelled,
    IoFailed,
    Uncertain,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct StreamError {
    pub code: StreamErrorCode,
    pub accepted_prefix_bytes: u32,
    pub may_have_applied: bool,
}

impl StreamError {
    #[must_use]
    pub const fn new(code: StreamErrorCode) -> Self {
        Self {
            code,
            accepted_prefix_bytes: 0,
            may_have_applied: false,
        }
    }
    #[must_use]
    pub const fn uncertain(mut self, possible: bool) -> Self {
        self.may_have_applied |= possible;
        self
    }
}

impl From<PlatformError> for StreamError {
    fn from(value: PlatformError) -> Self {
        Self::new(match value.code {
            PlatformErrorCode::PermissionDenied | PlatformErrorCode::Unauthenticated => {
                StreamErrorCode::Denied
            }
            PlatformErrorCode::ResourceExhausted | PlatformErrorCode::AdmissionRejected => {
                StreamErrorCode::Exhausted
            }
            PlatformErrorCode::DeadlineExceeded => StreamErrorCode::Timeout,
            PlatformErrorCode::Cancelled => StreamErrorCode::Cancelled,
            PlatformErrorCode::InvalidArgument => StreamErrorCode::InvalidInput,
            _ => StreamErrorCode::IoFailed,
        })
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StreamState {
    Open,
    ReadEof,
    WriteShut,
    ReadEofWriteShut,
    Stopping,
    Closed,
    Failed,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StreamInterest {
    Readable,
    Writable,
    Either,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StreamShutdown {
    Send,
    Receive,
    Both,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct StreamReadiness {
    pub readable: bool,
    pub writable: bool,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct StreamObservation {
    pub state: StreamState,
    pub accepted_write_bytes: u64,
    pub delivered_read_bytes: u64,
    pub application_write_attempted: bool,
}
pub struct StreamConnectRequest {
    pub endpoint: StreamEndpoint,
    pub timeout_millis: Option<u32>,
}

pub type StreamInvocation = BoxFuture<'static, Result<Box<dyn OutboundStream>, StreamError>>;
pub trait OutboundStreamInvoker: Send + Sync {
    fn start(
        &self,
        session: &CapabilitySession,
        request: StreamConnectRequest,
    ) -> Result<StreamInvocation, StreamError>;
}

/// Each operation owns its future independently of a guest facade/Store borrow.
/// Drop requests local abort; actual pending owners keep all charges until gone.
pub trait OutboundStream: Send + Sync {
    fn read(
        &self,
        maximum: usize,
        timeout_millis: Option<u32>,
    ) -> Result<BoxFuture<'static, Result<Option<IoOutputChunk>, StreamError>>, StreamError>;
    fn write(
        &self,
        bytes: Vec<u8>,
        timeout_millis: Option<u32>,
    ) -> Result<BoxFuture<'static, Result<u32, StreamError>>, StreamError>;
    fn ready(
        &self,
        interest: StreamInterest,
        timeout_millis: Option<u32>,
    ) -> Result<BoxFuture<'static, Result<StreamReadiness, StreamError>>, StreamError>;
    fn inspect(&self) -> StreamObservation;
    fn shutdown(
        &self,
        how: StreamShutdown,
    ) -> Result<BoxFuture<'static, Result<StreamObservation, StreamError>>, StreamError>;
    fn close(self: Box<Self>) -> BoxFuture<'static, Result<StreamObservation, StreamError>>;
}

#[derive(Default)]
pub(super) struct NetworkUsage {
    connections: AtomicUsize,
    attempts: AtomicUsize,
    bytes: AtomicU64,
    chunks: AtomicUsize,
    resident_bytes: AtomicUsize,
}

pub struct StreamChunkReservation {
    table: super::SessionResourceTableReservation,
    bytes: usize,
}
impl Drop for StreamChunkReservation {
    fn drop(&mut self) {
        self.table.with_session(|session| {
            session
                .core
                .network
                .resident_bytes
                .fetch_sub(self.bytes, Ordering::AcqRel);
            session.core.network.chunks.fetch_sub(1, Ordering::AcqRel);
        });
    }
}

/// A lease on the original sealed activation, including queued connection
/// ownership. Keep this after physical socket and buffer fields in the owner.
pub struct StreamScope {
    table: super::SessionResourceTableReservation,
}
impl CapabilitySession {
    pub fn reserve_host_memory(
        &self,
        bytes: u64,
    ) -> Result<latent_core::budget::HostMemoryReservation, PlatformError> {
        self.check_liveness()?;
        self.core
            .budget
            .reserve_host_memory(bytes)
            .map_err(|error| error.to_platform_error())
    }
    pub fn reserve_stream(&self) -> Result<StreamScope, PlatformError> {
        self.check_liveness()?;
        let table = self.reserve_resource_table(17 * 1024)?;
        self.core
            .network
            .connections
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
                value.checked_add(1).filter(|next| *next <= 2)
            })
            .map_err(|_| super::capacity())?;
        Ok(StreamScope { table })
    }
}
impl StreamScope {
    /// Four resident payload owners, with at most 64 KiB including read copies,
    /// across all threads/connections/closed-but-retained chunks of this Store.
    pub fn reserve_chunk(&self, bytes: usize) -> Result<StreamChunkReservation, PlatformError> {
        if bytes == 0 || bytes > 2 * MAXIMUM_CHUNK_BYTES {
            return Err(super::capacity());
        }
        self.with_session(|session| {
            session.check_liveness()?;
            let table = session.reserve_resource_table(512)?;
            session
                .core
                .network
                .chunks
                .fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
                    value.checked_add(1).filter(|n| *n <= 4)
                })
                .map_err(|_| super::capacity())?;
            if session
                .core
                .network
                .resident_bytes
                .fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
                    value.checked_add(bytes).filter(|n| *n <= 64 * 1024)
                })
                .is_err()
            {
                session.core.network.chunks.fetch_sub(1, Ordering::AcqRel);
                return Err(super::capacity());
            }
            Ok(StreamChunkReservation { table, bytes })
        })
    }
    pub fn reserve_host_memory(
        &self,
        bytes: u64,
    ) -> Result<latent_core::budget::HostMemoryReservation, PlatformError> {
        self.with_session(|session| session.reserve_host_memory(bytes))
    }
    pub fn with_session<T>(&self, inspect: impl FnOnce(&CapabilitySession) -> T) -> T {
        self.table.with_session(inspect)
    }
    /// Call only after guarded acceptance, before DNS/connect. These cumulative
    /// counts never reset when a connection is closed or another thread starts.
    pub fn dispatched_connect(&self) -> Result<(), PlatformError> {
        self.with_session(|session| {
            session.check_liveness()?;
            session
                .core
                .network
                .attempts
                .fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
                    value.checked_add(1).filter(|next| *next <= 32)
                })
                .map_err(|_| super::capacity())?;
            Ok(())
        })
    }
    pub fn charge_transfer(&self, bytes: usize) -> Result<(), PlatformError> {
        self.with_session(|session| {
            session.check_liveness()?;
            session
                .core
                .network
                .bytes
                .fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
                    value
                        .checked_add(bytes as u64)
                        .filter(|next| *next <= 2 * 1024 * 1024)
                })
                .map_err(|_| super::capacity())?;
            Ok(())
        })
    }
}
impl Drop for StreamScope {
    fn drop(&mut self) {
        self.with_session(|session| {
            session
                .core
                .network
                .connections
                .fetch_sub(1, Ordering::AcqRel);
        });
    }
}

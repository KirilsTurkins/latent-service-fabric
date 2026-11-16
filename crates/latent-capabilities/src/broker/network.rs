//! Closed stream boundary. Descriptors cannot mint a session or destination grant.
use super::{
    io::{IoFuture, IoOutputChunk},
    CapabilitySession,
};
use latent_core::{PlatformError, PlatformErrorCode};
use latent_policy::capability::StreamEndpoint;
use std::{
    alloc::Layout,
    ops::Deref,
    sync::{
        atomic::{AtomicU32, AtomicU64, AtomicUsize, Ordering},
        Arc,
    },
};

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

pub type StreamInvocation = IoFuture<'static, Result<Box<dyn OutboundStream>, StreamError>>;

/// Finite instantaneous physical ownership observations for trusted node
/// operators. Live byte counts disappear only with their retained owners;
/// they are neither cumulative audit totals nor permission/readiness proofs.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct StreamNodeUsage {
    pub configuration_epoch: u64,
    pub retired_generations: usize,
    pub stopped: bool,
    pub owners: usize,
    pub connections: usize,
    /// Retained quarantines already included in owners and connections.
    /// `None` means this invoker cannot observe them, not a zero count.
    pub quarantined_connections: Option<usize>,
    pub pending_operations: usize,
    pub retained_chunks: usize,
    pub maintenance_owners: usize,
    pub live_accepted_write_bytes: u64,
    pub live_delivered_read_bytes: u64,
}

pub trait OutboundStreamInvoker: Send + Sync {
    fn start(
        &self,
        session: &CapabilitySession,
        request: StreamConnectRequest,
    ) -> Result<StreamInvocation, StreamError>;

    /// Implementations use bounded nonblocking reads of their actual owners.
    /// An unavailable observation must never be replaced by a zero count.
    fn inspect_node_usage(&self) -> Result<Option<StreamNodeUsage>, PlatformError> {
        Ok(None)
    }
}

/// Each operation owns its future independently of a guest facade/Store borrow.
/// Drop requests local abort; actual pending owners keep all charges until gone.
pub trait OutboundStream: Send + Sync {
    fn read(
        &self,
        maximum: usize,
        timeout_millis: Option<u32>,
    ) -> Result<IoFuture<'static, Result<Option<IoOutputChunk>, StreamError>>, StreamError>;
    fn write(
        &self,
        bytes: Vec<u8>,
        timeout_millis: Option<u32>,
    ) -> Result<IoFuture<'static, Result<u32, StreamError>>, StreamError>;
    /// Prepay the window and original native memory before invoking this
    /// synchronous producer. The resulting future owns only materialized bytes.
    fn write_from(
        &self,
        maximum: usize,
        timeout_millis: Option<u32>,
        produce: &mut dyn FnMut() -> Result<Vec<u8>, PlatformError>,
    ) -> Result<IoFuture<'static, Result<u32, StreamError>>, StreamError>;
    fn ready(
        &self,
        interest: StreamInterest,
        timeout_millis: Option<u32>,
    ) -> Result<IoFuture<'static, Result<StreamReadiness, StreamError>>, StreamError>;
    fn inspect(&self) -> StreamObservation;
    fn shutdown(
        &self,
        how: StreamShutdown,
    ) -> Result<IoFuture<'static, Result<StreamObservation, StreamError>>, StreamError>;
    fn close(self: Box<Self>) -> IoFuture<'static, Result<StreamObservation, StreamError>>;
}

#[derive(Default)]
pub(super) struct NetworkUsage {
    connections: AtomicUsize,
    attempts: AtomicUsize,
    bytes: AtomicU64,
    chunks: AtomicUsize,
    resident_bytes: AtomicUsize,
    scope_sequence: AtomicU32,
}

pub struct StreamChunkReservation {
    table: super::SessionResourceTableReservation,
    bytes: usize,
}
/// A stream chunk window paired with its exact originating connection scope.
#[doc(hidden)]
pub struct BoundStreamChunkReservation {
    scope_tag: u32,
    window: StreamChunkReservation,
}
impl BoundStreamChunkReservation {
    pub(in crate::broker) fn belongs_to(
        &self,
        scope_tag: u32,
        session: &CapabilitySession,
    ) -> bool {
        scope_tag != 0
            && self.scope_tag == scope_tag
            && self.window.table.with_session(|original| {
                super::session::Shared::ptr_eq(&original.core, &session.core)
            })
    }
    pub(in crate::broker) fn into_window(self) -> StreamChunkReservation {
        self.window
    }
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

// The Arc is private: exposing a raw Arc or Weak would let its allocation
// outlive the original scope and its separately prepaid backing reservation.
struct SharedStreamScopeBacking {
    scope: StreamScope,
    _allocation: latent_core::budget::HostMemoryReservation,
}

fn shared_scope_allocation_bytes() -> Result<u64, PlatformError> {
    // Pinned Rust's ArcInner uses two AtomicUsize headers followed by T.
    let layout = Layout::new::<[AtomicUsize; 2]>()
        .extend(Layout::new::<SharedStreamScopeBacking>())
        .map_err(|_| super::capacity())?
        .0
        .pad_to_align();
    u64::try_from(layout.size())
        .ok()
        .and_then(|size| size.checked_add(64))
        .ok_or_else(super::capacity)
}

/// Shares one original stream scope while keeping its allocation charged
/// until the final strong owner has physically retired its Arc backing.
pub struct SharedStreamScope {
    backing: Option<Arc<SharedStreamScopeBacking>>,
}

impl Clone for SharedStreamScope {
    fn clone(&self) -> Self {
        Self {
            backing: Some(Arc::clone(
                self.backing.as_ref().expect("live stream scope"),
            )),
        }
    }
}

impl Deref for SharedStreamScope {
    type Target = StreamScope;
    fn deref(&self) -> &StreamScope {
        &self.backing.as_ref().expect("live stream scope").scope
    }
}

impl Drop for SharedStreamScope {
    fn drop(&mut self) {
        if let Some(backing) = self.backing.take() {
            // The last value moves out after the Arc allocation is freed.
            // No weak reference can escape this private owner.
            drop(Arc::into_inner(backing));
        }
    }
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
        let mut table = self.reserve_resource_table(17 * 1024)?;
        // Never recycle an identity within the same SessionCore. Exhaustion
        // fails closed rather than making a stale scope equal a later scope.
        let previous = self
            .core
            .network
            .scope_sequence
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
                value.checked_add(1)
            })
            .map_err(|_| super::capacity())?;
        table.set_stream_scope_tag(previous + 1);
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
    /// Prepay the actual Arc backing before sharing this original scope.
    pub fn share(self) -> Result<SharedStreamScope, PlatformError> {
        let allocation = self.reserve_host_memory(shared_scope_allocation_bytes()?)?;
        let mut shared = SharedStreamScope {
            backing: Some(Arc::new(SharedStreamScopeBacking {
                scope: self,
                _allocation: allocation,
            })),
        };
        Arc::get_mut(shared.backing.as_mut().expect("live stream scope"))
            .expect("new stream scope is unique")
            ._allocation
            .confirm();
        Ok(shared)
    }
    pub(in crate::broker) fn identity_tag(&self) -> u32 {
        self.table.stream_scope_tag()
    }
    pub(in crate::broker) fn belongs_to(&self, session: &CapabilitySession) -> bool {
        self.table
            .with_session(|original| super::session::Shared::ptr_eq(&original.core, &session.core))
    }

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
    /// Bind a genuine chunk admission to this exact scope for output custody.
    #[doc(hidden)]
    pub fn reserve_bound_chunk(
        &self,
        bytes: usize,
    ) -> Result<BoundStreamChunkReservation, PlatformError> {
        Ok(BoundStreamChunkReservation {
            scope_tag: self.identity_tag(),
            window: self.reserve_chunk(bytes)?,
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::broker::{tests::fixture::Fixture, CapabilityBrokerLimits};
    #[test]
    fn shared_stream_scope_keeps_original_charge_until_last_clone() {
        use latent_core::{
            ActivationBudget, BudgetProfile, ClockSample, EffectiveActivationBudget,
        };
        let fixture = Fixture::new(CapabilityBrokerLimits::default());
        let (request, mut control) = fixture.request("shared-stream-scope");
        let deadline = control.budget.deadline();
        let sample = ClockSample::new(
            deadline.admitted_at_unix_millis(),
            deadline.admitted_at_monotonic(),
        );
        control.budget = ActivationBudget::with_profile(
            EffectiveActivationBudget::admit_profile_at(
                BudgetProfile::Phase3,
                &request.budget,
                &request.budget,
                &request.budget,
                request.activation.deadline_unix_millis,
                sample,
            )
            .unwrap(),
            BudgetProfile::Phase3,
        )
        .unwrap();
        let session = fixture.session(&request, &control);
        let baseline = control.budget.host_memory_bytes();
        let scope = session.reserve_stream().unwrap();
        let reserved = control.budget.host_memory_bytes();
        let shared = scope.share().unwrap();
        let allocation = shared_scope_allocation_bytes().unwrap();
        eprintln!("shared stream scope allocation: {allocation} bytes including bookkeeping");
        assert_eq!(control.budget.host_memory_bytes(), reserved + allocation);
        let clones: Vec<_> = (0..8).map(|_| shared.clone()).collect();
        drop(shared);
        assert_eq!(control.budget.host_memory_bytes(), reserved + allocation);
        std::thread::scope(|threads| {
            for owner in clones {
                threads.spawn(move || drop(owner));
            }
        });
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        assert_eq!(session.core.network.connections.load(Ordering::Acquire), 0);

        // A one-byte-short original budget must refuse before sharing and
        // return the unshared scope's connection/table reservation.
        let refused = session.reserve_stream().unwrap();
        let reserved = control.budget.host_memory_bytes();
        let padding = control
            .budget
            .reserve_host_memory(request.budget.memory_bytes - reserved - allocation + 1)
            .unwrap();
        assert!(refused.share().is_err());
        assert_eq!(session.core.network.connections.load(Ordering::Acquire), 0);
        assert_eq!(
            control.budget.host_memory_bytes(),
            baseline + padding.bytes()
        );
        drop(padding);
        assert_eq!(control.budget.host_memory_bytes(), baseline);
    }

    #[test]
    fn stream_scope_identity_exhaustion_never_wraps_or_leaks_admission() {
        let fixture = Fixture::new(CapabilityBrokerLimits::default());
        let (request, control) = fixture.request("stream-scope-sequence");
        let session = fixture.session(&request, &control);
        session
            .core
            .network
            .scope_sequence
            .store(u32::MAX - 1, Ordering::Release);
        let last = session.reserve_stream().unwrap();
        assert_eq!(last.identity_tag(), u32::MAX);
        let before = fixture.broker.snapshot();
        assert!(session.reserve_stream().is_err());
        assert_eq!(fixture.broker.snapshot(), before);
        drop(last);
        assert!(session.reserve_stream().is_err());
    }
}

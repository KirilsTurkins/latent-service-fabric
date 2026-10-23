#[cfg(all(test, unix))]
mod control_tests;
mod critical;
mod pending_views;
pub use pending_views::{AuditPendingAttemptView, AuditPendingAttempts};
#[cfg(test)]
mod node_memory_tests;
mod run;
use super::memory::{AuditArc, AuditCallMemory, AuditOwned, Heap};
use super::{
    capacity, closed, codec, error, invalid, store,
    store::Store,
    ticket::{self, Reply},
    unavailable, AuditAppendTicket, AuditBeginTicket, AuditCursor, AuditLimits, AuditObservation,
    AuditOperationAttempt, AuditOperationConclusion, AuditOperationResult, AuditPageCoverage,
    AuditQueryRequest, AuditQueryTicket, AuditReason, AuditRecordData, AuditSnapshot,
    AuditStoredRecord, DurableAuditAck, Result,
};
pub use critical::{AuditAttempt, AuditCriticalReservation};
use latent_core::node_metadata::{
    NodeMetadataArc as SharedOwner, NodeMetadataLease, NodeMetadataOwner, NodeMetadataPreparation,
    NodeMetadataReservation, NodeMetadataWeak as SharedWeak,
};
use std::{
    collections::VecDeque,
    path::Path,
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Condvar, Mutex,
    },
    thread::{self, JoinHandle},
    time::Instant,
};

/// Affine read-only acknowledgement. Its real Strings retire before the
/// original memory Part; no raw-owned extraction or duplicating Clone exists.
pub struct OwnedDurableAuditAck(AuditOwned<DurableAuditAck>);
impl std::ops::Deref for OwnedDurableAuditAck {
    type Target = DurableAuditAck;
    fn deref(&self) -> &DurableAuditAck {
        &self.0
    }
}
impl std::fmt::Debug for OwnedDurableAuditAck {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        std::fmt::Debug::fmt(&**self, f)
    }
}

#[cfg(test)]
use std::sync::Arc;
pub struct DirectoryPhase2AuditJournal;
#[derive(Clone)]
pub struct AuditHandle {
    shared: SharedOwner<Shared>,
}
pub struct AuditWorker {
    shared: SharedOwner<Shared>,
    thread: Option<JoinHandle<()>>,
    // Remains after actual JoinHandle retirement, not merely closure return.
    thread_memory: Option<NodeMetadataLease>,
}
struct Shared {
    limits: AuditLimits,
    state: Mutex<State>,
    wake: Condvar,
    pages: SharedOwner<PageBudget>,
    dropped: AtomicU64,
    unavailable: AtomicU64,
    finished: AtomicBool,
    quarantined_metadata: std::sync::atomic::AtomicUsize,
    metadata: Option<NodeMetadataOwner>,
}
struct State {
    #[cfg(any(test, feature = "test-support"))]
    waiting: bool,
    queue: VecDeque<Command>,
    queued_bytes: usize,
    reserved_records: usize,
    reserved_bytes: usize,
    summary: AuditSnapshot,
    closed: bool,
    pending: Option<AuditArc<Pending>>,
    finish: Option<Finish>,
    begin: Option<(AuditArc<Pending>, Reply<AuditAttempt>)>,
}
struct Pending {
    shared: SharedWeak<Shared>,
    attempt: AuditOperationAttempt,
    sequence: AtomicU64,
    started: AtomicBool,
    abandoned: AtomicBool,
    finishing: AtomicBool,
    memory: AuditCallMemory,
    recovered: bool,
    begun: AtomicBool,
}
struct Finish {
    pending: AuditArc<Pending>,
    conclusion: AuditOwned<AuditOperationConclusion>,
    reply: Reply<OwnedDurableAuditAck>,
}
#[expect(
    clippy::large_enum_variant,
    reason = "Each bounded queue entry is prepaid by its fixed 4096/16384-byte command charge, including this inline payload"
)]
enum Command {
    Observe(AuditOwned<AuditObservation>),
    Begin(AuditArc<Pending>, Reply<AuditAttempt>),
    Query(
        AuditOwned<AuditQueryRequest>,
        Instant,
        PageChargeLease,
        Option<NodeMetadataPreparation<PageData>>,
        Reply<AuditPage>,
    ),
}
impl Command {
    fn cost(&self) -> usize {
        match self {
            Self::Observe(_) | Self::Begin(..) => 16384,
            Self::Query(..) => 4096,
        }
    }
}
struct PageBudget {
    state: Mutex<(usize, usize)>,
    owners: usize,
    bytes: usize,
}
struct PageCharge {
    budget: SharedOwner<PageBudget>,
    bytes: usize,
    // This Vec's exact limit-sized backing is prepaid by the original4q page
    // allowance. Every additional record grant precedes its decoded copies.
    records: Mutex<Vec<NodeMetadataReservation>>,
    metadata: Option<NodeMetadataOwner>,
}
impl PageCharge {
    fn prepare_record(&self, bytes: &[u8], maximum: usize) -> Result<()> {
        let Some(owner) = &self.metadata else {
            return Ok(());
        };
        let heap = codec::owned_graph_bound(bytes, maximum)?;
        let bytes = heap.checked_add(std::mem::size_of::<AuditStoredRecord>())
            .and_then(|bytes| bytes.checked_add(4096))
            // Original graph, currently converted protobuf graph, and one
            // temporary cloning/conversion image may coexist. Encoded buffers
            // and the reservation Vec remain in the historical4q allowance.
            .and_then(|bytes| bytes.checked_mul(3)).ok_or_else(capacity)?;
        let mut records = self.records.lock().map_err(|_| unavailable())?;
        if records.len() == records.capacity() {
            return Err(capacity());
        }
        let original = owner.reserve(bytes).map_err(|_| capacity())?;
        records.push(original);
        Ok(())
    }
}
impl Drop for PageCharge {
    fn drop(&mut self) {
        let mut s = self
            .budget
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        s.0 -= 1;
        s.1 -= self.bytes;
    }
}
// Original page capacity stays with its real graph, not a separable raw Vec.
struct PageChargeLease(SharedOwner<PageCharge>);
struct PageData {
    records: Vec<AuditStoredRecord>,
    coverage: AuditPageCoverage,
    next: Option<AuditCursor>,
    metadata: Option<NodeMetadataOwner>,
    lease: PageChargeLease,
}
/// Read-only shared response ownership. Clones reuse original paid backing.
#[derive(Clone)]
pub struct AuditResponseLease(SharedOwner<PageData>);
impl AuditResponseLease {
    #[must_use]
    pub fn reserved_bytes(&self) -> usize {
        self.0.lease.0.bytes
    }
    /// Prepay one actual byte-owner Box before constructing an escaped frame.
    /// Retain this affine guard through that Box's real deallocation.
    pub fn reserve_frame_metadata(&self) -> Result<Option<NodeMetadataReservation>> {
        self.0
            .metadata
            .as_ref()
            .map(|owner| owner.reserve(256).map_err(|_| capacity()))
            .transpose()
    }
}
#[derive(Clone)]
pub struct AuditPage {
    data: SharedOwner<PageData>,
}
impl AuditPage {
    #[must_use]
    pub fn records(&self) -> &[AuditStoredRecord] {
        &self.data.records
    }
    #[must_use]
    pub fn coverage(&self) -> &AuditPageCoverage {
        &self.data.coverage
    }
    #[must_use]
    pub fn next_cursor(&self) -> Option<&AuditCursor> {
        self.data.next.as_ref()
    }
    /// Preserve the actual graph while a trusted adapter constructs/encodes its
    /// bounded response copies. There is no raw owned extraction from the page.
    #[must_use]
    pub fn response_lease(&self) -> AuditResponseLease {
        AuditResponseLease(self.data.clone())
    }
}
impl DirectoryPhase2AuditJournal {
    /// Blocking startup; unsupported filesystem profiles reject before mutation.
    pub fn open(path: impl AsRef<Path>, limits: AuditLimits) -> Result<(AuditHandle, AuditWorker)> {
        Self::open_inner(path.as_ref(), limits, None)
    }
    /// Funded standalone path: original node heap capacity is admitted before
    /// filesystem ownership, record reload, queue or shared-Arc allocation.
    pub fn open_with_node_metadata(
        path: impl AsRef<Path>,
        limits: AuditLimits,
        metadata: NodeMetadataOwner,
    ) -> Result<(AuditHandle, AuditWorker)> {
        let limits = limits.validate()?;
        if metadata.maximum_bytes() != limits.maximum_metadata_bytes {
            return Err(invalid());
        }
        Self::open_with_node_bank(path, limits, metadata)
    }
    /// Use the original whole-node bank without turning the journal's derived
    /// per-journal metadata policy into a new physical node allowance. The
    /// broker must independently bind this same bank and its exact ceiling.
    /// All fixed journal backing is still admitted before filesystem mutation.
    pub fn open_with_node_bank(
        path: impl AsRef<Path>,
        limits: AuditLimits,
        metadata: NodeMetadataOwner,
    ) -> Result<(AuditHandle, AuditWorker)> {
        Self::open_inner(path.as_ref(), limits, Some(metadata))
    }
    fn open_inner(
        path: &Path,
        limits: AuditLimits,
        metadata: Option<NodeMetadataOwner>,
    ) -> Result<(AuditHandle, AuditWorker)> {
        let limits = limits.validate()?;
        let prepared = metadata
            .as_ref()
            .map(|owner| {
                let extra = StoreMemory::bytes(limits)?;
                SharedOwner::<Shared>::prepare_fixed(owner, extra).map_err(|_| capacity())
            })
            .transpose()?;
        let lease = prepared
            .as_ref()
            .map_or_else(NodeMetadataLease::default, |p| p.lease());
        let store = Store::open_with_metadata(path, limits, lease, prepared.is_some())?;
        let limits = store.limits;
        let (records, bytes, next) = store.summary();
        let recovered_memory = if store.pending.is_some() {
            Some(if let Some(owner) = &metadata {
                AuditCallMemory::node(
                    owner,
                    AuditCallMemory::envelope_bytes(limits.maximum_record_bytes)?,
                )?
            } else {
                AuditCallMemory::default()
            })
        } else {
            None
        };
        let recovered_prepared = recovered_memory
            .as_ref()
            .map(|memory| {
                memory.prepare_arc::<Pending>(AuditCallMemory::owned_heap_bound(
                    limits.maximum_record_bytes,
                )?)
            })
            .transpose()?;
        let pending_record = store.pending.clone();
        if pending_record.is_some()
            && (records >= limits.maximum_records
                || bytes + limits.maximum_record_bytes > limits.maximum_disk_bytes)
        {
            return Err(capacity());
        }
        let pages = PageBudget {
            state: Mutex::new((0, 0)),
            owners: limits.maximum_query_owners,
            bytes: limits.maximum_total_page_bytes,
        };
        let pages = if let Some(owner) = &metadata {
            SharedOwner::prepare_fixed(owner, 0)
                .map_err(|_| capacity())?
                .allocate(pages)
        } else {
            SharedOwner::unaccounted(pages)
        };
        let value = Shared {
            limits,
            state: Mutex::new(State {
                #[cfg(any(test, feature = "test-support"))]
                waiting: false,
                queue: if prepared.is_some() {
                    VecDeque::with_capacity(limits.maximum_queued_operations)
                } else {
                    VecDeque::new()
                },
                queued_bytes: 0,
                reserved_records: usize::from(pending_record.is_some()),
                reserved_bytes: usize::from(pending_record.is_some()) * limits.maximum_record_bytes,
                summary: AuditSnapshot {
                    retained_records: records,
                    retained_bytes: bytes,
                    next_sequence: next,
                    unknown_outcomes: store.unknown,
                    previous_session_loss_unknown: store.previous_session_loss_unknown,
                    ..Default::default()
                },
                closed: false,
                pending: None,
                finish: None,
                begin: None,
            }),
            wake: Condvar::new(),
            pages,
            dropped: AtomicU64::new(0),
            unavailable: AtomicU64::new(0),
            finished: AtomicBool::new(false),
            quarantined_metadata: std::sync::atomic::AtomicUsize::new(0),
            metadata,
        };
        let shared = if let Some(prepared) = prepared {
            prepared.allocate(value)
        } else {
            SharedOwner::unaccounted(value)
        };
        if let Some(p) = pending_record {
            let heap = p.attempt.heap_bytes()?;
            shared.state.lock().map_err(|_| unavailable())?.pending =
                Some(recovered_prepared.expect("recovered admission").allocate(
                    Pending {
                        shared: shared.downgrade(),
                        attempt: p.attempt,
                        sequence: AtomicU64::new(p.sequence),
                        started: AtomicBool::new(true),
                        abandoned: AtomicBool::new(false),
                        finishing: AtomicBool::new(false),
                        memory: recovered_memory.expect("recovered memory"),
                        recovered: true,
                        begun: AtomicBool::new(true),
                    },
                    heap,
                ));
        }
        let thread_memory = shared.metadata.as_ref().map(|_| shared.lease());
        let owned = shared.clone();
        let thread = thread::Builder::new()
            .name("latent-audit".into())
            .spawn(move || {
                let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    run::run(owned.clone(), store);
                }));
                let mut s = owned
                    .state
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                let failed = result.is_err();
                s.closed = true;
                s.summary.recovery_pending |= failed;
                let queued = std::mem::take(&mut s.queue);
                let begin = s.begin.take();
                let finish = s.finish.take();
                owned.finished.store(true, Ordering::Release);
                drop(s);
                owned.wake.notify_all();
                drop(queued);
                drop(begin);
                drop(finish);
                if let Err(panic) = result {
                    std::panic::resume_unwind(panic);
                }
            })
            .map_err(|_| unavailable())?;
        Ok((
            AuditHandle {
                shared: shared.clone(),
            },
            AuditWorker {
                shared,
                thread: Some(thread),
                thread_memory,
            },
        ))
    }
}
impl Shared {
    // Only bounded control owners use this synchronization. State holders do
    // bounded memory work; the audit worker performs all journal I/O outside it.
    fn control_lock(&self) -> Result<std::sync::MutexGuard<'_, State>> {
        self.state.lock().map_err(|_| unavailable())
    }

    fn lock(&self) -> Result<std::sync::MutexGuard<'_, State>> {
        self.state.try_lock().map_err(|e| match e {
            std::sync::TryLockError::WouldBlock => error(
                latent_core::PlatformErrorCode::ResourceExhausted,
                "audit-busy",
            ),
            std::sync::TryLockError::Poisoned(_) => unavailable(),
        })
    }
    fn queue_room(&self, s: &State, cost: usize) -> Result<()> {
        if s.closed {
            return Err(closed());
        }
        if s.summary.recovery_pending {
            return Err(unavailable());
        }
        if s.queue.len()
            + usize::from(
                s.pending
                    .as_ref()
                    .is_some_and(|p| p.sequence.load(Ordering::Acquire) == 0),
            )
            >= self.limits.maximum_queued_operations
            || cost > self.limits.maximum_queued_bytes - s.queued_bytes
        {
            return Err(capacity());
        }
        Ok(())
    }
    fn record_room(&self, s: &State, count: usize) -> Result<()> {
        if count > self.limits.maximum_records - s.summary.retained_records - s.reserved_records
            || count * self.limits.maximum_record_bytes
                > self.limits.maximum_disk_bytes - s.summary.retained_bytes - s.reserved_bytes
        {
            return Err(capacity());
        }
        Ok(())
    }
}
impl AuditHandle {
    /// Observe an isolated test journal's actual idle worker before its next call.
    /// This does not reserve capacity or retry a rejected capability operation.
    #[cfg(any(test, feature = "test-support"))]
    pub fn wait_until_idle_for_test(&self, deadline: Instant) -> Result<bool> {
        let mut state = self.shared.control_lock()?;
        loop {
            if state.closed {
                return Err(closed());
            }
            if state.waiting
                && state.pending.is_none()
                && state.begin.is_none()
                && state.finish.is_none()
                && state.queue.is_empty()
                && state.reserved_records == 0
                && state.queued_bytes == 0
            {
                return Ok(true);
            }
            let Some(remaining) = deadline.checked_duration_since(Instant::now()) else {
                return Ok(false);
            };
            state = self
                .shared
                .wake
                .wait_timeout(state, remaining)
                .map_err(|_| unavailable())?
                .0;
        }
    }

    /// Checks composition identity without performing I/O or acquiring a grant.
    #[must_use]
    pub fn same_owner(&self, other: &Self) -> bool {
        SharedOwner::ptr_eq(&self.shared, &other.shared)
    }
    #[must_use]
    pub fn limits(&self) -> AuditLimits {
        self.shared.limits
    }
    /// Original opaque owner only; neither matching names nor matching limits
    /// can reconstruct the reservation or select an execution authority.
    #[must_use]
    pub fn node_metadata_owner(&self) -> Option<NodeMetadataOwner> {
        self.shared.metadata.clone()
    }
    pub fn prepare_call_memory(
        &self,
        budget: &latent_core::ActivationBudget,
    ) -> Result<AuditCallMemory> {
        AuditCallMemory::activation(
            budget,
            AuditCallMemory::envelope_bytes(self.shared.limits.maximum_record_bytes)?,
        )
    }
    fn control_memory(&self) -> Result<AuditCallMemory> {
        self.shared.metadata.as_ref().map_or_else(
            || Ok(AuditCallMemory::default()),
            |owner| {
                AuditCallMemory::node(
                    owner,
                    AuditCallMemory::envelope_bytes(self.shared.limits.maximum_record_bytes)?,
                )
            },
        )
    }
    pub fn try_capture(&self, event: &AuditObservation) -> Result<()> {
        let memory = match self.control_memory() {
            Ok(memory) => memory,
            Err(error) => {
                self.note_dropped_capture();
                return Err(error);
            }
        };
        self.try_capture_with_memory(event, &memory)
    }
    /// Record a failed before-copy diagnostic admission in the existing lossy
    /// capture counter. This does not reserve journal or execution capacity.
    pub fn note_dropped_capture(&self) {
        increment(&self.shared.dropped);
    }

    pub fn try_capture_with_memory(
        &self,
        event: &AuditObservation,
        memory: &AuditCallMemory,
    ) -> Result<()> {
        let result = (|| {
            let _scratch = memory.codec_scratch(self.shared.limits.maximum_record_bytes)?;
            codec::observation(event)?;
            let mut s = self.shared.lock()?;
            self.shared.queue_room(&s, 16384)?;
            self.shared.record_room(&s, 1)?;
            let part = memory.prepare_owned(AuditCallMemory::owned_heap_bound(
                self.shared.limits.maximum_record_bytes,
            )?)?;
            let event = codec::normalize(event, self.shared.limits.maximum_record_bytes)?;
            codec::envelope(
                &event.scope,
                &event.actor,
                AuditRecordData::Observation(event.clone()),
                self.shared.limits.maximum_record_bytes,
            )?;
            s.reserved_records += 1;
            s.reserved_bytes += self.shared.limits.maximum_record_bytes;
            s.queued_bytes += 16384;
            let heap = event.heap_bytes()?;
            s.queue
                .push_back(Command::Observe(AuditOwned::new(event, part, heap)));
            drop(s);
            self.shared.wake.notify_one();
            Ok(())
        })();
        if result.is_err() {
            increment(&self.shared.dropped);
        }
        result
    }
    #[expect(
        clippy::needless_pass_by_value,
        reason = "The public API consumes the request while replacing caller capacities with bounded owned copies"
    )]
    pub fn query(&self, query: AuditQueryRequest, deadline: Instant) -> Result<AuditQueryTicket> {
        codec::scope(&query.scope)?;
        if let Some(a) = &query.filter.actor {
            codec::token(a, 512)?;
        }
        if query.limit == 0
            || query.limit > self.shared.limits.maximum_query_events
            || query.maximum_bytes < 32768
            || query.maximum_bytes > self.shared.limits.maximum_page_bytes
            || query.cursor.as_ref().is_some_and(|c| c.0.len() > 256)
            || query
                .filter
                .from_unix_millis
                .zip(query.filter.to_unix_millis)
                .is_some_and(|(a, b)| a > b)
        {
            return Err(invalid());
        }
        if Instant::now() >= deadline {
            return Err(error(
                latent_core::PlatformErrorCode::DeadlineExceeded,
                "audit-query-deadline",
            ));
        }
        let mut s = self.shared.lock()?;
        self.shared.queue_room(&s, 4096)?;
        let bytes = query.maximum_bytes.checked_mul(4).ok_or_else(capacity)?;
        let mut pages = self.shared.pages.state.lock().map_err(|_| unavailable())?;
        if pages.0 == self.shared.pages.owners || bytes > self.shared.pages.bytes - pages.1 {
            return Err(capacity());
        }
        let prepared = self
            .shared
            .metadata
            .as_ref()
            .map(|owner| SharedOwner::<PageCharge>::prepare(owner, bytes).map_err(|_| capacity()))
            .transpose()?;
        let page_prepared = self
            .shared
            .metadata
            .as_ref()
            .map(|owner| SharedOwner::<PageData>::prepare(owner, 0).map_err(|_| capacity()))
            .transpose()?;
        pages.0 += 1;
        pages.1 += bytes;
        drop(pages);
        let charge = PageCharge {
            budget: self.shared.pages.clone(),
            bytes,
            records: Mutex::new(if self.shared.metadata.is_some() {
                Vec::with_capacity(query.limit)
            } else {
                Vec::new()
            }),
            metadata: self.shared.metadata.clone(),
        };
        let lease = PageChargeLease(if let Some(prepared) = prepared {
            prepared.allocate(charge)
        } else {
            SharedOwner::unaccounted(charge)
        });
        let memory = self.shared.metadata.as_ref().map_or_else(
            || Ok(AuditCallMemory::default()),
            |owner| AuditCallMemory::node(owner, 32768),
        )?;
        let input_part = memory.prepare_owned(16384)?;
        // Normalize every retained string, never retain caller spare capacities.
        let query = AuditQueryRequest {
            scope: codec::normalize(&query.scope, 4096)?,
            filter: codec::normalize(&query.filter, 4096)?,
            cursor: query
                .cursor
                .as_ref()
                .map(|c| AuditCursor(c.0.as_str().into())),
            ..query
        };
        let heap = query.heap_bytes()?;
        let query = AuditOwned::new(query, input_part, heap);
        let (reply, ticket) = ticket::channel(&memory)?;
        s.queued_bytes += 4096;
        s.queue
            .push_back(Command::Query(query, deadline, lease, page_prepared, reply));
        drop(s);
        self.shared.wake.notify_one();
        Ok(AuditQueryTicket(ticket))
    }
    /// Borrow the actual at-most-one pending record through an owning paid view.
    /// No independently allocated Vec or cloned record escapes this fence.
    pub fn pending_attempts(&self) -> Result<AuditPendingAttempts> {
        let s = self.shared.control_lock()?;
        Ok(AuditPendingAttempts::from_pending(s.pending.as_ref()))
    }
    pub fn note_unavailable(&self) {
        increment(&self.shared.unavailable);
    }
    pub fn snapshot(&self) -> AuditSnapshot {
        let s = self
            .shared
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let pages = self
            .shared
            .pages
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let node = self
            .shared
            .metadata
            .as_ref()
            .map(NodeMetadataOwner::snapshot);
        AuditSnapshot {
            node_metadata_maximum_bytes: node.map_or(0, |n| n.maximum_bytes),
            node_metadata_reserved_bytes: node.map_or(0, |n| n.reserved_bytes),
            node_metadata_fixed_reserved_bytes: node.map_or(0, |n| n.fixed_reserved_bytes),
            node_metadata_transient_reserved_bytes: node.map_or(0, |n| n.transient_reserved_bytes),
            node_metadata_quarantined_reserved_bytes: self
                .shared
                .quarantined_metadata
                .load(Ordering::Acquire),
            reserved_records: s.reserved_records,
            reserved_bytes: s.reserved_bytes,
            queued_operations: s.queue.len(),
            queued_bytes: s.queued_bytes,
            query_owners: pages.0,
            query_bytes: pages.1,
            pending_attempts: usize::from(s.pending.is_some()),
            closed: s.closed,
            dropped_observations: self.shared.dropped.load(Ordering::Relaxed),
            unavailable_events: self.shared.unavailable.load(Ordering::Relaxed),
            ..s.summary
        }
    }
    pub fn close(&self) {
        let mut s = self
            .shared
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        s.closed = true;
        drop(s);
        self.shared.wake.notify_all();
    }
}
impl AuditWorker {
    pub fn join_until(&mut self, deadline: Instant) -> Result<bool> {
        let mut s = self.shared.state.lock().map_err(|_| unavailable())?;
        s.closed = true;
        self.shared.wake.notify_all();
        while !self.shared.finished.load(Ordering::Acquire) {
            let Some(duration) = deadline.checked_duration_since(Instant::now()) else {
                return Ok(false);
            };
            s = self
                .shared
                .wake
                .wait_timeout(s, duration)
                .map_err(|_| unavailable())?
                .0;
        }
        drop(s);
        if let Some(thread) = self.thread.take() {
            thread.join().map_err(|_| unavailable())?;
        }
        Ok(true)
    }
}
impl Drop for AuditWorker {
    fn drop(&mut self) {
        let mut s = self
            .shared
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        s.closed = true;
        drop(s);
        self.shared.wake.notify_all();
        if let Some(thread) = self.thread.take() {
            if thread.is_finished() {
                // join retires the real JoinPacket owner before its lease. It
                // does not qualify libc/pthread's private cached OS stacks.
                let _ = thread.join();
            } else if let Some(memory) = self.thread_memory.take() {
                // No hidden reaper or replacement worker. Preserve both actual
                // owners and their original unavailable capacity until process
                // teardown when physical completion has not been established.
                self.shared
                    .quarantined_metadata
                    .store(memory.reserved_bytes(), Ordering::Release);
                std::mem::forget((thread, memory));
            }
            // Legacy unaccounted workers retain their original detach policy.
        }
    }
}
fn increment(counter: &AtomicU64) {
    let _ = counter.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |v| {
        Some(v.saturating_add(1))
    });
}

struct StoreMemory;
impl StoreMemory {
    fn bytes(limits: AuditLimits) -> Result<usize> {
        std::alloc::Layout::array::<Command>(limits.maximum_queued_operations)
            .map_err(|_| capacity())?
            .size()
            .checked_add(64)
            .and_then(|bytes| bytes.checked_add(super::store::native_memory_bytes(limits).ok()?))
            .ok_or_else(capacity)
    }
}

#[cfg(all(test, unix))]
mod node_bank_policy_tests;

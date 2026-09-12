mod critical;
mod run;
use super::{
    capacity, closed, codec, error, invalid, store,
    store::Store,
    ticket::{self, Reply},
    unavailable, AuditAppendTicket, AuditBeginTicket, AuditCursor, AuditLimits, AuditObservation,
    AuditOperationAttempt, AuditOperationConclusion, AuditOperationResult, AuditPageCoverage,
    AuditPendingAttempt, AuditQueryRequest, AuditQueryTicket, AuditReason, AuditRecordData,
    AuditSnapshot, AuditStoredRecord, DurableAuditAck, Result,
};
pub use critical::{AuditAttempt, AuditCriticalReservation};
use std::{
    collections::VecDeque,
    path::Path,
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Arc, Condvar, Mutex, Weak,
    },
    thread::{self, JoinHandle},
    time::Instant,
};

pub struct DirectoryPhase2AuditJournal;
#[derive(Clone)]
pub struct AuditHandle {
    shared: Arc<Shared>,
}
pub struct AuditWorker {
    shared: Arc<Shared>,
    thread: Option<JoinHandle<()>>,
}
struct Shared {
    limits: AuditLimits,
    state: Mutex<State>,
    wake: Condvar,
    pages: Arc<PageBudget>,
    dropped: AtomicU64,
    unavailable: AtomicU64,
    finished: AtomicBool,
}
struct State {
    queue: VecDeque<Command>,
    queued_bytes: usize,
    reserved_records: usize,
    reserved_bytes: usize,
    summary: AuditSnapshot,
    closed: bool,
    pending: Option<Arc<Pending>>,
    finish: Option<Finish>,
    begin: Option<(Arc<Pending>, Reply<AuditAttempt>)>,
}
struct Pending {
    shared: Weak<Shared>,
    attempt: AuditOperationAttempt,
    sequence: AtomicU64,
    started: AtomicBool,
    abandoned: AtomicBool,
    finishing: AtomicBool,
    recovered: bool,
    begun: AtomicBool,
}
struct Finish {
    pending: Arc<Pending>,
    conclusion: AuditOperationConclusion,
    reply: Reply<DurableAuditAck>,
}
enum Command {
    Observe(AuditObservation),
    Begin(Arc<Pending>, Reply<AuditAttempt>),
    Query(
        AuditQueryRequest,
        Instant,
        AuditResponseLease,
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
    budget: Arc<PageBudget>,
    bytes: usize,
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
/// Cloneable response ownership must remain alive through the encoded HTTP body.
#[derive(Clone)]
pub struct AuditResponseLease(Arc<PageCharge>);
impl AuditResponseLease {
    #[must_use]
    pub fn reserved_bytes(&self) -> usize {
        self.0.bytes
    }
}
pub struct AuditPage {
    records: Vec<AuditStoredRecord>,
    coverage: AuditPageCoverage,
    next: Option<AuditCursor>,
    lease: AuditResponseLease,
}
impl AuditPage {
    #[must_use]
    pub fn records(&self) -> &[AuditStoredRecord] {
        &self.records
    }
    #[must_use]
    pub fn coverage(&self) -> &AuditPageCoverage {
        &self.coverage
    }
    #[must_use]
    pub fn next_cursor(&self) -> Option<&AuditCursor> {
        self.next.as_ref()
    }
    #[must_use]
    pub fn into_parts(
        self,
    ) -> (
        Vec<AuditStoredRecord>,
        AuditPageCoverage,
        Option<AuditCursor>,
        AuditResponseLease,
    ) {
        (self.records, self.coverage, self.next, self.lease)
    }
}
impl DirectoryPhase2AuditJournal {
    /// Blocking startup; unsupported filesystem profiles reject before mutation.
    pub fn open(path: impl AsRef<Path>, limits: AuditLimits) -> Result<(AuditHandle, AuditWorker)> {
        let store = Store::open(path.as_ref(), limits)?;
        let limits = store.limits;
        let (records, bytes, next) = store.summary();
        let pending_record = store.pending.clone();
        if pending_record.is_some()
            && (records >= limits.maximum_records
                || bytes + limits.maximum_record_bytes > limits.maximum_disk_bytes)
        {
            return Err(capacity());
        }
        let shared = Arc::new(Shared {
            limits,
            state: Mutex::new(State {
                queue: VecDeque::new(),
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
            pages: Arc::new(PageBudget {
                state: Mutex::new((0, 0)),
                owners: limits.maximum_query_owners,
                bytes: limits.maximum_total_page_bytes,
            }),
            dropped: AtomicU64::new(0),
            unavailable: AtomicU64::new(0),
            finished: AtomicBool::new(false),
        });
        if let Some(p) = pending_record {
            shared.state.lock().map_err(|_| unavailable())?.pending = Some(Arc::new(Pending {
                shared: Arc::downgrade(&shared),
                attempt: p.attempt,
                sequence: AtomicU64::new(p.sequence),
                started: AtomicBool::new(true),
                abandoned: AtomicBool::new(false),
                finishing: AtomicBool::new(false),
                recovered: true,
                begun: AtomicBool::new(true),
            }));
        }
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
            },
        ))
    }
}
impl Shared {
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
    /// Checks composition identity without performing I/O or acquiring a grant.
    #[must_use]
    pub fn same_owner(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.shared, &other.shared)
    }
    #[must_use]
    pub fn limits(&self) -> AuditLimits {
        self.shared.limits
    }
    pub fn try_capture(&self, event: &AuditObservation) -> Result<()> {
        let result = (|| {
            codec::observation(event)?;
            let mut s = self.shared.lock()?;
            self.shared.queue_room(&s, 16384)?;
            self.shared.record_room(&s, 1)?;
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
            s.queue.push_back(Command::Observe(event));
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
        pages.0 += 1;
        pages.1 += bytes;
        drop(pages);
        let lease = AuditResponseLease(Arc::new(PageCharge {
            budget: self.shared.pages.clone(),
            bytes,
        }));
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
        let (reply, ticket) = ticket::channel();
        s.queued_bytes += 4096;
        s.queue
            .push_back(Command::Query(query, deadline, lease, reply));
        drop(s);
        self.shared.wake.notify_one();
        Ok(AuditQueryTicket(ticket))
    }
    pub fn pending_attempts(&self) -> Result<Vec<AuditPendingAttempt>> {
        let s = self.shared.lock()?;
        Ok(s.pending
            .as_ref()
            .filter(|p| p.sequence.load(Ordering::Acquire) > 0)
            .map(|p| AuditPendingAttempt {
                sequence: p.sequence.load(Ordering::Acquire),
                attempt: p.attempt.clone(),
            })
            .into_iter()
            .collect())
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
        AuditSnapshot {
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
    }
}
fn increment(counter: &AtomicU64) {
    let _ = counter.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |v| {
        Some(v.saturating_add(1))
    });
}

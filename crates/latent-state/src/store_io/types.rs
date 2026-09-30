use std::fmt;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StoreIoKind {
    Read,
    Write,
}

#[derive(Clone, Debug)]
pub struct StoreIoLimits {
    pub workers: usize,
    pub queued_jobs: usize,
    pub accepted_jobs: usize,
    pub active_reads: usize,
    pub active_writes: usize,
    pub retained_bytes: u64,
    pub job_bytes: u64,
}

impl StoreIoLimits {
    pub(super) fn validate(&self) -> Result<(), StoreIoError> {
        if [
            self.workers,
            self.queued_jobs,
            self.accepted_jobs,
            self.active_reads,
            self.active_writes,
        ]
        .contains(&0)
            || self.retained_bytes == 0
            || self.job_bytes == 0
            || self.workers > 32
            || self.queued_jobs > 4096
            || self.accepted_jobs > 8192
            || self.queued_jobs > self.accepted_jobs
            || self.retained_bytes > 1024 * 1024 * 1024
            || self.job_bytes > self.retained_bytes
            || self.active_reads > self.workers
            || self.active_writes > self.workers
        {
            return Err(StoreIoError::InvalidLimits);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StoreIoError {
    InvalidLimits,
    AdmissionClosed,
    QueueFull,
    AcceptedFull,
    ByteBudget,
    JobTooLarge,
    Exhausted,
    Poisoned,
    WorkerStartFailed,
    /// Callback panicked; this never establishes a technical abort.
    RecoveryRequired,
    InitializationFailed,
    /// Quarantined work was removed before any engine operation started.
    NotStarted,
    FinalizationFailed,
    DrainWaiterBusy,
    AlreadyDelivered,
}

pub struct StoreIoAdmissionError<F> {
    pub reason: StoreIoError,
    pub operation: F,
}

impl<F> fmt::Debug for StoreIoAdmissionError<F> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("StoreIoAdmissionError")
            .field("reason", &self.reason)
            .finish_non_exhaustive()
    }
}

/// Startup failure retains the store or its partial physical worker owner.
pub struct StoreIoStartError<S> {
    pub reason: StoreIoError,
    pub owner: Option<super::StoreIoOwner<S>>,
    pub store: Option<S>,
}

impl<S> fmt::Debug for StoreIoStartError<S> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("StoreIoStartError")
            .field("reason", &self.reason)
            .finish_non_exhaustive()
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum StoreIoEnginePhase {
    #[default]
    Owned,
    Finalizing,
    Closed,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct StoreIoSnapshot {
    pub queued: usize,
    pub active_reads: usize,
    pub active_writes: usize,
    pub accepted: usize,
    pub retained_bytes: u64,
    pub live_workers: usize,
    pub admission_closed: bool,
    pub engine_phase: StoreIoEnginePhase,
    pub quarantined: bool,
    pub failure: Option<StoreIoError>,
}

impl StoreIoSnapshot {
    #[must_use]
    pub fn physically_retired(self) -> bool {
        self.live_workers == 0 && self.engine_closed()
    }

    #[must_use]
    pub fn engine_closed(self) -> bool {
        self.engine_phase == StoreIoEnginePhase::Closed
    }

    #[must_use]
    pub fn finalizing(self) -> bool {
        self.engine_phase == StoreIoEnginePhase::Finalizing
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct StoreIoShutdown {
    pub clean: bool,
    pub snapshot: StoreIoSnapshot,
}

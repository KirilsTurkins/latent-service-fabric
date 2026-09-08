//! Finite preparation observations shared by synchronous and worker execution.

use serde::Serialize;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PreparationStage {
    RepositoryFetchVerified,
    MetadataValidation,
    ComponentNew,
    SurfaceLink,
    CacheAdoption,
    WholeJob,
    QueueWait,
}

impl PreparationStage {
    pub(super) const ALL: [Self; 7] = [
        Self::RepositoryFetchVerified,
        Self::MetadataValidation,
        Self::ComponentNew,
        Self::SurfaceLink,
        Self::CacheAdoption,
        Self::WholeJob,
        Self::QueueWait,
    ];

    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::RepositoryFetchVerified => "repository_fetch_verified",
            Self::MetadataValidation => "metadata_validation",
            Self::ComponentNew => "component_new",
            Self::SurfaceLink => "surface_link",
            Self::CacheAdoption => "cache_adoption",
            Self::WholeJob => "whole_job",
            Self::QueueWait => "queue_wait",
        }
    }

    pub(super) const fn index(self) -> usize {
        self as usize
    }
}

/// Linux task identity; a reused numerical TID is a different observation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct PreparationThreadIdentity {
    pub process_id: u32,
    pub thread_id: u32,
    pub start_time_ticks: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct PreparationThreadCpu {
    pub identity: PreparationThreadIdentity,
    pub user_ticks: u64,
    pub system_ticks: u64,
}

/// Both readings refer to the same task. Ticks are not nanoseconds.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct PreparationThreadCpuInterval {
    pub before: PreparationThreadCpu,
    pub after: PreparationThreadCpu,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RunningPreparation {
    pub job_id: u64,
    pub component_digest: Option<[u8; 32]>,
    pub stage: PreparationStage,
    pub started_nanos: u64,
    pub thread: Option<PreparationThreadIdentity>,
}

/// A bounded retained completed interval, including failures and unwinding.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PreparationStageObservation {
    pub sequence: u64,
    pub job_id: u64,
    pub component_digest: Option<[u8; 32]>,
    pub stage: PreparationStage,
    pub started_nanos: u64,
    pub finished_nanos: u64,
    pub succeeded: bool,
    pub thread_cpu: Option<PreparationThreadCpuInterval>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct PreparationStageTotals {
    pub stage: PreparationStage,
    pub started: u64,
    pub completed: u64,
    pub failed: u64,
    pub elapsed_nanos: u64,
    pub thread_cpu_samples: u64,
    pub thread_cpu_unavailable: u64,
    pub thread_cpu_user_ticks: u64,
    pub thread_cpu_system_ticks: u64,
}

impl PreparationStageTotals {
    pub(super) const fn new(stage: PreparationStage) -> Self {
        Self {
            stage,
            started: 0,
            completed: 0,
            failed: 0,
            elapsed_nanos: 0,
            thread_cpu_samples: 0,
            thread_cpu_unavailable: 0,
            thread_cpu_user_ticks: 0,
            thread_cpu_system_ticks: 0,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PreparationObserverSnapshot {
    pub enabled: bool,
    pub revision: u64,
    pub observed_nanos: u64,
    pub maximum_running_entries: usize,
    pub maximum_stage_observations: usize,
    pub active_jobs: u64,
    pub dropped_running_entries: u64,
    pub dropped_stage_observations: u64,
    /// None for the synchronous control; populated only by a compiler pool.
    pub compiler: Option<PreparationCompilerSnapshot>,
    pub stages: [PreparationStageTotals; 7],
    pub running: Vec<RunningPreparation>,
    pub recent_stages: Vec<PreparationStageObservation>,
}

/// Fixed optional compiler ownership schema, present in both comparison builds.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize)]
pub struct PreparationCompilerSnapshot {
    pub maximum_jobs: usize,
    pub maximum_workers: usize,
    pub maximum_queued_jobs: usize,
    pub maximum_waiters: usize,
    pub maximum_waiters_per_job: usize,
    pub maximum_ready_preparations: usize,
    pub maximum_document_bytes: usize,
    pub assigned_jobs: u64,
    pub running_jobs: u64,
    pub queued_jobs: u64,
    pub waiting_callers: u64,
    pub ready_preparations: u64,
    pub ready_metadata_bytes: u64,
    pub ready_compiled_image_bytes: u64,
    pub reserved_document_bytes: u64,
    pub workers_live: u64,
    pub workers_quiescent: u64,
    pub workers_joined: u64,
    pub accepting: bool,
    pub failed: bool,
    pub jobs_started: u64,
    pub jobs_completed: u64,
    pub jobs_failed: u64,
    pub jobs_abandoned: u64,
    pub coalesced_waiters: u64,
    pub queue_rejected: u64,
    pub waiter_rejected: u64,
    pub ready_rejected: u64,
    pub cancelled_waiters: u64,
    pub discarded_results: u64,
}

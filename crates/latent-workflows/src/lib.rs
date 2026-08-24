//! Durable workflow continuations, suspension points, timers, and compensation interfaces.

#![forbid(unsafe_code)]

use latent_core::{
    BoxFuture, ContinuationId, Metadata, PlatformError, VersionToken, WorkflowId,
    WorkflowInstanceId,
};
use latent_effects::EffectIntent;
use latent_state::StateMutation;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SuspensionPoint {
    Timer {
        wake_at_unix_millis: u64,
    },
    Event {
        topic: String,
        correlation_key: String,
    },
    Effect {
        effect_id: String,
    },
    ChildWorkflow {
        instance_id: WorkflowInstanceId,
    },
    Manual {
        reason: String,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkflowStatus {
    Pending,
    Running,
    Suspended,
    Completed,
    Failed,
    Compensating,
    Compensated,
    Cancelled,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Continuation {
    pub id: ContinuationId,
    pub workflow: WorkflowId,
    pub instance: WorkflowInstanceId,
    pub definition_digest: String,
    pub program_counter: String,
    pub locals: Vec<u8>,
    pub locals_media_type: String,
    pub suspension: SuspensionPoint,
    pub state_version: Option<VersionToken>,
    pub attempt: u32,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkflowTransition {
    pub status: WorkflowStatus,
    pub next_continuation: Option<Continuation>,
    pub state_mutations: Vec<StateMutation>,
    pub effects: Vec<EffectIntent>,
    pub output: Option<Vec<u8>>,
    pub output_media_type: Option<String>,
}

pub trait ContinuationStore: Send + Sync {
    fn put<'a>(&'a self, continuation: Continuation) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn get<'a>(
        &'a self,
        id: &'a ContinuationId,
    ) -> BoxFuture<'a, Result<Option<Continuation>, PlatformError>>;

    fn claim_ready<'a>(
        &'a self,
        worker: &'a str,
        now_unix_millis: u64,
        limit: u32,
    ) -> BoxFuture<'a, Result<Vec<Continuation>, PlatformError>>;

    fn delete<'a>(&'a self, id: &'a ContinuationId) -> BoxFuture<'a, Result<(), PlatformError>>;
}

pub trait WorkflowRuntime: Send + Sync {
    fn start<'a>(
        &'a self,
        workflow: &'a WorkflowId,
        input: Vec<u8>,
        media_type: &'a str,
    ) -> BoxFuture<'a, Result<WorkflowTransition, PlatformError>>;

    fn resume<'a>(
        &'a self,
        continuation: Continuation,
        signal: Vec<u8>,
        media_type: &'a str,
    ) -> BoxFuture<'a, Result<WorkflowTransition, PlatformError>>;

    fn cancel<'a>(
        &'a self,
        instance: &'a WorkflowInstanceId,
        reason: &'a str,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;
}

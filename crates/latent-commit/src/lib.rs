//! Atomic state-and-effect commit planning, coordination, and recovery interfaces.

#![forbid(unsafe_code)]

use latent_core::{ActivationId, BoxFuture, Metadata, PlatformError};
use latent_effects::{EffectIntent, EffectReceipt};
use latent_state::{CommitReceipt as StateCommitReceipt, StateTransaction};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivationCommitPlan {
    pub activation_id: ActivationId,
    pub state_transaction: Option<StateTransaction>,
    pub effects: Vec<EffectIntent>,
    pub output_digest: Option<String>,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivationCommitReceipt {
    pub activation_id: ActivationId,
    pub state: Option<StateCommitReceipt>,
    pub persisted_effects: Vec<String>,
    pub committed_at_unix_millis: u64,
    pub commit_token: String,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CommitStatus {
    Unknown,
    Preparing,
    Committed,
    Aborted,
    RecoveryRequired,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommitInspection {
    pub activation_id: ActivationId,
    pub status: CommitStatus,
    pub receipt: Option<ActivationCommitReceipt>,
    pub effect_receipts: Vec<EffectReceipt>,
    pub metadata: Metadata,
}

pub trait CommitCoordinator: Send + Sync {
    fn commit<'a>(
        &'a self,
        plan: ActivationCommitPlan,
    ) -> BoxFuture<'a, Result<ActivationCommitReceipt, PlatformError>>;

    fn abort<'a>(
        &'a self,
        plan: ActivationCommitPlan,
        reason: &'a str,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn inspect<'a>(
        &'a self,
        activation_id: &'a ActivationId,
    ) -> BoxFuture<'a, Result<CommitInspection, PlatformError>>;
}

pub trait AtomicStateEffectStore: Send + Sync {
    fn persist<'a>(
        &'a self,
        transaction: Option<StateTransaction>,
        effects: Vec<EffectIntent>,
    ) -> BoxFuture<'a, Result<ActivationCommitReceipt, PlatformError>>;
}

pub trait CommitRecovery: Send + Sync {
    fn recover<'a>(
        &'a self,
        activation_id: &'a ActivationId,
    ) -> BoxFuture<'a, Result<CommitInspection, PlatformError>>;
}

//! Durable external-effect intent, dispatch, receipt, and retry interfaces.

#![forbid(unsafe_code)]

use latent_core::{
    ActivationId, BoxFuture, CapabilityId, EffectId, IdempotencyKey, Metadata, Payload,
    PlatformError, ProviderId,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EffectMode {
    Deferred,
    Awaited,
    Volatile,
    Idempotent,
    Compensatable,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EffectStatus {
    Pending,
    Dispatching,
    Succeeded,
    FailedRetryable,
    FailedPermanent,
    Compensating,
    Compensated,
    DeadLettered,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EffectRetryPolicy {
    pub maximum_attempts: u32,
    pub initial_delay_millis: u64,
    pub maximum_delay_millis: u64,
    pub backoff_multiplier_milli: u32,
    pub retryable_codes: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EffectIntent {
    pub id: EffectId,
    pub activation_id: ActivationId,
    pub sequence: u32,
    pub capability: CapabilityId,
    pub provider: ProviderId,
    pub operation: String,
    pub mode: EffectMode,
    pub payload: Payload,
    pub payload_media_type: String,
    pub idempotency_key: IdempotencyKey,
    pub deadline_unix_millis: Option<u64>,
    pub retry: EffectRetryPolicy,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EffectReceipt {
    pub effect_id: EffectId,
    pub status: EffectStatus,
    pub attempt: u32,
    pub provider_receipt: Option<String>,
    pub output: Option<Payload>,
    pub output_media_type: Option<String>,
    pub occurred_at_unix_millis: u64,
    pub metadata: Metadata,
}

pub trait EffectStore: Send + Sync {
    fn append<'a>(&'a self, intents: Vec<EffectIntent>)
        -> BoxFuture<'a, Result<(), PlatformError>>;

    fn claim<'a>(
        &'a self,
        worker: &'a str,
        limit: u32,
    ) -> BoxFuture<'a, Result<Vec<EffectIntent>, PlatformError>>;

    fn record<'a>(&'a self, receipt: EffectReceipt) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn history<'a>(
        &'a self,
        effect_id: &'a EffectId,
    ) -> BoxFuture<'a, Result<Vec<EffectReceipt>, PlatformError>>;
}

pub trait EffectProvider: Send + Sync {
    fn provider_id(&self) -> &ProviderId;

    fn dispatch<'a>(
        &'a self,
        intent: &'a EffectIntent,
    ) -> BoxFuture<'a, Result<EffectReceipt, PlatformError>>;
}

pub trait EffectDispatcher: Send + Sync {
    fn dispatch<'a>(
        &'a self,
        intent: EffectIntent,
    ) -> BoxFuture<'a, Result<EffectReceipt, PlatformError>>;

    fn compensate<'a>(
        &'a self,
        original: &'a EffectIntent,
        compensation: EffectIntent,
    ) -> BoxFuture<'a, Result<EffectReceipt, PlatformError>>;
}

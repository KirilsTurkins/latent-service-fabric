//! Shared trigger registration, source adapters, cursors, and dispatch interfaces.

#![forbid(unsafe_code)]

use latent_activation::{ActivationEnvelope, ActivationOutcome};
use latent_core::{BoxFuture, Metadata, PlatformError, TriggerId};
use latent_manifest::{TriggerKind, TriggerManifest};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TriggerCursor {
    pub trigger_id: TriggerId,
    pub position: String,
    pub observed_at_unix_millis: u64,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TriggerEvent {
    pub trigger_id: TriggerId,
    pub event_id: String,
    pub payload: Vec<u8>,
    pub media_type: String,
    pub occurred_at_unix_millis: u64,
    pub idempotency_key: Option<String>,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TriggerDispatch {
    pub event: TriggerEvent,
    pub activation: ActivationEnvelope,
}

pub trait TriggerRegistry: Send + Sync {
    fn apply<'a>(
        &'a self,
        trigger: TriggerManifest,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn get<'a>(
        &'a self,
        id: &'a TriggerId,
    ) -> BoxFuture<'a, Result<Option<TriggerManifest>, PlatformError>>;

    fn list<'a>(
        &'a self,
        kind: Option<TriggerKind>,
    ) -> BoxFuture<'a, Result<Vec<TriggerManifest>, PlatformError>>;
}

pub trait TriggerSource: Send + Sync {
    fn kind(&self) -> TriggerKind;

    fn poll<'a>(
        &'a self,
        trigger: &'a TriggerManifest,
        cursor: Option<&'a TriggerCursor>,
        limit: u32,
    ) -> BoxFuture<'a, Result<Vec<(TriggerEvent, TriggerCursor)>, PlatformError>>;

    fn acknowledge<'a>(
        &'a self,
        trigger: &'a TriggerManifest,
        cursor: TriggerCursor,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;
}

pub trait TriggerDispatcher: Send + Sync {
    fn map<'a>(
        &'a self,
        trigger: &'a TriggerManifest,
        event: TriggerEvent,
    ) -> BoxFuture<'a, Result<TriggerDispatch, PlatformError>>;

    fn dispatch<'a>(
        &'a self,
        dispatch: TriggerDispatch,
    ) -> BoxFuture<'a, ActivationOutcome>;
}

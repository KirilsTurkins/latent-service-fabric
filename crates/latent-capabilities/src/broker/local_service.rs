//! Trusted node port for the concrete local service adapter. Only accepted
//! capability work enters it; a guest DTO cannot construct a `ProviderCall`.
use super::{PlatformError, ProviderCall};
use latent_activation::ActivationOutcome;
use latent_core::{BoxFuture, ChildBudgetOwner, IdempotencyKey, Metadata, Payload};
use latent_routing::InvocationTarget;

pub struct LocalServiceRequest {
    pub target: InvocationTarget,
    pub deadline_unix_millis: Option<u64>,
    pub priority: u8,
    pub idempotency_key: Option<IdempotencyKey>,
    pub metadata: Metadata,
    pub input: Payload,
    pub input_media_type: String,
}

/// The child ledger remains owned through actual cleanup and result transfer.
/// Adapters must retain `call` through canonical lowering before dropping the
/// child owner. Its already-reserved output capacity must cover the result.
pub struct LocalServiceCompletion {
    pub outcome: ActivationOutcome,
    pub call: ProviderCall,
    pub child: ChildBudgetOwner,
}
pub type LocalServiceInvocation = BoxFuture<'static, Result<LocalServiceCompletion, PlatformError>>;

pub trait LocalServiceInvoker: Send + Sync {
    /// Synchronously performs bounded child budget/quota/cell admission before
    /// the guest can resume. Work and cleanup then belong to the node, including
    /// when the returned receiver is dropped. No per-service executor is created.
    fn start(
        &self,
        call: ProviderCall,
        request: LocalServiceRequest,
    ) -> Result<LocalServiceInvocation, PlatformError>;
}

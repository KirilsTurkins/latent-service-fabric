//! One explicit transaction admission within the existing activation lifecycle.
use latent_activation::ActivationEnvelope;
use latent_core::{ActivationBudget, BoxFuture, PlatformError};
use latent_executor::transaction::TransactionHost;
use std::sync::Arc;

/// The trusted state runtime validates the selected companion/publication and
/// authenticated scope, reserves durable command capacity before guest work,
/// and retains the original physical owners. Implementations cannot replace
/// this activation's accepted source, budget or monotonic deadline.
pub trait TransactionActivationAdmission: Send + Sync {
    fn admit<'a>(
        &'a self,
        envelope: &'a ActivationEnvelope,
        budget: &'a ActivationBudget,
    ) -> BoxFuture<'a, Result<Arc<dyn TransactionHost>, PlatformError>>;
}

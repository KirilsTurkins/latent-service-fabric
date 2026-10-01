use super::super::StateTransactionHost;
use crate::activation_manager::{TransactionCompletion, TransactionCompletionHook};
use latent_activation::ActivationOutcome;
use latent_core::{ActivationTerminalState, BoxFuture};
use std::sync::Arc;

pub(super) struct QueryCompletion {
    host: Arc<StateTransactionHost>,
}
impl QueryCompletion {
    pub(super) fn new(host: Arc<StateTransactionHost>) -> Self {
        Self { host }
    }
}
impl TransactionCompletionHook for QueryCompletion {
    fn complete(&self, outcome: ActivationOutcome) -> BoxFuture<'_, TransactionCompletion> {
        Box::pin(async move {
            let consumption = match &outcome {
                ActivationOutcome::Succeeded(success) => success.consumption.clone(),
                ActivationOutcome::DeclaredError { consumption, .. }
                | ActivationOutcome::Failed { consumption, .. } => consumption.clone(),
            };
            let output = match &outcome {
                ActivationOutcome::Succeeded(success) => success.output.len(),
                ActivationOutcome::DeclaredError { error, .. } => error.payload.len(),
                ActivationOutcome::Failed { .. } => 0,
            };
            let permitted = if matches!(
                &outcome,
                ActivationOutcome::Succeeded(success)
                    if success.committed_state_version.is_some() || !success.effect_ids.is_empty()
            ) {
                Err(super::super::authorization::denied())
            } else if matches!(outcome, ActivationOutcome::Failed { .. }) {
                // An original technical failure is not a data delivery. Keep its
                // typed stage/reason while still retiring the physical view.
                Ok(())
            } else {
                self.host
                    .authority()
                    .authorize("query-info", 0, output, || Ok(()))
            };
            // No result, inbox, outbox or command row is created. The guest Store
            // is already destroyed, and retirement awaits the actual native view.
            let retired = self.host.retire().await;
            let outcome = match (permitted, retired) {
                (Ok(()), Ok(())) => outcome,
                (Err(error), _) => ActivationOutcome::Failed {
                    terminal_state: ActivationTerminalState::Rejected,
                    error,
                    consumption,
                },
                (_, Err(error)) => ActivationOutcome::Failed {
                    terminal_state: ActivationTerminalState::PlatformFailed,
                    error: super::failure(error),
                    consumption,
                },
            };
            TransactionCompletion::ordinary(outcome)
        })
    }
}

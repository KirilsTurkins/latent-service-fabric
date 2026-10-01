use super::super::StateTransactionHost;
use crate::activation_manager::{TransactionCompletion, TransactionCompletionHook};
use base64::Engine;
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
    fn complete(&self, mut outcome: ActivationOutcome) -> BoxFuture<'_, TransactionCompletion> {
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
            let mut permitted = if matches!(
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
            if permitted.is_ok() && !matches!(outcome, ActivationOutcome::Failed { .. }) {
                match self.host.view_identity.token(&self.host.scope) {
                    Ok(token) => {
                        let metadata = match &mut outcome {
                            ActivationOutcome::Succeeded(success) => &mut success.metadata,
                            ActivationOutcome::DeclaredError { error, .. } => &mut error.metadata,
                            ActivationOutcome::Failed { .. } => {
                                unreachable!("excluded technical failure")
                            }
                        };
                        if metadata.contains_key(super::VIEW_METADATA) {
                            permitted = Err(super::super::authorization::denied());
                        } else {
                            metadata.insert(
                                super::VIEW_METADATA.into(),
                                base64::engine::general_purpose::STANDARD.encode(token),
                            );
                        }
                    }
                    Err(_) => permitted = Err(super::super::authorization::denied()),
                }
            }
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
            if matches!(outcome, ActivationOutcome::Failed { .. }) {
                return TransactionCompletion::ordinary(outcome);
            }
            // Rebind only after actual guest/view retirement. The one protected
            // read checks namespace history; subsequent socket polls retain a
            // synchronous policy/lifecycle fence and open no additional view.
            match self.host.query_delivery_fence().await {
                Ok(fence) => TransactionCompletion::ordinary_authorized(outcome, fence),
                Err(error) => TransactionCompletion::ordinary(ActivationOutcome::Failed {
                    terminal_state: ActivationTerminalState::Rejected,
                    error,
                    consumption: match outcome {
                        ActivationOutcome::Succeeded(success) => success.consumption,
                        ActivationOutcome::DeclaredError { consumption, .. }
                        | ActivationOutcome::Failed { consumption, .. } => consumption,
                    },
                }),
            }
        })
    }
}

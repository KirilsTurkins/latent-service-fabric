use super::{NativeTransactionAdmission, TransactionAdmissionResult, TransactionCompletionResult};
use crate::activation_runner::{failure_for_platform_error, outcome_consumption};
use crate::transaction_runtime::{CommandCompletion, CommandCompletionDisposition};
use crate::TransactionCommitControl;
use latent_activation::{ActivationOutcome, ActivationSuccess};
use latent_commit::atomic::{AtomicError, Outcome};
use latent_core::{BudgetConsumption, DeclaredError, Metadata, PlatformErrorCode};
use latent_executor::transaction::TransactionHost;
use std::sync::Arc;

impl NativeTransactionAdmission {
    pub(super) async fn complete_native(
        &self,
        outcome: ActivationOutcome,
        control: TransactionCommitControl,
    ) -> ActivationOutcome {
        let consumption = outcome_consumption(&outcome);
        let admitted = match self.take_result() {
            Ok(Some(admitted)) => admitted,
            Ok(None) => return outcome,
            Err(_) => return unavailable(consumption),
        };
        let Ok(retained) = self.retained_capacity() else {
            return unavailable(consumption);
        };
        let (result, observation) = match admitted {
            TransactionAdmissionResult::Command { claim, host } => {
                let identity = claim.record().clone();
                let completion = CommandCompletion::new(
                    claim,
                    host.clone(),
                    self.owners.effects.clone(),
                    self.owners.time.clone(),
                    control,
                );
                let disposition = match completion {
                    Ok(completion) => completion.finish(outcome).await,
                    Err(_) => CommandCompletionDisposition::RecoveryRequired {
                        command: identity,
                        retained_native: Some(Arc::clone(&retained)),
                        cleanup_failure: host.retire().await.err(),
                    },
                };
                let observation = command_observation(&disposition, consumption);
                (
                    TransactionCompletionResult::Command(disposition),
                    observation,
                )
            }
            TransactionAdmissionResult::Query { host } => {
                let view = host.identity();
                let retired = host.retire().await.is_ok();
                // Recheck after actual native destruction; guest calls and
                // ledger spending stay closed throughout this completion.
                let current = control.matches(host.activation_id(), host.budget())
                    && control.is_current()
                    && host.authorization.authorize_query_completion().is_ok()
                    && retained.check_current().is_ok();
                let outcome = if current && retired {
                    outcome
                } else {
                    unavailable(consumption.clone())
                };
                let observation = bodyless_observation(&outcome);
                (
                    TransactionCompletionResult::Query {
                        outcome,
                        view,
                        retained: Arc::clone(&host.memory),
                        native: Arc::clone(&retained),
                    },
                    observation,
                )
            }
            TransactionAdmissionResult::Existing { command, retained } => (
                TransactionCompletionResult::Existing { command, retained },
                outcome,
            ),
            TransactionAdmissionResult::Pending(pending) => {
                let command = pending.record().clone();
                let proof = pending.retire_without_guest().map(Box::new);
                // This proof still needs a fresh authorized recovery writer to
                // persist Aborted. It is never exposed as a durable abort here.
                (
                    TransactionCompletionResult::PendingRetired {
                        command,
                        proof,
                        retained: Arc::clone(&retained),
                    },
                    outcome,
                )
            }
        };
        match self.completion.lock() {
            Ok(mut slot) if slot.is_none() => {
                *slot = Some(result);
                // The actual view/work and result now retain this same guard.
                // The admission shell adds no lifetime after physical completion.
                if let Ok(mut retention) = self.retention.lock() {
                    retention.take();
                }
                observation
            }
            _ => unavailable(outcome_consumption(&observation)),
        }
    }
}

fn command_observation(
    disposition: &CommandCompletionDisposition,
    consumption: BudgetConsumption,
) -> ActivationOutcome {
    match disposition {
        CommandCompletionDisposition::Durable { result, .. } => match result.outcome() {
            Outcome::Committed => empty_success(consumption),
            Outcome::Rejected => ActivationOutcome::DeclaredError {
                error: DeclaredError {
                    code: result.code().unwrap_or("rejected").into(),
                    message: String::new(),
                    payload: Vec::new(),
                    media_type: String::new(),
                    metadata: Metadata::new(),
                },
                consumption,
            },
            _ => unavailable(consumption),
        },
        CommandCompletionDisposition::Retired {
            reason: AtomicError::Conflict,
            ..
        } => failure_for_platform_error(
            super::error(
                PlatformErrorCode::StateConflict,
                "transaction-state-conflict",
            ),
            consumption,
        ),
        _ => unavailable(consumption),
    }
}

fn bodyless_observation(outcome: &ActivationOutcome) -> ActivationOutcome {
    let consumption = outcome_consumption(outcome);
    match outcome {
        ActivationOutcome::Succeeded(_) => empty_success(consumption),
        ActivationOutcome::DeclaredError { error, .. } => ActivationOutcome::DeclaredError {
            error: DeclaredError {
                code: error.code.clone(),
                message: String::new(),
                payload: Vec::new(),
                media_type: String::new(),
                metadata: Metadata::new(),
            },
            consumption,
        },
        ActivationOutcome::Failed {
            terminal_state,
            error,
            ..
        } => ActivationOutcome::Failed {
            terminal_state: *terminal_state,
            error: error.clone(),
            consumption,
        },
    }
}
fn empty_success(consumption: BudgetConsumption) -> ActivationOutcome {
    ActivationOutcome::Succeeded(ActivationSuccess {
        output: Vec::new(),
        output_media_type: String::new(),
        consumption,
        committed_state_version: None,
        effect_ids: Vec::new(),
        metadata: Metadata::new(),
    })
}
fn unavailable(consumption: BudgetConsumption) -> ActivationOutcome {
    failure_for_platform_error(
        super::error(
            PlatformErrorCode::Unavailable,
            "transaction-recovery-required",
        ),
        consumption,
    )
}

use super::{
    error, OwnedPhase4Response, PlatformError, PlatformErrorCode, TransactionInstallation,
};
use latent_activation::{ActivationOutcome, ActivationSuccess};
use latent_commit::atomic::{CommandRecord, DurableResult, Outcome, SourceIdentity};
use latent_core::{ActivationClock, ActivationTerminalState, BudgetConsumption, DeclaredError};
use latent_node::{
    transaction_runtime::{
        CommandCompletionDisposition as Disposition, OwnedTransactionCompletion,
        TransactionCompletionResult as Completion, TransactionResponseAuthority,
    },
    ActivationReceipt,
};
use latent_rpc::{invocation::v1 as i, phase4 as contract, transaction::v1 as t};

impl super::super::Phase4ResponseOwner for TransactionResponseAuthority {
    fn reserved_bytes(&self) -> usize {
        usize::try_from(self.reserved_response_bytes()).unwrap_or(0)
    }
    fn with_current(&self, publish: &mut dyn FnMut()) -> Result<(), PlatformError> {
        TransactionResponseAuthority::with_current(self, publish)
    }
}

pub(super) fn response(
    receipt: ActivationReceipt,
    owned: OwnedTransactionCompletion,
    installation: &TransactionInstallation,
    limits: &crate::invocation::InvocationLimits,
    clock: &dyn ActivationClock,
) -> Result<OwnedPhase4Response, PlatformError> {
    owned.authority.with_current(&mut || {})?;
    let current_consumption = consumption(&receipt.outcome);
    let response = match owned.result {
        Completion::Query { outcome, view, .. } => {
            let resolved = receipt
                .resolved_revision
                .as_ref()
                .ok_or_else(|| error(PlatformErrorCode::Unavailable))?;
            let original = installation.source_for_resolved(resolved)?;
            let tenant = resolved.target.tenant.0.clone();
            contract::Response::from(t::QueryResponse {
                invocation: Some(crate::invocation::transaction_invocation_response(
                    receipt, outcome, limits,
                )),
                view: Some(t::ViewIdentity {
                    namespace: Some(t::NamespaceSelector {
                        tenant,
                        namespace: view.namespace,
                        incarnation: view.incarnation,
                    }),
                    version: view.version,
                    state_schema: view.state_schema,
                }),
                source: Some(source(&original)),
                observed_at_unix_millis: clock.sample().unix_millis(),
            })
        }
        Completion::Command(disposition) => command_response(receipt, disposition, limits)?,
        Completion::Existing {
            command, result, ..
        } => {
            let result = result.as_ref().ok().and_then(Option::as_ref);
            let outcome = match result {
                Some(result) => result_outcome(&command, result, current_consumption)?,
                None => failure(current_consumption),
            };
            let inspection = inspection(&command, result.map(AsRef::as_ref), None);
            let invocation = command_invocation(receipt, outcome, limits, command.source());
            contract::Response::from(t::InvokeCommandResponse {
                invocation: Some(invocation),
                command: Some(inspection),
                replayed: true,
            })
        }
        Completion::PendingRetired { command, .. } => {
            let mut inspection = inspection(&command, None, None);
            inspection.outcome = t::CommandOutcome::RecoveryRequired as i32;
            let invocation = crate::invocation::transaction_invocation_response(
                receipt,
                failure(current_consumption),
                limits,
            );
            contract::Response::from(t::InvokeCommandResponse {
                invocation: Some(invocation),
                command: Some(inspection),
                replayed: false,
            })
        }
    };
    let needed = response
        .encoded_len()
        .checked_mul(4)
        .and_then(|n| n.checked_add(16 * 1024))
        .ok_or_else(|| error(PlatformErrorCode::ResourceExhausted))?;
    if needed > usize::try_from(owned.authority.reserved_response_bytes()).unwrap_or(0) {
        return Err(error(PlatformErrorCode::ResourceExhausted));
    }
    owned.authority.with_current(&mut || {})?;
    Ok(OwnedPhase4Response::new(response, owned.authority))
}

fn command_response(
    receipt: ActivationReceipt,
    disposition: Disposition,
    limits: &crate::invocation::InvocationLimits,
) -> Result<contract::Response, PlatformError> {
    let consumption = consumption(&receipt.outcome);
    let (inspection, outcome, original) = match disposition {
        Disposition::Durable {
            command,
            result,
            cleanup_failure,
            ..
        } => {
            let outcome = result_outcome(&command, &result, consumption)?;
            let cleanup = cleanup_failure.map(|_| i::PlatformError {
                code: "unavailable".into(),
                message: "transaction cleanup unavailable".into(),
                retryable: false,
                ..Default::default()
            });
            (
                inspection(&command, Some(&result), cleanup),
                outcome,
                command.source().clone(),
            )
        }
        Disposition::Retired { command, .. } | Disposition::RecoveryRequired { command, .. } => {
            let mut inspected = inspection(&command, None, None);
            inspected.outcome = t::CommandOutcome::RecoveryRequired as i32;
            (inspected, failure(consumption), command.source().clone())
        }
    };
    Ok(contract::Response::from(t::InvokeCommandResponse {
        invocation: Some(command_invocation(receipt, outcome, limits, &original)),
        command: Some(inspection),
        replayed: false,
    }))
}

fn command_invocation(
    receipt: ActivationReceipt,
    outcome: ActivationOutcome,
    limits: &crate::invocation::InvocationLimits,
    original: &SourceIdentity,
) -> i::InvokeResponse {
    let mut response = crate::invocation::transaction_invocation_response(receipt, outcome, limits);
    // Historical data source in this public replay projection is independent of
    // the current activation journal/source pin. It grants no new execution.
    response.revision_id.clone_from(&original.revision);
    response
        .release_digest
        .clone_from(&original.component_digest);
    response.route_generation = original.route_generation;
    response.publication_id = Some(original.publication.clone());
    response
}

fn result_outcome(
    command: &CommandRecord,
    result: &DurableResult,
    consumption: BudgetConsumption,
) -> Result<ActivationOutcome, PlatformError> {
    let Some(value) = result.value() else {
        return Ok(failure(consumption));
    };
    Ok(match result.outcome() {
        Outcome::Committed => ActivationOutcome::Succeeded(ActivationSuccess {
            output: value.bytes.clone(),
            output_media_type: value.media_type.clone(),
            metadata: value.metadata.iter().cloned().collect(),
            consumption,
            committed_state_version: Some(hex(result.committed_view_token())),
            effect_ids: command.effect_ids().iter().map(|id| id.hex()).collect(),
        }),
        Outcome::Rejected => ActivationOutcome::DeclaredError {
            error: DeclaredError {
                code: result
                    .code()
                    .ok_or_else(|| error(PlatformErrorCode::Internal))?
                    .into(),
                message: String::new(),
                payload: value.bytes.clone(),
                media_type: value.media_type.clone(),
                metadata: value.metadata.iter().cloned().collect(),
            },
            consumption,
        },
        _ => failure(consumption),
    })
}

pub(super) fn source(value: &SourceIdentity) -> t::SourceIdentity {
    t::SourceIdentity {
        publication_id: value.publication.clone(),
        revision_id: value.revision.clone(),
        release_digest: value.release_digest.clone(),
        component_digest: value.component_digest.clone(),
        route_generation: value.route_generation,
        contract_digest: value.contract_digest.clone(),
        state_schema: value.state_schema.clone(),
        input_format: value.input_format.clone(),
        result_format: value.result_format.clone(),
    }
}
fn inspection(
    record: &CommandRecord,
    result: Option<&DurableResult>,
    cleanup_failure: Option<i::PlatformError>,
) -> t::CommandInspection {
    let available = result.is_some_and(|result| result.value().is_some());
    let source = source(record.source());
    let committed = record.outcome() == Outcome::Committed;
    let retained_result = result.and_then(|result| {
        let value = result.value()?;
        match result.outcome() {
            Outcome::Committed => {
                Some(t::command_inspection::RetainedResult::Success(i::Success {
                    payload: value.bytes.clone(),
                    media_type: value.media_type.clone(),
                    metadata: value.metadata.iter().cloned().collect(),
                    committed_state_version: Some(hex(result.committed_view_token())),
                    effect_ids: record.effect_ids().iter().map(|id| id.hex()).collect(),
                }))
            }
            Outcome::Rejected => Some(t::command_inspection::RetainedResult::BusinessRejection(
                i::DeclaredError {
                    code: result.code()?.into(),
                    message: String::new(),
                    payload: value.bytes.clone(),
                    media_type: value.media_type.clone(),
                    metadata: value.metadata.iter().cloned().collect(),
                },
            )),
            _ => None,
        }
    });
    t::CommandInspection {
        key: Some(t::CommandKey {
            namespace: Some(t::NamespaceSelector {
                tenant: record.key().tenant.clone(),
                namespace: record.key().namespace.clone(),
                incarnation: record.key().incarnation.clone(),
            }),
            recovery_scope: record.key().recovery_scope.clone(),
            operation: record.key().operation.clone(),
            entity: record.key().entity.clone(),
            client_key: record.key().client_key.clone(),
        }),
        command_id: record.id().hex(),
        attempt_id: record.attempt().to_string(),
        fingerprint_sha256: record.fingerprint().bytes().to_vec(),
        outcome: match record.outcome() {
            Outcome::Pending => t::CommandOutcome::InProgress,
            Outcome::Committed => t::CommandOutcome::Committed,
            Outcome::Rejected => t::CommandOutcome::Rejected,
            Outcome::Aborted => t::CommandOutcome::RecoveryRequired,
        } as i32,
        metadata_durable: matches!(
            record.outcome(),
            Outcome::Committed | Outcome::Rejected | Outcome::Aborted
        ),
        application_state_committed: committed,
        source: Some(source.clone()),
        retained_result,
        commit: committed.then(|| t::CommitReceipt {
            command_id: record.id().hex(),
            attempt_id: record.attempt().to_string(),
            transaction_id: record.transaction_id().hex(),
            committed_version: record.committed_view_token().unwrap_or_default().to_vec(),
            committed_at_unix_millis: record.completed_at(),
            effect_ids: record.effect_ids().iter().map(|id| id.hex()).collect(),
            receipt_id: record.disposition_id().hex(),
            source: Some(source),
        }),
        proven_abort: None,
        retention: Some(t::LinkedRetention {
            record_format: "lsf-command-v3".into(),
            record_version: 3,
            payload_expires_at_unix_millis: Some(record.result_expires()),
            identity_expires_at_unix_millis: Some(record.identity_expires()),
            remaining_recovery_millis: None,
            required_record_ids: vec![
                record.id().hex(),
                record.attempt_id().hex(),
                record.transaction_id().hex(),
            ],
            payload_available: available,
        }),
        cleanup_failure,
    }
}
fn consumption(outcome: &ActivationOutcome) -> BudgetConsumption {
    match outcome {
        ActivationOutcome::Succeeded(success) => success.consumption.clone(),
        ActivationOutcome::DeclaredError { consumption, .. }
        | ActivationOutcome::Failed { consumption, .. } => consumption.clone(),
    }
}
fn failure(consumption: BudgetConsumption) -> ActivationOutcome {
    ActivationOutcome::Failed {
        terminal_state: ActivationTerminalState::PlatformFailed,
        error: error(PlatformErrorCode::Unavailable),
        consumption,
    }
}
fn hex(bytes: &[u8]) -> String {
    use std::fmt::Write;
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        write!(output, "{byte:02x}").expect("String formatting");
    }
    output
}

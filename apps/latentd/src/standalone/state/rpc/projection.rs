use super::{denied, unavailable, OwnedPhase4Response, PlatformError};
use crate::standalone::state::InstalledTransactionOperation;
use base64::{engine::general_purpose::STANDARD, Engine};
use latent_commit::atomic::{CommandRecord, Outcome};
use latent_core::ActivationClock;
use latent_node::{
    transaction_runtime::command_completion::{CommandObservation, ResultDeliveryFence},
    ActivationReceipt,
};
use latent_wire::{
    invocation::{proto as i, InvocationLimits},
    phase4::{contract, transaction as t, Phase4ResponseOwner},
};
use std::sync::Arc;

struct Owner {
    fence: Arc<ResultDeliveryFence>,
    bytes: usize,
}
impl Phase4ResponseOwner for Owner {
    fn reserved_bytes(&self) -> usize {
        usize::try_from(self.fence.reserved_response_bytes()).unwrap_or(0)
    }
    fn with_current(&self, publish: &mut dyn FnMut()) -> Result<(), PlatformError> {
        self.fence.with_current(self.bytes, || {
            publish();
            Ok(())
        })
    }
}
pub(super) fn response(
    receipt: ActivationReceipt,
    installed: &InstalledTransactionOperation,
    query: bool,
    command: Option<&t::CommandSelector>,
    limits: &InvocationLimits,
    clock: &dyn ActivationClock,
) -> Result<OwnedPhase4Response, PlatformError> {
    // Query outcomes also use the original finite response reservation. Check
    // before typed projection clones any owned payload or metadata.
    if query {
        super::bounded_result(&receipt.outcome)?;
    }
    let fence = receipt
        .result_delivery_fence
        .as_ref()
        .ok_or_else(unavailable)?
        .clone();
    let response = if query {
        query_response(receipt, installed, limits, clock)?
    } else {
        command_response(receipt, command.ok_or_else(denied)?, limits)?
    };
    let bytes = response
        .encoded_len()
        .checked_mul(4)
        .and_then(|n| n.checked_add(16384))
        .ok_or_else(unavailable)?;
    if bytes > usize::try_from(fence.reserved_response_bytes()).unwrap_or(0) {
        return Err(unavailable());
    }
    fence.with_current(bytes, || Ok(()))?;
    Ok(OwnedPhase4Response::new(
        response,
        Arc::new(Owner { fence, bytes }),
    ))
}
fn query_response(
    receipt: ActivationReceipt,
    installed: &InstalledTransactionOperation,
    limits: &InvocationLimits,
    clock: &dyn ActivationClock,
) -> Result<contract::Response, PlatformError> {
    let resolved = receipt.resolved_revision.as_ref().ok_or_else(unavailable)?;
    let source = t::SourceIdentity {
        publication_id: installed.publication().publication().to_string(),
        revision_id: resolved.revision.0.clone(),
        release_digest: resolved.release.0.clone(),
        component_digest: installed.component_digest.clone(),
        route_generation: resolved.route_generation.0,
        contract_digest: installed.contract_digest.clone(),
        state_schema: installed.state_schema().into(),
        input_format: "lsf-wit-values-v1".into(),
        result_format: "lsf-wit-values-v1".into(),
    };
    let metadata = match &receipt.outcome {
        latent_activation::ActivationOutcome::Succeeded(v) => &v.metadata,
        latent_activation::ActivationOutcome::DeclaredError { error, .. } => &error.metadata,
        latent_activation::ActivationOutcome::Failed { .. } => return Err(unavailable()),
    };
    let token = metadata
        .get(latent_node::transaction_runtime::query::VIEW_METADATA)
        .ok_or_else(unavailable)?;
    let version = STANDARD.decode(token).map_err(|_| unavailable())?;
    if version.len() != latent_state::session::version::VIEW_TOKEN_BYTES
        || STANDARD.encode(&version) != *token
    {
        return Err(unavailable());
    }
    let view = t::ViewIdentity {
        namespace: Some(t::NamespaceSelector {
            tenant: resolved.target.tenant.0.clone(),
            namespace: installed.namespace().into(),
            incarnation: installed.incarnation().to_string(),
        }),
        version,
        state_schema: installed.state_schema().into(),
    };
    let mut receipt = receipt;
    match &mut receipt.outcome {
        latent_activation::ActivationOutcome::Succeeded(v) => {
            v.metadata
                .remove(latent_node::transaction_runtime::query::VIEW_METADATA);
        }
        latent_activation::ActivationOutcome::DeclaredError { error, .. } => {
            error
                .metadata
                .remove(latent_node::transaction_runtime::query::VIEW_METADATA);
        }
        latent_activation::ActivationOutcome::Failed { .. } => {}
    }
    Ok(contract::Response::from(t::QueryResponse {
        invocation: Some(latent_wire::invocation::transaction_invocation_response(
            receipt, limits,
        )),
        view: Some(view),
        source: Some(source),
        observed_at_unix_millis: clock.sample().unix_millis(),
    }))
}
fn command_response(
    receipt: ActivationReceipt,
    command: &t::CommandSelector,
    limits: &InvocationLimits,
) -> Result<contract::Response, PlatformError> {
    let disposition = receipt.transaction.as_ref().ok_or_else(unavailable)?;
    if !disposition.read_authorized() {
        return Err(denied());
    }
    let record = disposition.original_command();
    let replayed = disposition.recovered_result();
    let inspected = inspection(record, disposition.observation(), command, &receipt, limits)?;
    let original = record.source().clone();
    let mut invocation = latent_wire::invocation::transaction_invocation_response(receipt, limits);
    invocation.publication_id = Some(original.publication);
    invocation.revision_id = original.revision;
    invocation.release_digest = original.component_digest;
    invocation.route_generation = original.route_generation;
    Ok(contract::Response::from(t::InvokeCommandResponse {
        invocation: Some(invocation),
        command: Some(inspected),
        replayed,
    }))
}
fn source(record: &CommandRecord) -> t::SourceIdentity {
    let value = record.source();
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
pub(super) fn inspection(
    record: &CommandRecord,
    observation: CommandObservation,
    selector: &t::CommandSelector,
    receipt: &ActivationReceipt,
    _limits: &InvocationLimits,
) -> Result<t::CommandInspection, PlatformError> {
    let terminal = observation == CommandObservation::Terminal;
    let original = source(record);
    let mut payload = None;
    if terminal {
        match &receipt.outcome {
            latent_activation::ActivationOutcome::Succeeded(v) => {
                payload = Some(t::command_inspection::RetainedResult::Success(i::Success {
                    payload: v.output.clone(),
                    media_type: v.output_media_type.clone(),
                    metadata: v.metadata.clone().into_iter().collect(),
                    committed_state_version: v.committed_state_version.clone(),
                    effect_ids: v.effect_ids.clone(),
                }));
            }
            latent_activation::ActivationOutcome::DeclaredError { error, .. } => {
                payload = Some(t::command_inspection::RetainedResult::BusinessRejection(
                    latent_wire::invocation::declared_error_to_proto(error),
                ));
            }
            latent_activation::ActivationOutcome::Failed { .. } => {}
        }
    }
    let committed = terminal && record.outcome() == Outcome::Committed;
    let outcome = if terminal {
        match record.outcome() {
            Outcome::Committed => t::CommandOutcome::Committed,
            Outcome::Rejected => t::CommandOutcome::Rejected,
            Outcome::Aborted => t::CommandOutcome::Aborted,
            Outcome::Pending => return Err(unavailable()),
        }
    } else if observation == CommandObservation::InProgress {
        t::CommandOutcome::InProgress
    } else {
        t::CommandOutcome::RecoveryRequired
    };
    let encoded = record.encode().map_err(|_| unavailable())?;
    let version = match encoded.get(4) {
        Some(3) => 3,
        Some(4) => 4,
        _ => return Err(unavailable()),
    };
    Ok(t::CommandInspection {
        key: Some(t::CommandKey {
            namespace: selector.namespace.clone(),
            recovery_scope: record.key().recovery_scope.clone(),
            operation: selector.operation.clone(),
            entity: record.key().entity.clone(),
            client_key: record.key().client_key.clone(),
        }),
        command_id: record.id().hex(),
        attempt_id: record.attempt_id().hex(),
        fingerprint_sha256: record.fingerprint().bytes().to_vec(),
        outcome: outcome as i32,
        metadata_durable: terminal,
        application_state_committed: committed,
        source: Some(original.clone()),
        retained_result: payload,
        commit: committed.then(|| t::CommitReceipt {
            command_id: record.id().hex(),
            attempt_id: record.attempt_id().hex(),
            transaction_id: record.transaction_id().hex(),
            committed_version: record.committed_view_token().unwrap_or_default().to_vec(),
            committed_at_unix_millis: record.completed_at(),
            effect_ids: record.effect_ids().iter().map(|id| id.hex()).collect(),
            receipt_id: record.disposition_id().hex(),
            source: Some(original),
        }),
        proven_abort: record
            .abort_proof()
            .filter(|_| terminal && record.outcome() == Outcome::Aborted)
            .map(|proof| t::AbortFence {
                command_id: record.id().hex(),
                attempt_id: record.attempt_id().hex(),
                transaction_id: record.transaction_id().hex(),
                owner_fence: proof.bytes().to_vec(),
            }),
        retention: Some(t::LinkedRetention {
            record_format: format!("lsf-command-v{version}"),
            record_version: version,
            payload_expires_at_unix_millis: Some(record.result_expires()),
            identity_expires_at_unix_millis: Some(record.identity_expires()),
            remaining_recovery_millis: None,
            required_record_ids: vec![record.id().hex(), record.attempt_id().hex()],
            payload_available: matches!(
                &receipt.outcome,
                latent_activation::ActivationOutcome::Succeeded(_)
                    | latent_activation::ActivationOutcome::DeclaredError { .. }
            ),
        }),
        cleanup_failure: receipt
            .delivery_failure
            .as_ref()
            .map(latent_wire::invocation::platform_error_to_proto),
    })
}

pub(super) fn lookup_response(
    receipt: ActivationReceipt,
    command: &t::CommandSelector,
    attempt: Option<&str>,
    commit: Option<&str>,
    limits: &InvocationLimits,
) -> Result<OwnedPhase4Response, PlatformError> {
    if matches!(
        receipt.outcome,
        latent_activation::ActivationOutcome::Succeeded(_)
            | latent_activation::ActivationOutcome::DeclaredError { .. }
    ) {
        super::bounded_result(&receipt.outcome)?;
    }
    let disposition = receipt.transaction.as_ref().ok_or_else(unavailable)?;
    if !disposition.read_authorized() {
        return Err(denied());
    }
    let record = disposition.original_command();
    if attempt.is_some_and(|id| id != record.attempt_id().hex()) {
        return Err(denied());
    }
    let fence = receipt
        .result_delivery_fence
        .as_ref()
        .ok_or_else(unavailable)?
        .clone();
    let inspected = inspection(record, disposition.observation(), command, &receipt, limits)?;
    let response = if let Some(commit) = commit {
        if inspected
            .commit
            .as_ref()
            .is_none_or(|value| value.receipt_id != commit)
        {
            return Err(denied());
        }
        contract::Response::from(t::LookupCommitResponse {
            command: Some(inspected),
        })
    } else {
        contract::Response::from(t::LookupCommandResponse {
            command: Some(inspected),
        })
    };
    let bytes = response
        .encoded_len()
        .checked_mul(4)
        .and_then(|value| value.checked_add(16384))
        .ok_or_else(unavailable)?;
    if bytes > usize::try_from(fence.reserved_response_bytes()).unwrap_or(0) {
        return Err(unavailable());
    }
    fence.with_current(bytes, || Ok(()))?;
    Ok(OwnedPhase4Response::new(
        response,
        Arc::new(Owner { fence, bytes }),
    ))
}

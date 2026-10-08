//! Fixed transaction HTTP response framing over the shared command owners.
mod binding;
pub(super) use binding::{bind, budget, map};
#[cfg(test)]
mod tests;
use std::sync::Arc;

use base64::{engine::general_purpose::STANDARD, Engine};
use latent_activation::ActivationOutcome;
use latent_commit::atomic::{CommandRecord, DurableResult, Outcome as DurableOutcome};
use latent_core::{BudgetConsumption, PlatformError, PlatformErrorCode};
use latent_ingress::http::{self, Delivery, DeliveryFence, HttpError, Invocation, Outcome};
use latent_node::{
    transaction_runtime::command_completion::{
        CanonicalCommandResult, CommandObservation, CommandOutput, CommandResultCodec,
        ResultDeliveryFence,
    },
    ActivationReceipt,
};
use serde::Serialize;

const RESULT_BYTES: usize = 128 * 1024;

/// The common result format stays portable. This approved ingress narrows its
/// representable payload before any business write, rather than dropping an
/// oversized result after a successful transaction.
pub(crate) struct HttpCommandResultCodec;
impl CommandResultCodec for HttpCommandResultCodec {
    fn format(&self) -> &str {
        CanonicalCommandResult.format()
    }

    fn validate(&self, outcome: &ActivationOutcome) -> Result<CommandOutput, PlatformError> {
        validate_payload(outcome)?;
        CanonicalCommandResult.validate(outcome)
    }

    fn replay(
        &self,
        record: &CommandRecord,
        result: &DurableResult,
        consumption: BudgetConsumption,
    ) -> Result<ActivationOutcome, PlatformError> {
        let outcome = CanonicalCommandResult.replay(record, result, consumption)?;
        validate_payload(&outcome)?;
        Ok(outcome)
    }
}

fn validate_payload(outcome: &ActivationOutcome) -> Result<(), PlatformError> {
    let valid = match outcome {
        ActivationOutcome::Succeeded(value) => {
            value.output.len() <= RESULT_BYTES && value.output_media_type == http::VALUE_MEDIA_TYPE
        }
        ActivationOutcome::DeclaredError { error, .. } => {
            error.payload.len() <= RESULT_BYTES
                && error.media_type == http::VALUE_MEDIA_TYPE
                && !error.code.is_empty()
                && error.code.len() <= 256
                && error.message.len() <= 1024
                && error.metadata.is_empty()
        }
        ActivationOutcome::Failed { error, .. } => return Err(error.clone()),
    };
    if valid {
        Ok(())
    } else {
        Err(super::super::error(
            PlatformErrorCode::InvalidArgument,
            "transaction-http-result-not-representable",
        ))
    }
}

struct CurrentResult {
    state: Arc<ResultDeliveryFence>,
    bytes: usize,
}
impl DeliveryFence for CurrentResult {
    fn with_current(
        &self,
        action: &mut dyn FnMut() -> Result<(), HttpError>,
    ) -> Result<(), HttpError> {
        self.state
            .with_current(self.bytes, || Ok(action()))
            .map_err(|error| match error.code {
                PlatformErrorCode::PermissionDenied | PlatformErrorCode::Unauthenticated => {
                    HttpError::Forbidden
                }
                PlatformErrorCode::Cancelled => HttpError::Disconnected,
                PlatformErrorCode::DeadlineExceeded => HttpError::DeadlineExceeded,
                _ => HttpError::Overloaded,
            })?
    }
}

#[derive(Serialize)]
#[serde(rename_all = "kebab-case")]
struct ResultValue<'a> {
    media_type: &'a str,
    body_base64: String,
    error_code: Option<&'a str>,
    error_message: Option<&'a str>,
}

#[derive(Serialize)]
#[serde(rename_all = "kebab-case")]
struct AbortFence {
    command_id: String,
    attempt_id: String,
    transaction_id: String,
    owner_fence: String,
}

#[derive(Serialize)]
#[serde(rename_all = "kebab-case")]
struct Response<'a> {
    profile: &'static str,
    disposition: &'static str,
    representation: &'static str,
    command_id: Option<String>,
    attempt_id: Option<String>,
    state_view: Option<String>,
    effect_ids: Vec<String>,
    result_expires_at: Option<String>,
    delivery_failure: Option<&'static str>,
    abort_fence: Option<AbortFence>,
    result: Option<ResultValue<'a>>,
}

pub(super) fn complete(
    receipt: &ActivationReceipt,
    invocation: Invocation,
) -> Result<Delivery, u16> {
    let Some(fence) = &receipt.result_delivery_fence else {
        // A technical failure carries no state data. Durable observations whose
        // fresh read permission failed must not expose the original receipt.
        if receipt.transaction.is_some() {
            return Err(403);
        }
        let ActivationOutcome::Failed { error, .. } = &receipt.outcome else {
            return Err(403);
        };
        return invocation
            .complete(Outcome::Platform(error.code))
            .map_err(|error| error.status().unwrap_or(0));
    };
    let (status, response) = response(receipt)?;
    let body = serde_json::to_vec(&response).map_err(|_| 503u16)?;
    if body.len() > http::MAX_RESPONSE_BODY {
        return Err(502);
    }
    let current = Arc::new(CurrentResult {
        state: Arc::clone(fence),
        bytes: body.len(),
    });
    invocation
        .complete_transaction(status, body, current)
        .map_err(|error| error.status().unwrap_or(0))
}

fn response(receipt: &ActivationReceipt) -> Result<(u16, Response<'_>), u16> {
    let result = payload(&receipt.outcome)?;
    let response = Response {
        profile: http::transaction::PROFILE,
        disposition: "query",
        representation: "application-result",
        command_id: None,
        attempt_id: None,
        state_view: None,
        effect_ids: Vec::new(),
        result_expires_at: None,
        delivery_failure: receipt
            .delivery_failure
            .as_ref()
            .map(|error| error.code.wire_code()),
        abort_fence: None,
        result,
    };
    let Some(disposition) = &receipt.transaction else {
        return query_response(&receipt.outcome, response);
    };
    command_response(receipt, disposition, response)
}

fn query_response<'a>(
    outcome: &ActivationOutcome,
    mut response: Response<'a>,
) -> Result<(u16, Response<'a>), u16> {
    let metadata = match outcome {
        ActivationOutcome::Succeeded(value) => &value.metadata,
        ActivationOutcome::DeclaredError { error, .. } => &error.metadata,
        ActivationOutcome::Failed { .. } => return Err(503),
    };
    let token = metadata
        .get(latent_node::transaction_runtime::query::VIEW_METADATA)
        .ok_or(502u16)?;
    let bytes = STANDARD.decode(token).map_err(|_| 502u16)?;
    if bytes.len() != latent_state::session::version::VIEW_TOKEN_BYTES
        || !bytes.starts_with(b"NV\x02")
        || STANDARD.encode(&bytes) != *token
    {
        return Err(502);
    }
    response.state_view = Some(token.clone());
    let status = if matches!(outcome, ActivationOutcome::DeclaredError { .. }) {
        422
    } else {
        200
    };
    Ok((status, response))
}

fn command_response<'a>(
    receipt: &'a ActivationReceipt,
    disposition: &latent_node::TransactionDisposition,
    mut response: Response<'a>,
) -> Result<(u16, Response<'a>), u16> {
    if !disposition.read_authorized() {
        return Err(403);
    }
    let record = disposition.original_command();
    response.command_id = Some(record.id().hex());
    response.attempt_id = Some(record.attempt_id().hex());
    response.result_expires_at = Some(record.result_expires().to_string());
    response.state_view = record
        .committed_view_token()
        .map(|token| STANDARD.encode(token));
    response.effect_ids = record.effect_ids().iter().map(|id| id.hex()).collect();
    let status = match disposition.observation() {
        CommandObservation::InProgress => {
            response.disposition = "in-progress";
            202
        }
        CommandObservation::RecoveryRequired => {
            response.disposition = "recovery-required";
            503
        }
        CommandObservation::Terminal => match record.outcome() {
            DurableOutcome::Committed => {
                response.disposition = "committed";
                200
            }
            DurableOutcome::Rejected => {
                response.disposition = "rejected";
                422
            }
            DurableOutcome::Aborted => {
                response.disposition = "aborted";
                let proof = record.abort_proof().ok_or(502u16)?;
                response.abort_fence = Some(AbortFence {
                    command_id: record.id().hex(),
                    attempt_id: record.attempt_id().hex(),
                    transaction_id: record.transaction_id().hex(),
                    owner_fence: STANDARD.encode(proof.bytes()),
                });
                409
            }
            DurableOutcome::Pending => return Err(502),
        },
    };
    response.representation = if response.result.is_some() {
        "application-result"
    } else if disposition.observation() == CommandObservation::Terminal {
        "receipt-only"
    } else {
        "status-only"
    };
    // This exact typed expiration comes from the common result lookup, which
    // evaluated the original horizon using the protected continuity owner.
    let expired = matches!(
        &receipt.outcome,
        ActivationOutcome::Failed { error, .. }
            if error.code == PlatformErrorCode::Unavailable
                && error.message == "original-command-result-expired"
    );
    Ok((if expired { 410 } else { status }, response))
}

fn payload(outcome: &ActivationOutcome) -> Result<Option<ResultValue<'_>>, u16> {
    match outcome {
        ActivationOutcome::Succeeded(value) => {
            validate_payload(outcome).map_err(|_| 502u16)?;
            Ok(Some(ResultValue {
                media_type: &value.output_media_type,
                body_base64: STANDARD.encode(&value.output),
                error_code: None,
                error_message: None,
            }))
        }
        ActivationOutcome::DeclaredError { error, .. } => {
            // Query completion adds its host-owned view token. It cannot become
            // arbitrary response headers or a stored command metadata field.
            if error.payload.len() > RESULT_BYTES
                || error.media_type != http::VALUE_MEDIA_TYPE
                || error.code.is_empty()
                || error.code.len() > 256
                || error.message.len() > 1024
                || error
                    .metadata
                    .keys()
                    .any(|key| key != latent_node::transaction_runtime::query::VIEW_METADATA)
            {
                return Err(502);
            }
            Ok(Some(ResultValue {
                media_type: &error.media_type,
                body_base64: STANDARD.encode(&error.payload),
                error_code: Some(&error.code),
                error_message: Some(&error.message),
            }))
        }
        ActivationOutcome::Failed { .. } => Ok(None),
    }
}

//! Direct HTTP admission and framing over the existing transaction owners.
mod binding;
#[cfg(test)]
mod tests;
pub(super) use binding::{bind, budget, business_metadata, map, recover};

use base64::{engine::general_purpose::STANDARD, Engine};
use latent_activation::ActivationOutcome;
use latent_core::{PlatformError, PlatformErrorCode};
use latent_ingress::http::{self, Delivery, DeliveryFence, HttpError, Invocation, Outcome};
use latent_node::{
    transaction_runtime::{
        NativeTransactionAdmission, TransactionAdmissionOwners, TransactionInstallation,
        TransactionOutcomeValidator,
    },
    ActivationReceipt,
};
use latent_rpc::{invocation::v1 as i, phase4, transaction::v1 as t};
use latent_wire::phase4::{OwnedPhase4Response, Phase4ResponseOwner, StateManagementBackend};
use serde::Serialize;
use std::sync::Arc;

const RESULT_BYTES: usize = 128 * 1024;

#[derive(Clone)]
pub(in crate::standalone) struct Services {
    pub owners: Arc<TransactionAdmissionOwners>,
    pub installations: Arc<[Arc<TransactionInstallation>]>,
    pub operations: Arc<[crate::config::state::OperationSettings]>,
    pub management: StateManagementBackend,
}

pub(super) struct HttpResultValidator;
impl TransactionOutcomeValidator for HttpResultValidator {
    fn validate(&self, outcome: &ActivationOutcome) -> Result<(), PlatformError> {
        let valid = match outcome {
            ActivationOutcome::Succeeded(value) => {
                value.output.len() <= RESULT_BYTES
                    && value.output_media_type == http::VALUE_MEDIA_TYPE
                    && host_metadata(&value.metadata)
            }
            ActivationOutcome::DeclaredError { error, .. } => {
                error.payload.len() <= RESULT_BYTES
                    && error.media_type == http::VALUE_MEDIA_TYPE
                    && error.metadata.is_empty()
                    && !error.code.is_empty()
                    && error.code.len() <= 256
            }
            ActivationOutcome::Failed { .. } => true,
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
}

struct CurrentResult(Arc<dyn Phase4ResponseOwner>);
impl DeliveryFence for CurrentResult {
    fn with_current(
        &self,
        action: &mut dyn FnMut() -> Result<(), HttpError>,
    ) -> Result<(), HttpError> {
        let mut result = None;
        self.0
            .with_current(&mut || {
                result = Some(action());
            })
            .map_err(|error| match error.code {
                PlatformErrorCode::PermissionDenied | PlatformErrorCode::Unauthenticated => {
                    HttpError::Forbidden
                }
                PlatformErrorCode::DeadlineExceeded => HttpError::DeadlineExceeded,
                PlatformErrorCode::Cancelled => HttpError::Disconnected,
                _ => HttpError::Overloaded,
            })?;
        result.ok_or(HttpError::Overloaded)?
    }
}

#[derive(Serialize)]
#[serde(rename_all = "kebab-case")]
struct ResultValue {
    media_type: String,
    body_base64: String,
    error_code: Option<String>,
    error_message: Option<String>,
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
struct Response {
    profile: &'static str,
    disposition: &'static str,
    representation: &'static str,
    delivery_failure: Option<&'static str>,
    command_id: Option<String>,
    attempt_id: Option<String>,
    state_view: Option<String>,
    effect_ids: Vec<String>,
    result_expires_at: Option<String>,
    abort_fence: Option<AbortFence>,
    result: Option<ResultValue>,
}

pub(super) fn complete(
    receipt: ActivationReceipt,
    invocation: Invocation,
    admission: &NativeTransactionAdmission,
    installation: &TransactionInstallation,
    clock: &dyn latent_core::ActivationClock,
) -> Result<Delivery, u16> {
    #[cfg(test)]
    if let ActivationOutcome::Failed { error, .. } = &receipt.outcome {
        eprintln!(
            "HTTP transaction terminal code={:?} reason={}",
            error.code, error.message
        );
    }
    let completion = admission
        .take_owned_completion()
        .map_err(super::dispatch::status)?;
    let Some(completion) = completion else {
        let ActivationOutcome::Failed { error, .. } = &receipt.outcome else {
            return Err(503);
        };
        return invocation
            .complete(Outcome::Platform(error.code))
            .map_err(|e| e.status().unwrap_or(0));
    };
    let owned = latent_wire::phase4::project_transaction_completion(
        receipt,
        completion,
        installation,
        &latent_wire::invocation::InvocationLimits::default(),
        clock,
    )
    .map_err(super::dispatch::status)?;
    deliver(invocation, owned)
}

pub(super) fn deliver(
    invocation: Invocation,
    completion: OwnedPhase4Response,
) -> Result<Delivery, u16> {
    let (response, owner) = completion.into_parts();
    owner
        .with_current(&mut || {})
        .map_err(super::dispatch::status)?;
    let (status, response) = project(response)?;
    let body = serde_json::to_vec(&response).map_err(|_| 503u16)?;
    if body.len() > http::MAX_RESPONSE_BODY
        || body.len().saturating_mul(4).saturating_add(16 * 1024) > owner.reserved_bytes()
    {
        return Err(502);
    }
    invocation
        .complete_transaction(status, body, Arc::new(CurrentResult(owner)))
        .map_err(|e| e.status().unwrap_or(0))
}

fn project(response: phase4::Response) -> Result<(u16, Response), u16> {
    let mut body = Response {
        profile: http::transaction::PROFILE,
        disposition: "query",
        representation: "receipt-only",
        delivery_failure: None,
        command_id: None,
        attempt_id: None,
        state_view: None,
        effect_ids: vec![],
        result_expires_at: None,
        abort_fence: None,
        result: None,
    };
    let (command, invocation) = match response {
        phase4::Response::InvokeCommand(value) => (value.command, value.invocation),
        phase4::Response::Query(value) => {
            body.state_view = value.view.map(|v| STANDARD.encode(v.version));
            (None, value.invocation)
        }
        phase4::Response::LookupCommand(value) => (value.command, None),
        _ => return Err(503),
    };
    if let Some(invocation) = invocation {
        body.result = match invocation.result {
            Some(i::invoke_response::Result::Success(value)) => Some(success(value)?),
            Some(i::invoke_response::Result::DeclaredError(value)) => Some(rejection(value)?),
            Some(i::invoke_response::Result::PlatformFailure(_)) => None,
            None => return Err(503),
        };
    }
    let status = if let Some(command) = command {
        if command.cleanup_failure.is_some() {
            body.delivery_failure = Some("unavailable");
        }
        body.command_id = Some(command.command_id);
        body.attempt_id = Some(command.attempt_id);
        body.result_expires_at = command
            .retention
            .and_then(|r| r.payload_expires_at_unix_millis)
            .map(|n| n.to_string());
        body.abort_fence = command.proven_abort.map(|f| AbortFence {
            command_id: f.command_id,
            attempt_id: f.attempt_id,
            transaction_id: f.transaction_id,
            owner_fence: STANDARD.encode(f.owner_fence),
        });
        if let Some(commit) = command.commit {
            body.state_view = Some(STANDARD.encode(commit.committed_version));
            body.effect_ids = commit.effect_ids;
        }
        if let Some(result) = command.retained_result {
            body.result = match result {
                t::command_inspection::RetainedResult::Success(value) => Some(success(value)?),
                t::command_inspection::RetainedResult::BusinessRejection(value) => {
                    Some(rejection(value)?)
                }
                t::command_inspection::RetainedResult::TechnicalFailure(_) => None,
            };
        }
        match t::CommandOutcome::try_from(command.outcome).map_err(|_| 503u16)? {
            t::CommandOutcome::Committed => {
                body.disposition = "committed";
                200
            }
            t::CommandOutcome::Rejected => {
                body.disposition = "rejected";
                422
            }
            t::CommandOutcome::Aborted => {
                body.disposition = "aborted";
                409
            }
            t::CommandOutcome::InProgress => {
                body.disposition = "in-progress";
                202
            }
            t::CommandOutcome::RecoveryRequired => {
                body.disposition = "recovery-required";
                503
            }
            _ => return Err(503),
        }
    } else if let Some(result) = &body.result {
        if result.error_code.is_some() {
            422
        } else {
            200
        }
    } else {
        503
    };
    if body.result.is_some() {
        body.representation = "application-result";
    }
    Ok((status, body))
}

fn success(value: i::Success) -> Result<ResultValue, u16> {
    if value.payload.len() > RESULT_BYTES
        || value.media_type != http::VALUE_MEDIA_TYPE
        || !host_metadata(&value.metadata)
    {
        return Err(502);
    }
    Ok(ResultValue {
        media_type: value.media_type,
        body_base64: STANDARD.encode(value.payload),
        error_code: None,
        error_message: None,
    })
}

fn host_metadata<'a>(values: impl IntoIterator<Item = (&'a String, &'a String)>) -> bool {
    values.into_iter().all(|(key, value)| match key.as_str() {
        "cell-id" => value.len() <= 256 && !value.chars().any(char::is_control),
        "cell-disposition" => matches!(value.as_str(), "released" | "quarantined"),
        _ => false,
    })
}
fn rejection(value: i::DeclaredError) -> Result<ResultValue, u16> {
    if value.payload.len() > RESULT_BYTES
        || value.media_type != http::VALUE_MEDIA_TYPE
        || !value.metadata.is_empty()
        || value.code.is_empty()
        || value.code.len() > 256
    {
        return Err(502);
    }
    Ok(ResultValue {
        media_type: value.media_type,
        body_base64: STANDARD.encode(value.payload),
        error_code: Some(value.code),
        error_message: Some(String::new()),
    })
}

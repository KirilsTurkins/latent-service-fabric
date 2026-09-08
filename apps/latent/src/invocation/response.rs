mod values;

use latent_activation::{ActivationOutcome, RetainedActivationOutcome};
use latent_core::CancelDisposition;
use latent_wire::invocation::{
    activation_status_from_proto, cancel_disposition_from_proto, invocation_response_from_proto,
};
use serde_json::json;

use super::{bounds, proto, protocol};
use crate::{
    error::{platform_value, Failure},
    output::Outcome,
};
use values::{consumption, declared, payload, terminal};

pub(super) fn invocation(
    value: proto::InvokeResponse,
    requested: Option<&str>,
    maximum: usize,
) -> Result<Outcome, Failure> {
    bounds::invocation(&value, requested, maximum)?;
    let response = invocation_response_from_proto(value).map_err(|_| protocol())?;
    let mut data = json!({"activationId": response.receipt.activation_id.0,
        "resolvedRevision": response.receipt.resolved_revision.map(|pin| json!({
            "revisionId": pin.revision_id.0, "releaseDigest": pin.release_digest.0,
            "routeGeneration": pin.route_generation.0.to_string()}))});
    Ok(match response.outcome {
        ActivationOutcome::Succeeded(result) => {
            data["payload"] = payload(&result.output, &result.output_media_type);
            data["consumption"] = consumption(&result.consumption);
            data["committedStateVersion"] = json!(result.committed_state_version);
            data["effectIds"] = json!(result.effect_ids);
            data["metadata"] = json!(result.metadata);
            Outcome::success(data)
        }
        ActivationOutcome::DeclaredError {
            error,
            consumption: used,
        } => {
            data["declaredError"] = declared(&error);
            data["consumption"] = consumption(&used);
            Outcome::domain_error(data)
        }
        ActivationOutcome::Failed {
            terminal_state,
            error,
            consumption: used,
        } => {
            data["terminalState"] = json!(terminal(terminal_state));
            data["consumption"] = consumption(&used);
            Outcome::platform_failure(data, &error)
        }
    })
}

pub(super) fn status(
    value: proto::ActivationStatus,
    requested: &str,
    maximum: usize,
) -> Result<Outcome, Failure> {
    bounds::status(&value, requested, maximum)?;
    // These strings are validated by the shared converter, including every known
    // phase/terminal spelling. Keep those spellings without another enum table.
    let phase = value.phase.clone();
    let state = value.terminal_state.clone();
    let value = activation_status_from_proto(value).map_err(|_| protocol())?;
    let outcome = match value.terminal_outcome {
        Some(RetainedActivationOutcome::Succeeded(summary)) => json!({"kind": "success",
            "committedStateVersion": summary.committed_state_version, "effectIds": summary.effect_ids, "metadata": summary.metadata}),
        Some(RetainedActivationOutcome::DeclaredError(error)) => {
            json!({"kind": "declared-error", "declaredError": declared(&error)})
        }
        Some(RetainedActivationOutcome::PlatformFailure(error)) => {
            json!({"kind": "platform-failure", "error": platform_value(&error)})
        }
        None => serde_json::Value::Null,
    };
    Ok(Outcome::success(
        json!({"activationId": value.activation_id.0, "phase": phase,
        "terminalState": state, "terminalOutcome": outcome,
        "finalConsumption": value.final_consumption.as_ref().map(consumption),
        "lastUpdatedUnixMillis": value.last_updated_unix_millis.to_string(),
        "terminalAtUnixMillis": value.terminal_at_unix_millis.map(|v| v.to_string()), "metadata": value.metadata}),
    ))
}

pub(super) fn cancellation(
    value: proto::CancelResponse,
    id: &str,
    maximum: usize,
) -> Result<Outcome, Failure> {
    bounds::cancellation(&value, maximum)?;
    let disposition = cancel_disposition_from_proto(value).map_err(|_| protocol())?;
    let (name, state) = match disposition {
        CancelDisposition::Accepted => ("accepted", None),
        CancelDisposition::AlreadyTerminal(state) => ("already_terminal", terminal(state)),
        CancelDisposition::NotFound => ("not_found", None),
    };
    let data = json!({"activationId": id, "disposition": name, "terminalState": state});
    Ok(if disposition == CancelDisposition::NotFound {
        Outcome::not_found(data)
    } else {
        Outcome::success(data)
    })
}

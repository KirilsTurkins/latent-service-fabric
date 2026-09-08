use std::collections::HashMap;

use super::{proto, protocol};
use crate::error::Failure;
use prost::Message;

const STRING: usize = 4096;
const PAYLOAD: usize = 1024 * 1024;

pub(super) fn identifier(value: &str, maximum: usize) -> bool {
    !value.is_empty()
        && value.len() <= maximum
        && !value
            .chars()
            .any(|ch| ch.is_control() || ch.is_whitespace())
}
pub(super) fn media(value: &str) -> bool {
    !value.is_empty() && value.len() <= STRING && !value.chars().any(char::is_control)
}

pub(super) fn invocation(
    value: &proto::InvokeResponse,
    requested: Option<&str>,
    maximum: usize,
) -> Result<(), Failure> {
    let fields = identifier(&value.activation_id, 512)
        && requested.is_none_or(|id| id == value.activation_id)
        && value.revision_id.len() <= 512
        && value.release_digest.len() <= 512;
    let outcome = match value.result.as_ref() {
        Some(proto::invoke_response::Result::Success(value)) => success(value),
        Some(proto::invoke_response::Result::DeclaredError(value)) => declared(value),
        Some(proto::invoke_response::Result::PlatformFailure(value)) => platform(value),
        None => false,
    };
    finish(fields && outcome, value, maximum)
}

pub(super) fn status(
    value: &proto::ActivationStatus,
    requested: &str,
    maximum: usize,
) -> Result<(), Failure> {
    let fields = identifier(&value.activation_id, 512)
        && value.activation_id == requested
        && value.phase.len() <= 64
        && value.terminal_state.as_ref().is_none_or(|s| s.len() <= 64)
        && metadata(&value.metadata, 64);
    let outcome = match value.terminal_outcome.as_ref() {
        Some(proto::activation_status::TerminalOutcome::Succeeded(value)) => summary(
            value.committed_state_version.as_deref(),
            &value.effect_ids,
            &value.metadata,
        ),
        Some(proto::activation_status::TerminalOutcome::DeclaredError(value)) => declared(value),
        Some(proto::activation_status::TerminalOutcome::PlatformFailure(value)) => platform(value),
        None => true,
    };
    finish(fields && outcome, value, maximum)
}

pub(super) fn cancellation(value: &proto::CancelResponse, maximum: usize) -> Result<(), Failure> {
    finish(
        value.terminal_state.as_ref().is_none_or(|s| s.len() <= 64),
        value,
        maximum,
    )
}

fn success(value: &proto::Success) -> bool {
    value.payload.len() <= PAYLOAD
        && media(&value.media_type)
        && summary(
            value.committed_state_version.as_deref(),
            &value.effect_ids,
            &value.metadata,
        )
}
fn summary(
    version: Option<&str>,
    effects: &[String],
    attributes: &HashMap<String, String>,
) -> bool {
    version.is_none_or(|s| s.len() <= STRING)
        && effects.len() <= 64
        && effects.iter().all(|id| identifier(id, STRING))
        && metadata(attributes, 64)
}
fn declared(value: &proto::DeclaredError) -> bool {
    identifier(&value.code, STRING)
        && value.message.len() <= STRING
        && value.payload.len() <= PAYLOAD
        && media(&value.media_type)
        && metadata(&value.metadata, 64)
}
fn platform(value: &proto::PlatformError) -> bool {
    identifier(&value.code, 512)
        && value.message.len() <= STRING
        && value.detail_items.len() <= 16
        && value
            .detail_items
            .iter()
            .all(|detail| identifier(&detail.kind, STRING) && metadata(&detail.fields, 32))
}
fn metadata(values: &HashMap<String, String>, maximum: usize) -> bool {
    if values.len() > maximum {
        return false;
    }
    let mut total = 0_usize;
    for (key, value) in values {
        if key.len() > STRING || value.len() > STRING {
            return false;
        }
        total += key.len() + value.len();
        if total > 32 * 1024 {
            return false;
        }
    }
    true
}
fn finish(valid: bool, value: &impl Message, maximum: usize) -> Result<(), Failure> {
    // Encoding traverses collections only after their independent count/byte checks.
    if valid && value.encoded_len() <= maximum {
        Ok(())
    } else {
        Err(protocol())
    }
}

use latent_core::{Metadata, PlatformError};

use crate::{ActivationObservationContext, GuestLogRecord, LogRecord};

use super::{error, formatting, SharedActivationObserverConfig};

pub(super) fn validate_config(
    config: &SharedActivationObserverConfig,
) -> Result<(), PlatformError> {
    if [
        config.maximum_active_correlations,
        config.maximum_correlation_value_bytes,
        config.maximum_context_bytes,
        config.maximum_log_input_bytes,
        config.maximum_log_body_bytes,
        config.maximum_log_fields,
        config.maximum_field_name_bytes,
        config.maximum_field_value_bytes,
    ]
    .contains(&0)
        || config.allowed_guest_field_names.capacity() > config.maximum_log_fields
        || config.allowed_guest_field_names.iter().any(|name| {
            name.is_empty()
                || name.capacity().saturating_add("guest.".len()) > config.maximum_field_name_bytes
                || name.chars().any(char::is_control)
                || reserved(name)
                || sensitive(name)
        })
        || !allocation_bounds_fit(config)
    {
        return Err(error("invalid-activation-observer-limits"));
    }
    Ok(())
}

fn allocation_bounds_fit(config: &SharedActivationObserverConfig) -> bool {
    // Boxed entries plus both sparse BTree indexes have a fixed conservative
    // allowance per token; the second identifier copy belongs to the ID index.
    let correlations = config
        .maximum_context_bytes
        .checked_add(config.maximum_correlation_value_bytes)
        .and_then(|bytes| bytes.checked_add(4096))
        .and_then(|bytes| bytes.checked_mul(config.maximum_active_correlations));
    let allowlist = config
        .maximum_field_name_bytes
        .checked_add(size_of::<String>())
        .and_then(|bytes| bytes.checked_mul(config.maximum_log_fields));
    correlations
        .zip(allowlist)
        .and_then(|(contexts, names)| contexts.checked_add(names))
        .is_some_and(|bytes| isize::try_from(bytes).is_ok())
}

pub(super) fn valid_context(
    context: &ActivationObservationContext,
    config: &SharedActivationObserverConfig,
) -> bool {
    let values = [
        Some(context.activation_id.0.as_str()),
        Some(context.root_activation_id.0.as_str()),
        context
            .parent_activation_id
            .as_ref()
            .map(|id| id.0.as_str()),
        Some(context.tenant.0.as_str()),
        Some(context.service.0.as_str()),
        Some(context.contract.0.as_str()),
        Some(context.function.0.as_str()),
        Some(context.trace_id.0.as_str()),
        Some(context.span_id.0.as_str()),
        context.release.as_ref().map(|id| id.0.as_str()),
        context.revision.as_ref().map(|id| id.0.as_str()),
    ];
    let mut remaining = config.maximum_context_bytes;
    values.into_iter().flatten().all(|value| {
        if value.len() > config.maximum_correlation_value_bytes
            || value.chars().any(char::is_control)
        {
            return false;
        }
        let Some(left) = remaining.checked_sub(value.len()) else {
            return false;
        };
        remaining = left;
        true
    })
}

pub(super) fn valid_log(
    record: &GuestLogRecord<'_>,
    config: &SharedActivationObserverConfig,
) -> bool {
    if record.activation_id.0.len() > config.maximum_correlation_value_bytes
        || record.fields.len() > config.maximum_log_fields
    {
        return false;
    }
    let Some(mut remaining) = config
        .maximum_log_input_bytes
        .checked_sub(record.body.len())
    else {
        return false;
    };
    for (key, value) in record.fields {
        let Some(left) = remaining
            .checked_sub(key.len())
            .and_then(|left| left.checked_sub(value.len()))
        else {
            return false;
        };
        remaining = left;
    }
    true
}

pub(super) fn guest_log(
    record: &GuestLogRecord<'_>,
    context: &ActivationObservationContext,
    config: &SharedActivationObserverConfig,
) -> LogRecord {
    let mut attributes = formatting::attributes(context, config.maximum_field_value_bytes);
    attributes.extend(fields(record.fields, config));
    let body = if config.export_guest_log_bodies && !sensitive(record.body) {
        formatting::bounded(record.body, config.maximum_log_body_bytes)
    } else {
        "[REDACTED]".to_owned()
    };
    LogRecord {
        severity: record.severity,
        body,
        trace: Some(formatting::trace(context, config.maximum_field_value_bytes)),
        attributes,
        observed_at_unix_millis: record.observed_at_unix_millis,
    }
}

fn fields(fields: &Metadata, config: &SharedActivationObserverConfig) -> Metadata {
    fields
        .iter()
        .filter(|(name, _)| {
            name.len() <= config.maximum_field_name_bytes
                && !reserved(name)
                && !sensitive(name)
                && config
                    .allowed_guest_field_names
                    .iter()
                    .any(|allowed| allowed == *name)
        })
        .map(|(name, value)| {
            (
                format!("guest.{name}"),
                if sensitive(value) {
                    "[REDACTED]".to_owned()
                } else {
                    formatting::bounded(value, config.maximum_field_value_bytes)
                },
            )
        })
        .collect()
}

fn reserved(name: &str) -> bool {
    name.get(..7)
        .is_some_and(|prefix| prefix.eq_ignore_ascii_case("latent."))
}

fn sensitive(value: &str) -> bool {
    // Callers bound the complete borrowed input before this temporary copy.
    let lower = value.to_ascii_lowercase();
    [
        "authorization",
        "bearer ",
        "password",
        "passwd",
        "secret",
        "credential",
        "api_key",
        "api-key",
        "apikey",
        "access_token",
        "access-token",
        "refresh_token",
        "refresh-token",
        "private key",
        "privatekey",
        "begin rsa",
        "begin openssh",
        "cookie",
        "session",
        "token=",
        "token:",
        "\"token\"",
        "backtrace",
        "stacktrace",
        "stack trace",
        "payload",
    ]
    .iter()
    .any(|marker| lower.contains(marker))
}

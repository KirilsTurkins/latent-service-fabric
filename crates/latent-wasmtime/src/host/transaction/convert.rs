use super::{key_value as wit, port, staging};
use latent_core::transaction_contract as contract;

pub(super) fn state_error(error: port::StateFailure) -> wit::StateError {
    match error {
        port::StateFailure::PermissionDenied => wit::StateError::PermissionDenied,
        port::StateFailure::InvalidKey => wit::StateError::InvalidKey,
        port::StateFailure::InvalidValue => wit::StateError::InvalidValue,
        port::StateFailure::InvalidLimit => wit::StateError::InvalidLimit,
        port::StateFailure::InvalidCursor => wit::StateError::InvalidCursor,
        port::StateFailure::StaleInput => wit::StateError::StaleInput,
        port::StateFailure::Conflict => wit::StateError::Conflict,
        port::StateFailure::ReadBudgetExhausted => wit::StateError::ReadBudgetExhausted,
        port::StateFailure::WriteBudgetExhausted => wit::StateError::WriteBudgetExhausted,
        port::StateFailure::HandleClosed => wit::StateError::HandleClosed,
        port::StateFailure::WrongActivation => wit::StateError::WrongActivation,
        port::StateFailure::WrongMode => wit::StateError::WrongMode,
        port::StateFailure::UnsupportedVersion => wit::StateError::UnsupportedVersion,
        port::StateFailure::Cancelled => wit::StateError::Cancelled,
        port::StateFailure::Unavailable => wit::StateError::Unavailable,
    }
}
pub(super) fn intent_error(error: port::IntentFailure) -> staging::IntentError {
    match error {
        port::IntentFailure::PermissionDenied => staging::IntentError::PermissionDenied,
        port::IntentFailure::InvalidBinding => staging::IntentError::InvalidBinding,
        port::IntentFailure::InvalidOperation => staging::IntentError::InvalidOperation,
        port::IntentFailure::InvalidPayload => staging::IntentError::InvalidPayload,
        port::IntentFailure::InvalidExpiry => staging::IntentError::InvalidExpiry,
        port::IntentFailure::CountLimit => staging::IntentError::CountLimit,
        port::IntentFailure::ByteLimit => staging::IntentError::ByteLimit,
        port::IntentFailure::HandleClosed => staging::IntentError::HandleClosed,
        port::IntentFailure::WrongActivation => staging::IntentError::WrongActivation,
        port::IntentFailure::WrongMode => staging::IntentError::WrongMode,
        port::IntentFailure::UnsupportedProfile => staging::IntentError::UnsupportedProfile,
        port::IntentFailure::Cancelled => staging::IntentError::Cancelled,
        port::IntentFailure::Unavailable => staging::IntentError::Unavailable,
    }
}
pub(super) fn view(value: port::ViewIdentity) -> wit::ViewIdentity {
    wit::ViewIdentity {
        namespace: value.namespace,
        incarnation: value.incarnation,
        version: value.version,
        state_schema: value.state_schema,
    }
}
pub(super) fn value(value: contract::Value) -> wit::Value {
    wit::Value {
        bytes: value.bytes,
        media_type: value.media_type,
        metadata: value.metadata,
    }
}
pub(super) fn input_value(value: wit::Value) -> Result<contract::Value, wit::StateError> {
    let value = contract::Value {
        bytes: value.bytes,
        media_type: value.media_type,
        metadata: value.metadata,
    };
    value
        .validate()
        .map_err(|_| wit::StateError::InvalidValue)?;
    Ok(value)
}
pub(super) fn versioned(value: port::VersionedValue) -> wit::VersionedValue {
    wit::VersionedValue {
        value: self::value(value.value),
        version: value.version,
    }
}
pub(super) fn page_info(value: port::PageInfo) -> wit::PageInfo {
    wit::PageInfo {
        view: view(value.view),
        entry_count: value.entry_count,
        encoded_bytes: value.encoded_bytes,
        has_more: value.has_more,
        next_cursor: value.next_cursor,
    }
}
pub(super) fn view_size(value: &port::ViewIdentity) -> Result<usize, wit::StateError> {
    if value.namespace.is_empty()
        || value.namespace.len() > contract::IDENTITY_BYTES
        || value.incarnation.is_empty()
        || value.incarnation.len() > contract::IDENTITY_BYTES
        || value.state_schema.is_empty()
        || value.state_schema.len() > contract::IDENTITY_BYTES
        || value.version.len() > contract::VERSION_BYTES
    {
        return Err(wit::StateError::UnsupportedVersion);
    }
    Ok(value.namespace.len()
        + value.incarnation.len()
        + value.state_schema.len()
        + value.version.len()
        + 128)
}
pub(super) fn command_size(value: &port::CommandInfo) -> Result<usize, wit::StateError> {
    if value.command_id.is_empty()
        || value.command_id.len() > contract::IDENTITY_BYTES
        || value.attempt_id.is_empty()
        || value.attempt_id.len() > contract::IDENTITY_BYTES
        || value
            .entity
            .as_ref()
            .is_some_and(|e| e.is_empty() || e.len() > contract::IDENTITY_BYTES)
    {
        return Err(wit::StateError::UnsupportedVersion);
    }
    Ok(view_size(&value.view)?
        + value.command_id.len()
        + value.attempt_id.len()
        + value.entity.as_ref().map_or(0, String::len)
        + 128)
}
pub(super) fn input_size(value: &contract::Value) -> Result<usize, wit::StateError> {
    value
        .validate()
        .map_err(|_| wit::StateError::InvalidValue)?;
    Ok(value.bytes.len()
        + value.media_type.len()
        + value
            .metadata
            .iter()
            .map(|(a, b)| a.len() + b.len() + 32)
            .sum::<usize>()
        + 256)
}
pub(super) fn value_size(value: &port::VersionedValue) -> Result<usize, wit::StateError> {
    value
        .value
        .validate()
        .map_err(|_| wit::StateError::Unavailable)?;
    if value.version.len() > contract::VERSION_BYTES {
        return Err(wit::StateError::UnsupportedVersion);
    }
    Ok(value.value.bytes.len()
        + value.value.media_type.len()
        + value
            .value
            .metadata
            .iter()
            .map(|(a, b)| a.len() + b.len() + 32)
            .sum::<usize>()
        + value.version.len()
        + 256)
}
pub(super) fn page_size(page: &port::Page) -> Result<usize, wit::StateError> {
    if page.entries.len() > contract::PAGE_ENTRIES as usize
        || page.info.entry_count as usize != page.entries.len()
        || page.info.encoded_bytes > contract::PAGE_BYTES as u64
        || page
            .info
            .next_cursor
            .as_ref()
            .is_some_and(|c| c.len() > contract::VERSION_BYTES)
    {
        return Err(wit::StateError::Unavailable);
    }
    if page.info.has_more != page.info.next_cursor.is_some() {
        return Err(wit::StateError::Unavailable);
    }
    let header =
        view_size(&page.info.view)? + 128 + page.info.next_cursor.as_ref().map_or(0, Vec::len);
    page.entries.iter().try_fold(header, |sum, entry| {
        if entry.key.is_empty() || entry.key.len() > contract::KEY_BYTES {
            return Err(wit::StateError::Unavailable);
        }
        sum.checked_add(value_size(&entry.value)? + entry.key.len() + 128)
            .ok_or(wit::StateError::ReadBudgetExhausted)
    })
}

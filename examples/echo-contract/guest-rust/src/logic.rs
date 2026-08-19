//! Pure echo-domain behavior shared by native unit tests and the WebAssembly guest.

/// Maximum accepted UTF-8 message size, measured in bytes.
pub const MAX_MESSAGE_BYTES: usize = 4 * 1024;

/// Maximum activation identifier size included in a structured log field.
pub const MAX_ACTIVATION_ID_BYTES: usize = 128;

/// Classification used to map domain behavior to generated WIT types.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EchoOutcome {
    /// The message is accepted and returned unchanged.
    Success,
    /// The message contains no bytes.
    EmptyMessage,
    /// The message exceeds [`MAX_MESSAGE_BYTES`].
    MessageTooLarge,
}

impl EchoOutcome {
    /// Stable, bounded value written to the structured log.
    pub const fn as_log_value(self) -> &'static str {
        match self {
            Self::Success => "success",
            Self::EmptyMessage => "empty-message",
            Self::MessageTooLarge => "message-too-large",
        }
    }
}

/// Classify a message without allocating or observing host state.
#[must_use]
pub fn classify_message(message: &str) -> EchoOutcome {
    if message.is_empty() {
        EchoOutcome::EmptyMessage
    } else if message.len() > MAX_MESSAGE_BYTES {
        EchoOutcome::MessageTooLarge
    } else {
        EchoOutcome::Success
    }
}

/// Return a UTF-8-safe prefix no larger than `maximum_bytes`.
#[must_use]
pub fn bounded_utf8(value: &str, maximum_bytes: usize) -> String {
    if value.len() <= maximum_bytes {
        return value.to_owned();
    }

    let mut boundary = maximum_bytes;
    while !value.is_char_boundary(boundary) {
        boundary -= 1;
    }
    value[..boundary].to_owned()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_and_preserves_boundary_sized_messages() {
        let message = "x".repeat(MAX_MESSAGE_BYTES);
        assert_eq!(classify_message(&message), EchoOutcome::Success);
    }

    #[test]
    fn rejects_empty_messages() {
        assert_eq!(classify_message(""), EchoOutcome::EmptyMessage);
    }

    #[test]
    fn rejects_messages_larger_than_the_byte_limit() {
        let message = "x".repeat(MAX_MESSAGE_BYTES + 1);
        assert_eq!(classify_message(&message), EchoOutcome::MessageTooLarge);
    }

    #[test]
    fn measures_utf8_input_in_bytes() {
        let message = "é".repeat(MAX_MESSAGE_BYTES / 2 + 1);
        assert_eq!(classify_message(&message), EchoOutcome::MessageTooLarge);
    }

    #[test]
    fn bounds_activation_ids_at_a_character_boundary() {
        let value = format!("{}é", "x".repeat(MAX_ACTIVATION_ID_BYTES - 1));
        let bounded = bounded_utf8(&value, MAX_ACTIVATION_ID_BYTES);
        assert_eq!(bounded, "x".repeat(MAX_ACTIVATION_ID_BYTES - 1));
        assert!(bounded.len() <= MAX_ACTIVATION_ID_BYTES);
    }
}

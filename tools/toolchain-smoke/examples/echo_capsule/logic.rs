pub(crate) const MAX_MESSAGE_BYTES: usize = 64 * 1024;
pub(crate) const MAX_LOG_ACTIVATION_ID_BYTES: usize = 128;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum MessageRejection {
    Empty,
    OverLimit,
}

pub(crate) fn echo(message: String) -> Result<String, MessageRejection> {
    if message.is_empty() {
        return Err(MessageRejection::Empty);
    }
    if message.len() > MAX_MESSAGE_BYTES {
        return Err(MessageRejection::OverLimit);
    }
    Ok(message)
}

pub(crate) fn bounded_utf8_prefix(value: &str, maximum_bytes: usize) -> &str {
    if value.len() <= maximum_bytes {
        return value;
    }

    let mut end = maximum_bytes;
    while !value.is_char_boundary(end) {
        end -= 1;
    }
    &value[..end]
}

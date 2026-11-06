//! Allocation-free ceilings before serde creates typed collections or scratch.
//! This is a resource prepass, not a substitute for schema/canonical validation.
use super::{capacity, corrupt, PlatformError};

pub(super) fn check(bytes: &[u8]) -> Result<(), PlatformError> {
    let mut depth = 0usize;
    let mut delimiters = 0usize;
    let mut string_start = None;
    let mut escaped = false;
    for (index, byte) in bytes.iter().copied().enumerate() {
        if let Some(start) = string_start {
            // A valid 512-byte token needs at most 6 encoded bytes per byte.
            // Leave room for all existing record codecs, but no document-sized
            // escaped string may enter serde's scratch buffer.
            if index - start > 4096 {
                return Err(capacity());
            }
            if escaped {
                escaped = false;
            } else if byte == b'\\' {
                escaped = true;
            } else if byte == b'"' {
                string_start = None;
            }
            continue;
        }
        match byte {
            b'"' => {
                string_start = Some(index);
                delimiters += 1;
            }
            b'[' | b'{' => {
                depth += 1;
                delimiters += 1;
                if depth > 16 {
                    return Err(capacity());
                }
            }
            b']' | b'}' => depth = depth.checked_sub(1).ok_or_else(corrupt)?,
            b',' | b':' => delimiters += 1,
            _ => {}
        }
        if delimiters > 131_072 {
            return Err(capacity());
        }
    }
    if string_start.is_some() || depth != 0 {
        return Err(corrupt());
    }
    Ok(())
}

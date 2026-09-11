use crate::error::Failure;

use super::{invalid, model::Document};

pub(super) const MAXIMUM_CONFIG_BYTES: usize = 64 * 1024;

pub(super) fn document(bytes: &[u8]) -> Result<Document, Failure> {
    if bytes.len() > MAXIMUM_CONFIG_BYTES {
        return Err(invalid());
    }
    // Bound containers and structural tokens before any deserialization allocation.
    // Typed Serde structs subsequently reject malformed, duplicate, and unknown fields.
    let mut depth = 0_u32;
    let mut structures = 0_u32;
    let mut quoted = false;
    let mut escaped = false;
    for byte in bytes {
        if quoted {
            if escaped {
                escaped = false;
            } else if *byte == b'\\' {
                escaped = true;
            } else if *byte == b'"' {
                quoted = false;
            }
        } else {
            match byte {
                b'"' => quoted = true,
                b'{' | b'[' => {
                    depth += 1;
                    structures += 1;
                }
                b'}' | b']' => depth = depth.checked_sub(1).ok_or_else(invalid)?,
                b',' | b':' => structures += 1,
                _ => {}
            }
        }
        if depth > 16 || structures > 4096 {
            return Err(invalid());
        }
    }
    serde_json::from_slice(bytes).map_err(|_| invalid())
}

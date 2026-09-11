//! Cheap source preflight before third-party WIT parser allocation or recursion.
use super::{exhausted, invalid, limits::add, SemanticLimits};
use latent_core::PlatformError;

pub(super) fn preflight(
    source: &str,
    total_tokens: &mut usize,
    limits: SemanticLimits,
) -> Result<(), PlatformError> {
    if source.len() > limits.max_wit_source_bytes {
        return Err(exhausted("wit-source-byte-limit"));
    }
    let bytes = source.as_bytes();
    let mut offset = 0;
    let mut depth = 0_usize;
    while offset < bytes.len() {
        let byte = bytes[offset];
        if byte.is_ascii_whitespace() {
            offset += 1;
            continue;
        }
        if bytes[offset..].starts_with(b"//") {
            offset += 2;
            while offset < bytes.len() && bytes[offset] != b'\n' {
                offset += 1;
            }
            continue;
        }
        if bytes[offset..].starts_with(b"/*") {
            offset += 2;
            let mut comments = 1_usize;
            while comments != 0 {
                if offset == bytes.len() {
                    return Err(invalid("unterminated-wit-comment"));
                }
                if bytes[offset..].starts_with(b"/*") {
                    add(&mut comments, 1, limits.max_type_depth)?;
                    offset += 2;
                } else if bytes[offset..].starts_with(b"*/") {
                    comments -= 1;
                    offset += 2;
                } else {
                    offset += 1;
                }
            }
            continue;
        }
        add(total_tokens, 1, limits.max_wit_tokens)?;
        if byte == b'"' {
            offset += 1;
            let start = offset;
            loop {
                let next = *bytes
                    .get(offset)
                    .ok_or_else(|| invalid("unterminated-wit-string"))?;
                offset += 1;
                if next == b'"' {
                    break;
                }
                if next == b'\\' {
                    if offset == bytes.len() {
                        return Err(invalid("unterminated-wit-string"));
                    }
                    offset += 1;
                }
                if offset - start > limits.max_name_bytes {
                    return Err(exhausted("wit-token-byte-limit"));
                }
            }
        } else if byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'%' | b'-') {
            let start = offset;
            offset += 1;
            while offset < bytes.len()
                && (bytes[offset].is_ascii_alphanumeric() || matches!(bytes[offset], b'_' | b'-'))
            {
                offset += 1;
            }
            if offset - start > limits.max_name_bytes {
                return Err(exhausted("wit-token-byte-limit"));
            }
        } else {
            if matches!(byte, b'{' | b'(' | b'<' | b'[') {
                add(&mut depth, 1, limits.max_type_depth)?;
            } else if matches!(byte, b'}' | b')' | b']')
                || (byte == b'>'
                    && offset
                        .checked_sub(1)
                        .is_none_or(|prior| bytes[prior] != b'-'))
            {
                depth = depth
                    .checked_sub(1)
                    .ok_or_else(|| invalid("unbalanced-wit-delimiters"))?;
            }
            offset += 1;
        }
    }
    if depth != 0 {
        return Err(invalid("unbalanced-wit-delimiters"));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn lexical_bounds_precede_recursive_source_parsing() {
        let limits = SemanticLimits {
            max_type_depth: 4,
            ..SemanticLimits::default()
        };
        assert!(preflight(
            "/* < { /* > */ } */ package a:b; interface x { f: func() -> u32; }",
            &mut 0,
            limits
        )
        .is_ok());
        assert!(preflight(
            "package a:b; interface x { type x = list<list<list<list<u32>>>>; }",
            &mut 0,
            limits
        )
        .is_err());
        assert!(preflight("/* /* /* /* /* */ */ */ */ */", &mut 0, limits).is_err());
        assert!(preflight(
            "package a:b;",
            &mut 0,
            SemanticLimits {
                max_wit_tokens: 2,
                ..limits
            }
        )
        .is_err());
    }
}

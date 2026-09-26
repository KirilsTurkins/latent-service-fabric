use super::{HttpError, Scheme, MAX_TARGET_BYTES};
use std::net::{Ipv4Addr, Ipv6Addr};

/// A single canonical routing/security identity. Consumers must match these
/// bytes directly; they must not percent-decode or normalize a second time.
#[derive(Debug, PartialEq, Eq)]
pub struct CanonicalTarget {
    pub(super) scheme: Scheme,
    pub(super) authority: String,
    pub(super) path: String,
    pub(super) query: Option<String>,
}

impl CanonicalTarget {
    pub fn parse(scheme: Scheme, authority: &str, target: &str) -> Result<Self, HttpError> {
        if target.len() > MAX_TARGET_BYTES || !target.starts_with('/') {
            return Err(HttpError::InvalidTarget);
        }
        let authority = canonical_authority(scheme, authority)?;
        let (path, query) = target
            .split_once('?')
            .map_or((target, None), |(p, q)| (p, Some(q)));
        let path = normalize(path, false)?;
        if path.contains("//") || path.split('/').any(|s| matches!(s, "." | "..")) {
            return Err(HttpError::InvalidTarget);
        }
        let query = query.map(|value| normalize(value, true)).transpose()?;
        Ok(Self {
            scheme,
            authority,
            path,
            query,
        })
    }
    #[must_use]
    pub fn scheme(&self) -> Scheme {
        self.scheme
    }
    #[must_use]
    pub fn authority(&self) -> &str {
        &self.authority
    }
    #[must_use]
    pub fn path(&self) -> &str {
        &self.path
    }
    #[must_use]
    pub fn query(&self) -> Option<&str> {
        self.query.as_deref()
    }
}

pub(super) fn canonical_authority(scheme: Scheme, value: &str) -> Result<String, HttpError> {
    if value.is_empty() || value.len() > 255 || !value.is_ascii() {
        return Err(HttpError::InvalidTarget);
    }
    let (host, port) = if value.starts_with('[') {
        let (host, suffix) = value.split_once(']').ok_or(HttpError::InvalidTarget)?;
        let address: Ipv6Addr = host[1..].parse().map_err(|_| HttpError::InvalidTarget)?;
        let port = if suffix.is_empty() {
            None
        } else {
            Some(suffix.strip_prefix(':').ok_or(HttpError::InvalidTarget)?)
        };
        (format!("[{address}]"), port)
    } else {
        let (host, port) = value
            .split_once(':')
            .map_or((value, None), |(h, p)| (h, Some(p)));
        if host.is_empty() || host.ends_with('.') || host.len() > 253 {
            return Err(HttpError::InvalidTarget);
        }
        if host.bytes().all(|b| b.is_ascii_digit() || b == b'.') {
            let address: Ipv4Addr = host.parse().map_err(|_| HttpError::InvalidTarget)?;
            if address.to_string() != host {
                return Err(HttpError::InvalidTarget);
            }
        } else if host.split('.').any(|label| {
            label.is_empty()
                || label.len() > 63
                || label.starts_with('-')
                || label.ends_with('-')
                || !label
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'-')
        }) {
            return Err(HttpError::InvalidTarget);
        }
        (host.to_ascii_lowercase(), port)
    };
    let Some(port) = port else {
        return Ok(host);
    };
    let number = super::bounded::decimal(port)
        .filter(|n| *n > 0 && *n <= 65535)
        .ok_or(HttpError::InvalidTarget)?;
    if (scheme == Scheme::Http && number == 80) || (scheme == Scheme::Https && number == 443) {
        return Ok(host);
    }
    Ok(format!("{host}:{number}"))
}

fn unreserved(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'.' | b'_' | b'~')
}
fn hex(byte: u8) -> Result<u8, HttpError> {
    match byte {
        b'0'..=b'9' => Ok(byte - b'0'),
        b'a'..=b'f' => Ok(byte - b'a' + 10),
        b'A'..=b'F' => Ok(byte - b'A' + 10),
        _ => Err(HttpError::InvalidTarget),
    }
}
fn normalize(value: &str, query: bool) -> Result<String, HttpError> {
    let bytes = value.as_bytes();
    let mut result = String::new();
    result
        .try_reserve_exact(bytes.len())
        .map_err(|_| HttpError::AllocationFailed)?;
    let mut index = 0;
    while index < bytes.len() {
        let byte = bytes[index];
        if byte == b'%' {
            let pair = bytes
                .get(index + 1..index + 3)
                .ok_or(HttpError::InvalidTarget)?;
            let decoded = hex(pair[0])? * 16 + hex(pair[1])?;
            // Encoded separators and percent signs must not acquire a different
            // interpretation in a downstream URI decoder or filesystem adapter.
            if decoded < 32 || decoded == 127 || (!query && matches!(decoded, b'/' | b'\\' | b'%'))
            {
                return Err(HttpError::InvalidTarget);
            }
            if unreserved(decoded) {
                result.push(char::from(decoded));
            } else {
                result.push('%');
                result.push(char::from(pair[0].to_ascii_uppercase()));
                result.push(char::from(pair[1].to_ascii_uppercase()));
            }
            index += 3;
        } else {
            let pchar = unreserved(byte) || b"!$&'()*+,;=:@/".contains(&byte);
            if !(pchar || query && byte == b'?') {
                return Err(HttpError::InvalidTarget);
            }
            result.push(char::from(byte));
            index += 1;
        }
    }
    Ok(result)
}

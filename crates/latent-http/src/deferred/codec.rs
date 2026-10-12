use super::qualification::{digest, QualifiedHttpEndpoint, ENDPOINT_CONTRACT, MAXIMUM_REPLY_BYTES};
use crate::{protocol::ProtocolResponse, HttpError};
use serde::Deserialize;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum Answer {
    Accepted { sequence: u64, duplicate: bool },
    Absent,
    Conflict,
    Expired,
    Rejected,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Profile<'a> {
    format_version: u32,
    #[serde(borrow)]
    contract: &'a str,
    #[serde(borrow)]
    endpoint_incarnation: &'a str,
    retention_millis: u64,
    maximum_payload_bytes: usize,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Receipt<'a> {
    format_version: u32,
    #[serde(borrow)]
    endpoint_incarnation: &'a str,
    #[serde(borrow)]
    idempotency_key: &'a str,
    #[serde(borrow)]
    body_digest: &'a str,
    #[serde(borrow)]
    outcome: &'a str,
    sequence: u64,
    duplicate: bool,
}

pub(super) fn profile(
    response: &ProtocolResponse,
    bytes: &[u8],
    endpoint: &QualifiedHttpEndpoint,
) -> Result<(), HttpError> {
    headers(response, endpoint)?;
    bounded(bytes)?;
    let profile: Profile<'_> =
        serde_json::from_slice(bytes).map_err(|_| HttpError::ConnectionFailed)?;
    if response.status != 200
        || profile.format_version != 1
        || profile.contract != ENDPOINT_CONTRACT
        || profile.endpoint_incarnation != endpoint.endpoint_incarnation
        || profile.retention_millis != endpoint.retention_millis
        || profile.maximum_payload_bytes != endpoint.maximum_payload_bytes
    {
        return Err(HttpError::PermissionDenied);
    }
    Ok(())
}

pub(super) fn receipt(
    response: &ProtocolResponse,
    bytes: &[u8],
    endpoint: &QualifiedHttpEndpoint,
    key: &str,
    body_digest: &str,
    lookup: bool,
) -> Result<Answer, HttpError> {
    headers(response, endpoint)?;
    bounded(bytes)?;
    let reply: Receipt<'_> =
        serde_json::from_slice(bytes).map_err(|_| HttpError::ConnectionFailed)?;
    if reply.format_version != 1
        || reply.endpoint_incarnation != endpoint.endpoint_incarnation
        || reply.idempotency_key != key
        || !digest(reply.body_digest)
    {
        return Err(HttpError::PermissionDenied);
    }
    match (response.status, reply.outcome) {
        (200 | 201, "accepted")
            if reply.body_digest == body_digest
                && reply.sequence > 0
                && (!lookup || response.status == 200) =>
        {
            Ok(Answer::Accepted {
                sequence: reply.sequence,
                duplicate: reply.duplicate,
            })
        }
        (404, "absent")
            if lookup
                && reply.body_digest == body_digest
                && reply.sequence == 0
                && !reply.duplicate =>
        {
            Ok(Answer::Absent)
        }
        (409, "conflict") if reply.sequence == 0 && !reply.duplicate => Ok(Answer::Conflict),
        (410, "expired") if reply.sequence == 0 && !reply.duplicate => Ok(Answer::Expired),
        (422, "rejected")
            if !lookup
                && reply.body_digest == body_digest
                && reply.sequence == 0
                && !reply.duplicate =>
        {
            Ok(Answer::Rejected)
        }
        _ => Err(HttpError::ConnectionFailed),
    }
}

fn headers(response: &ProtocolResponse, endpoint: &QualifiedHttpEndpoint) -> Result<(), HttpError> {
    let get = |name| {
        let mut found = response
            .headers
            .iter()
            .filter(|(key, _)| key.eq_ignore_ascii_case(name));
        let value = found.next().map(|(_, value)| value.as_str());
        if found.next().is_some() {
            None
        } else {
            value
        }
    };
    if get("content-type") != Some("application/json")
        || get("lsf-endpoint-contract") != Some(ENDPOINT_CONTRACT)
        || get("lsf-endpoint-incarnation") != Some(endpoint.endpoint_incarnation.as_str())
        || get("lsf-idempotency-retention-millis").and_then(|v| v.parse::<u64>().ok())
            != Some(endpoint.retention_millis)
        || response
            .headers
            .iter()
            .filter(|(key, _)| key.eq_ignore_ascii_case("content-encoding"))
            .count()
            > 1
        || response
            .headers
            .iter()
            .any(|(key, value)| key.eq_ignore_ascii_case("content-encoding") && value != "identity")
        || response
            .headers
            .iter()
            .any(|(key, _)| key.eq_ignore_ascii_case("location"))
    {
        return Err(HttpError::PermissionDenied);
    }
    Ok(())
}

fn bounded(bytes: &[u8]) -> Result<(), HttpError> {
    if bytes.is_empty() || bytes.len() > MAXIMUM_REPLY_BYTES {
        return Err(HttpError::ResponseTooLarge);
    }
    let mut depth = 0u8;
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
                    depth = depth
                        .checked_add(1)
                        .filter(|depth| *depth <= 4)
                        .ok_or(HttpError::ResponseTooLarge)?;
                }
                b'}' | b']' => {
                    depth = depth.checked_sub(1).ok_or(HttpError::ConnectionFailed)?;
                }
                _ => (),
            }
        }
    }
    if quoted || depth != 0 {
        return Err(HttpError::ConnectionFailed);
    }
    Ok(())
}

use super::{exhausted, unauthenticated, Result, MAX_TOKEN_BYTES, MAX_TOKEN_RESPONSE_BYTES};
use reqwest::header::HeaderValue;
use serde::Deserialize;
use std::time::{Duration, SystemTime};
use time::{format_description::well_known::Rfc3339, OffsetDateTime};
use tokio::time::Instant;
use zeroize::Zeroize;

pub(super) const EXPIRY_SKEW: Duration = Duration::from_secs(5);
const MAX_LIFETIME: u64 = 3600;

pub(super) fn parse(
    body: &[u8],
    scope: &str,
    started: Instant,
    wall: SystemTime,
) -> Result<(HeaderValue, Instant)> {
    if body.len() > MAX_TOKEN_RESPONSE_BYTES {
        return Err(exhausted("oci-token-response-byte-limit"));
    }
    let document: TokenDocument =
        serde_json::from_slice(body).map_err(|_| unauthenticated("oci-token-response-invalid"))?;
    let token = match (
        document.token.as_deref().filter(|value| !value.is_empty()),
        document
            .access_token
            .as_deref()
            .filter(|value| !value.is_empty()),
    ) {
        (Some(token), None) | (None, Some(token)) => token,
        (Some(token), Some(alias)) if token == alias => token,
        _ => return Err(unauthenticated("oci-token-response-ambiguous")),
    };
    let seconds = document.expires_in.unwrap_or(60);
    if token.is_empty()
        || token.len() > MAX_TOKEN_BYTES
        || !token.bytes().all(|byte| byte.is_ascii_graphic())
        || !(6..=MAX_LIFETIME).contains(&seconds)
        || document
            .scope
            .as_deref()
            .is_some_and(|value| value != scope)
        || document.refresh_token.is_some()
    {
        return Err(unauthenticated("oci-token-response-outside-profile"));
    }
    let now = Instant::now();
    let lifetime = Duration::from_secs(seconds)
        .checked_sub(EXPIRY_SKEW)
        .ok_or_else(|| unauthenticated("oci-token-expiry-invalid"))?;
    let mut expires = started
        .checked_add(lifetime)
        .ok_or_else(|| unauthenticated("oci-token-expiry-invalid"))?;
    if let Some(issued) = document.issued_at.as_deref() {
        if issued.len() > 64 {
            return Err(unauthenticated("oci-token-issued-at-invalid"));
        }
        let issued = OffsetDateTime::parse(issued, &Rfc3339)
            .map_err(|_| unauthenticated("oci-token-issued-at-invalid"))?;
        let wall = OffsetDateTime::from(wall);
        if issued > wall + time::Duration::seconds(5) {
            return Err(unauthenticated("oci-token-issued-in-future"));
        }
        let expiry = issued
            .checked_add(time::Duration::seconds(
                i64::try_from(seconds).map_err(|_| unauthenticated("oci-token-expiry-invalid"))?,
            ))
            .ok_or_else(|| unauthenticated("oci-token-expiry-invalid"))?;
        let remaining = expiry - wall;
        let remaining =
            Duration::try_from(remaining).map_err(|_| unauthenticated("oci-token-expired"))?;
        let remaining = remaining
            .checked_sub(EXPIRY_SKEW)
            .ok_or_else(|| unauthenticated("oci-token-expired"))?;
        let issued_expiry = now
            .checked_add(remaining)
            .ok_or_else(|| unauthenticated("oci-token-expiry-invalid"))?;
        expires = expires.min(issued_expiry);
    }
    if expires <= now {
        return Err(unauthenticated("oci-token-expired"));
    }
    Ok((
        super::super::transport::client::bearer_authorization(token)?,
        expires,
    ))
}

#[derive(Deserialize)]
struct TokenDocument {
    #[serde(default, deserialize_with = "present")]
    token: Option<String>,
    #[serde(default, deserialize_with = "present")]
    access_token: Option<String>,
    #[serde(default, deserialize_with = "present")]
    expires_in: Option<u64>,
    #[serde(default, deserialize_with = "present")]
    issued_at: Option<String>,
    #[serde(default, deserialize_with = "present")]
    scope: Option<String>,
    #[serde(default, deserialize_with = "present")]
    refresh_token: Option<String>,
}

fn present<'de, Decoder, Value>(
    decoder: Decoder,
) -> std::result::Result<Option<Value>, Decoder::Error>
where
    Decoder: serde::Deserializer<'de>,
    Value: Deserialize<'de>,
{
    Value::deserialize(decoder).map(Some)
}

impl Drop for TokenDocument {
    fn drop(&mut self) {
        for token in [
            &mut self.token,
            &mut self.access_token,
            &mut self.refresh_token,
        ]
        .into_iter()
        .flatten()
        {
            token.zeroize();
        }
    }
}

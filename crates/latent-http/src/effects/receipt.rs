use super::contract::{hex_identity, WIRE_CONTRACT};
use crate::protocol::ProtocolResponse;
use serde::Deserialize;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct Receipt {
    contract: String,
    effect: String,
    body_sha256: String,
    provider_incarnation: String,
    retain_until_unix_millis: String,
    state: State,
    receipt: Option<String>,
}

#[derive(Deserialize)]
#[serde(rename_all = "kebab-case")]
enum State {
    Applied,
    Reserved,
}

pub(super) enum VerifiedReceipt {
    Applied(String),
    Reserved,
}

pub(super) fn verify(
    response: &ProtocolResponse,
    bytes: &[u8],
    effect: &str,
    body_sha256: &str,
    incarnation: &str,
    retain_until: u64,
) -> Option<VerifiedReceipt> {
    if !matches!(response.status, 200 | 201 | 202 | 503)
        || response.body_bytes != bytes.len()
        || response
            .headers
            .iter()
            .filter(|(name, _)| name == "content-type")
            .count()
            != 1
        || !response
            .headers
            .iter()
            .any(|(name, value)| name == "content-type" && value == "application/json")
        || response
            .headers
            .iter()
            .filter(|(name, _)| name == "cache-control")
            .count()
            != 1
        || !response
            .headers
            .iter()
            .any(|(name, value)| name == "cache-control" && value == "no-store")
        || response.headers.iter().any(|(name, _)| {
            matches!(
                name.as_str(),
                "location" | "content-encoding" | "set-cookie" | "www-authenticate"
            )
        })
    {
        return None;
    }
    let receipt: Receipt = serde_json::from_slice(bytes).ok()?;
    if receipt.contract != WIRE_CONTRACT
        || receipt.effect != effect
        || receipt.body_sha256 != body_sha256
        || receipt.provider_incarnation != incarnation
        || !hex_identity(&receipt.effect)
        || !hex_identity(&receipt.body_sha256)
        || !hex_identity(&receipt.provider_incarnation)
        || receipt.retain_until_unix_millis != retain_until.to_string()
    {
        return None;
    }
    match (response.status, receipt.state, receipt.receipt) {
        (200 | 201, State::Applied, Some(receipt)) if hex_identity(&receipt) => {
            Some(VerifiedReceipt::Applied(receipt))
        }
        (200 | 202 | 503, State::Reserved, None) => Some(VerifiedReceipt::Reserved),
        _ => None,
    }
}

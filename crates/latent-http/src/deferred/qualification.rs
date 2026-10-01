use crate::{destination, HttpError, HttpProviderConfig, HttpResolution};
use latent_policy::capability::HttpOrigin;
use serde::{Deserialize, Serialize};

/// Explicit operator approval of the documented atomic deduplication endpoint.
/// This metadata cannot certify an arbitrary HTTP API or client supplied URL.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct QualifiedHttpEndpoint {
    pub format_version: u32,
    pub origin: HttpOrigin,
    /// GET probes this exact path; POST performs this one approved operation.
    pub operation_path: String,
    /// GET of this prefix plus the fixed effect identity retrieves its record.
    pub lookup_prefix: String,
    /// The endpoint must compare this under its own durable mutation fence.
    pub endpoint_incarnation: String,
    pub retention_millis: u64,
    pub media_type: String,
    pub maximum_payload_bytes: usize,
}

pub const ENDPOINT_CONTRACT: &str = "lsf-atomic-idempotent-http-v1";
pub const MAXIMUM_REPLY_BYTES: usize = 2048;
pub const RESPONSE_RESERVATION_BYTES: u64 = 2048 + 2 * 8192 + 4096;

impl QualifiedHttpEndpoint {
    pub fn validate(&self, config: &HttpProviderConfig) -> Result<(), HttpError> {
        config.validate()?;
        if self.format_version != 1
            || config.destinations.len() != 1
            || self.origin != config.destinations[0].origin
            || self.origin.scheme != "https"
            || !matches!(
                config.destinations[0].resolution,
                HttpResolution::Static { .. }
            )
            || !config.destinations[0].redirect_destinations.is_empty()
            || config.limits.maximum_redirects != 0
            || !(11..=32).contains(&config.limits.maximum_headers)
            || config.limits.maximum_header_bytes < 4096
            || config.limits.maximum_header_bytes > 8192
            || config.limits.maximum_response_body_bytes < MAXIMUM_REPLY_BYTES
            || self.endpoint_incarnation.capacity() > 64
            || !digest(&self.endpoint_incarnation)
            || !(1000..=604_800_000).contains(&self.retention_millis)
            || !(1..=65536).contains(&self.maximum_payload_bytes)
            || self.maximum_payload_bytes > config.limits.maximum_request_body_bytes
            || self.operation_path.capacity() > 256
            || self.lookup_prefix.capacity() > 256
            || !path(&self.operation_path)
            || self.operation_path.ends_with('/')
            || !self.lookup_prefix.strip_suffix('/').is_some_and(path)
            || self.lookup_prefix.starts_with("//")
            || self.media_type.capacity() > 128
            || !matches!(
                self.media_type.as_str(),
                "application/octet-stream" | "application/json" | "text/plain"
            )
        {
            return Err(HttpError::InvalidRequest);
        }
        let origin = format!("https://{}:{}", self.origin.host, self.origin.port);
        if origin.len() + self.operation_path.len() > 256 {
            return Err(HttpError::InvalidRequest);
        }
        let target = destination::parse(&format!("{origin}{}", self.operation_path), config)?;
        if target.url.path() != self.operation_path || target.url.query().is_some() {
            return Err(HttpError::InvalidUrl);
        }
        let lookup = format!(
            "{origin}{}lsf-effect-{}",
            self.lookup_prefix,
            "0".repeat(64)
        );
        let target = destination::parse(&lookup, config)?;
        if target.url.query().is_some() {
            return Err(HttpError::InvalidUrl);
        }
        Ok(())
    }
}

fn path(path: &str) -> bool {
    path.starts_with('/')
        && path.len() <= 256
        && path.split('/').skip(1).all(|part| {
            !part.is_empty()
                && part != "."
                && part != ".."
                && part
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || b"_-".contains(&byte))
        })
}
pub(super) fn digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

use super::{text, BlobError, Result, PART_BYTES};
use latent_http::{HttpProviderConfig, HttpResolution};
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct S3Limits {
    pub maximum_object_bytes: usize,
    pub maximum_stages: usize,
    pub maximum_staging_bytes: usize,
    pub maximum_records: usize,
    /// Includes sealed objects and every unresolved remote upload reservation.
    pub maximum_remote_bytes: u64,
    pub maximum_handles: usize,
}
impl Default for S3Limits {
    fn default() -> Self {
        Self {
            maximum_object_bytes: 8 * 1024 * 1024,
            maximum_stages: 2,
            maximum_staging_bytes: 16 * 1024 * 1024,
            maximum_records: 64,
            maximum_remote_bytes: 256 * 1024 * 1024,
            maximum_handles: 64,
        }
    }
}
impl S3Limits {
    pub fn validate(self) -> Result<()> {
        if !(1..=32 * 1024 * 1024).contains(&self.maximum_object_bytes)
            || !(1..=8).contains(&self.maximum_stages)
            || self.maximum_staging_bytes < self.maximum_object_bytes
            || self.maximum_staging_bytes > 32 * 1024 * 1024
            || !(1..=128).contains(&self.maximum_records)
            || self.maximum_remote_bytes < self.maximum_object_bytes as u64
            || self.maximum_remote_bytes > 1024 * 1024 * 1024
            || !(1..=256).contains(&self.maximum_handles)
        {
            return Err(BlobError::InvalidRange);
        }
        Ok(())
    }
    pub(crate) fn parts(self) -> usize {
        self.maximum_object_bytes.div_ceil(PART_BYTES)
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct S3Config {
    pub format_version: u32,
    pub namespace: String,
    pub region: String,
    pub bucket: String,
    /// Relative ASCII segments ending in '/'. Guests never supply remote keys.
    pub prefix: String,
    pub transport: HttpProviderConfig,
    pub limits: S3Limits,
}
impl S3Config {
    pub fn validate(&self) -> Result<()> {
        self.limits.validate()?;
        self.transport.validate().map_err(super::http)?;
        if self.format_version != 1
            || !text(&self.namespace, 128)
            || self.namespace.capacity() > 128
            || !token(&self.region, 64)
            || self.region.capacity() > 64
            || !bucket(&self.bucket)
            || self.bucket.capacity() > 63
            || self.prefix.is_empty()
            || self.prefix.capacity() > 128
            || !self.prefix.ends_with('/')
            || self.prefix[..self.prefix.len() - 1]
                .split('/')
                .any(|v| !token(v, 63))
            || self.transport.destinations.len() != 1
            || self.transport.destinations[0].origin.scheme != "https"
            || !matches!(
                self.transport.destinations[0].resolution,
                HttpResolution::Static { .. }
            )
            || !self.transport.destinations[0]
                .redirect_destinations
                .is_empty()
            || !self.transport.destinations[0]
                .allowed_request_headers
                .is_empty()
            || self.transport.limits.maximum_redirects != 0
        {
            return Err(BlobError::InvalidRange);
        }
        Ok(())
    }
    pub(crate) fn host(&self) -> String {
        let origin = &self.transport.destinations[0].origin;
        if origin.host.contains(':') {
            format!("[{}]:{}", origin.host, origin.port)
        } else {
            format!("{}:{}", origin.host, origin.port)
        }
    }
    pub(crate) fn identity(&self) -> Result<String> {
        self.validate()?;
        Ok(super::sha(
            &serde_json::to_vec(self).map_err(|_| BlobError::InvalidRange)?,
        ))
    }
}
fn token(value: &str, maximum: usize) -> bool {
    !value.is_empty()
        && value.len() <= maximum
        && value
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
        && value.as_bytes()[0].is_ascii_alphanumeric()
        && value.as_bytes()[value.len() - 1].is_ascii_alphanumeric()
}
fn bucket(value: &str) -> bool {
    (3..=63).contains(&value.len())
        && token(value, 63)
        && !value.starts_with("xn--")
        && !value.ends_with("--x-s3")
}

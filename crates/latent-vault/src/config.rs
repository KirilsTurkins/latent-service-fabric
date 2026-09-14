use super::{Result, SecretError};
use latent_http::{HttpProviderConfig, HttpResolution};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct VaultLimits {
    pub maximum_value_bytes: usize,
    pub maximum_response_bytes: usize,
    /// Raw response/parser workspace and all actual retained value owners.
    pub maximum_plaintext_bytes: usize,
    pub maximum_cache_entries: usize,
    pub maximum_cache_bytes: usize,
    /// Freshness bound, not a dynamic Vault lease. Zero disables the cache.
    pub cache_ttl_millis: u64,
}
impl Default for VaultLimits {
    fn default() -> Self {
        Self {
            maximum_value_bytes: 16384,
            maximum_response_bytes: 65536,
            maximum_plaintext_bytes: 1024 * 1024,
            maximum_cache_entries: 16,
            maximum_cache_bytes: 256 * 1024,
            cache_ttl_millis: 5000,
        }
    }
}
#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum VaultEncoding {
    Utf8,
    Base64,
}
/// An exact operator allowlist row. No guest reference becomes a remote path.
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct VaultReference {
    pub tenant: String,
    pub reference: String,
    pub mount: String,
    pub path: String,
    pub field: String,
    /// None reads the current version; positive values pin an exact KV version.
    pub version: Option<u64>,
    pub encoding: VaultEncoding,
    pub media_type: String,
    /// Operator expiry, independent of KV's non-leased storage semantics.
    pub expires_at_unix_millis: Option<u64>,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct VaultConfig {
    pub format_version: u32,
    pub namespace: Option<String>,
    pub transport: HttpProviderConfig,
    pub limits: VaultLimits,
    pub references: Vec<VaultReference>,
}
fn path(value: &str, maximum: usize) -> bool {
    text(value, maximum)
        && value.split('/').all(|p| {
            !p.is_empty()
                && !matches!(p, "." | "..")
                && p.bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
        })
}
impl VaultConfig {
    pub fn validate(&self) -> Result<()> {
        let l = self.limits;
        if self.format_version != 1
            || !(1..=32768).contains(&l.maximum_value_bytes)
            || !(1024..=262_144).contains(&l.maximum_response_bytes)
            || l.maximum_response_bytes < l.maximum_value_bytes
            || !(65536..=4 * 1024 * 1024).contains(&l.maximum_plaintext_bytes)
            || l.maximum_plaintext_bytes
                < 3 * l.maximum_response_bytes + l.maximum_value_bytes + 65536
            || l.maximum_cache_entries > 16
            || l.maximum_cache_bytes > 512 * 1024
            || l.cache_ttl_millis > 60000
            || self
                .namespace
                .as_ref()
                .is_some_and(|n| n.capacity() > 128 || !path(n, 128))
            || self.references.is_empty()
            || self.references.capacity() > 16
        {
            return Err(SecretError::Unavailable);
        }
        self.transport
            .validate()
            .map_err(|_| SecretError::Unavailable)?;
        if self.transport.destinations.len() != 1
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
            return Err(SecretError::PermissionDenied);
        }
        for (index, r) in self.references.iter().enumerate() {
            if !text(&r.tenant, 128)
                || r.tenant.capacity() > 128
                || !text(&r.reference, 256)
                || r.reference.capacity() > 256
                || !r
                    .reference
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"-_.:/@".contains(&b))
                || !path(&r.mount, 128)
                || r.mount.capacity() > 128
                || !path(&r.path, 256)
                || r.path.capacity() > 256
                || !text(&r.field, 128)
                || r.field.capacity() > 128
                || !text(&r.media_type, 128)
                || r.media_type.capacity() > 128
                || r.version == Some(0)
                || self.references[..index]
                    .iter()
                    .any(|other| other.tenant == r.tenant && other.reference == r.reference)
            {
                return Err(SecretError::PermissionDenied);
            }
        }
        Ok(())
    }
    pub(super) fn identity(&self) -> Result<String> {
        self.validate()?;
        let encoded = serde_json::to_vec(self).map_err(|_| SecretError::Unavailable)?;
        Ok(format!("sha256:{:x}", Sha256::digest(&encoded)))
    }
    pub(super) fn host(&self) -> String {
        let o = &self.transport.destinations[0].origin;
        if o.host.contains(':') {
            format!("[{}]:{}", o.host, o.port)
        } else {
            format!("{}:{}", o.host, o.port)
        }
    }
}

pub(crate) fn text(value: &str, maximum: usize) -> bool {
    !value.is_empty() && value.len() <= maximum && value.bytes().all(|b| (0x21..=0x7e).contains(&b))
}

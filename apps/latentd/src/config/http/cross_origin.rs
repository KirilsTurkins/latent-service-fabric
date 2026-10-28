//! Closed operator grants. Origin is a browser read policy, never a principal.
use super::{invalid, Authentication, CanonicalTarget, HttpIngressConfig, PlatformError, Scheme};
use latent_artifacts::{LifecycleScope, PublicationRef};
use latent_core::TenantId;
use serde::{Deserialize, Serialize};
use std::{collections::BTreeSet, io, net::Ipv4Addr};

#[cfg(test)]
mod tests;

pub(crate) const MAX_GRANTS: usize = 32;
pub(crate) const MAX_ORIGINS: usize = 16;
pub(crate) const MAX_ORIGIN_BYTES: usize = 512;
pub(crate) const MAX_CONFIGURATION_BYTES: usize = 64 * 1024;

#[derive(Clone, Copy, Debug, Default, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum CrossOriginCredentials {
    #[default]
    Omit,
    Include,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CrossOriginAssetGrant {
    pub authority: String,
    pub tenant: String,
    pub publication: String,
    pub origins: Vec<String>,
    #[serde(default)]
    pub credentials: CrossOriginCredentials,
}

impl CrossOriginAssetGrant {
    pub(crate) fn caller(&self, authority: &str, tenant: &str, origin: &str) -> Option<&str> {
        if self.authority != authority || self.tenant != tenant {
            return None;
        }
        self.origins
            .iter()
            .find(|approved| approved.as_str() == origin)
            .map(String::as_str)
    }
}

pub(super) fn validate(
    http: &HttpIngressConfig,
    scheme: Scheme,
    authentication: &Authentication,
) -> Result<(), PlatformError> {
    let grants = &http.cross_origin_assets;
    if grants.is_empty() {
        return Ok(());
    }
    let Authentication::PublicOrigins(owners) = authentication else {
        return Err(invalid("httpIngress.crossOriginAssets"));
    };
    if scheme != Scheme::Https || grants.len() > MAX_GRANTS {
        return Err(invalid("httpIngress.crossOriginAssets"));
    }
    let mut unique = BTreeSet::new();
    for grant in grants {
        let target = CanonicalTarget::parse(Scheme::Https, &grant.authority, "/")
            .map_err(|_| invalid("httpIngress.crossOriginAssets.authority"))?;
        let reference = PublicationRef {
            id: grant
                .publication
                .parse()
                .map_err(|_| invalid("httpIngress.crossOriginAssets.publication"))?,
            scope: LifecycleScope::Tenant(TenantId(grant.tenant.clone())),
        };
        let mut origins = BTreeSet::new();
        if target.authority() != grant.authority
            || reference.id.as_str() != grant.publication
            || grant.tenant.is_empty()
            || grant.tenant.len() > 256
            || grant.tenant.chars().any(char::is_control)
            || !unique.insert((&grant.authority, &grant.tenant, &grant.publication))
            || grant.origins.is_empty()
            || grant.origins.len() > MAX_ORIGINS
            || grant
                .origins
                .iter()
                .any(|origin| !canonical_origin(origin) || !origins.insert(origin))
            || !owners.iter().any(|(authority, principal)| {
                authority == &grant.authority
                    && principal
                        .tenant
                        .as_ref()
                        .is_some_and(|tenant| tenant.0 == grant.tenant)
            })
        {
            return Err(invalid("httpIngress.crossOriginAssets"));
        }
    }
    // Count the complete compact policy encoding without allocating another
    // policy-sized buffer. Bounds above also cap all serialization work.
    serde_json::to_writer(ConfigurationBytes(0), grants)
        .map_err(|_| invalid("httpIngress.crossOriginAssets.bytes"))
}

fn canonical_origin(origin: &str) -> bool {
    if origin.len() > MAX_ORIGIN_BYTES || !origin.is_ascii() {
        return false;
    }
    let Some(authority) = origin.strip_prefix("https://") else {
        return false;
    };
    let Ok(target) = CanonicalTarget::parse(Scheme::Https, authority, "/") else {
        return false;
    };
    if target.authority() != authority {
        return false;
    }
    if authority.starts_with('[') {
        // The shared authority parser supplies canonical RFC 5952 spelling.
        // Dotted embedded IPv4 spellings are not browser Origin serialization.
        return !authority.contains('.');
    }
    let host = authority.split(':').next().unwrap_or_default();
    let last = host.rsplit('.').next().unwrap_or_default();
    // WHATWG interprets domains ending in a number as IPv4. Reject legacy
    // hex/octal/short addresses rather than approving an alias a browser rewrites.
    let numeric = last.bytes().all(|byte| byte.is_ascii_digit())
        || last.strip_prefix("0x").is_some_and(|suffix| {
            suffix.is_empty() || suffix.bytes().all(|byte| byte.is_ascii_hexdigit())
        });
    !numeric
        || host
            .parse::<Ipv4Addr>()
            .is_ok_and(|ip| ip.to_string() == host)
}

struct ConfigurationBytes(usize);
impl io::Write for ConfigurationBytes {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if bytes.len() > MAX_CONFIGURATION_BYTES.saturating_sub(self.0) {
            return Err(io::ErrorKind::InvalidInput.into());
        }
        self.0 += bytes.len();
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

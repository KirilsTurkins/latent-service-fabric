use super::{invalid, Result};
use latent_artifacts::package::PackageLimits;
use std::{fmt, net::SocketAddr, time::Duration};

/// Explicit origin/repository-scoped credentials. Debug never renders their bytes.
pub enum RegistryCredentials {
    Anonymous,
    Basic { username: String, password: String },
    Bearer(String),
}
impl fmt::Debug for RegistryCredentials {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::Anonymous => "Anonymous",
            Self::Basic { .. } => "Basic([redacted])",
            Self::Bearer(_) => "Bearer([redacted])",
        })
    }
}

pub struct RegistryConfig {
    /// Origin only, e.g. <https://registry.example:443>. No path, query or userinfo.
    pub origin: String,
    pub repository: String,
    pub credentials: RegistryCredentials,
    /// Required for hostname origins; bounds resolution work without runtime DNS.
    pub addresses: Vec<SocketAddr>,
    /// Additional operator-approved TLS roots in DER, at most 8 x 64 KiB.
    pub additional_root_certificates: Vec<Vec<u8>>,
    /// Permits HTTP only for a numeric loopback address. Intended for local tests.
    pub allow_insecure_loopback: bool,
    pub limits: RegistryLimits,
}
impl fmt::Debug for RegistryConfig {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("RegistryConfig")
            .field("credentials", &self.credentials)
            .field("address_count", &self.addresses.len())
            .field(
                "additional_root_count",
                &self.additional_root_certificates.len(),
            )
            .field("limits", &self.limits)
            .finish_non_exhaustive()
    }
}

#[derive(Debug, Clone, Copy)]
pub struct RegistryLimits {
    pub package: PackageLimits,
    pub max_in_flight: usize,
    pub max_retained_packages: usize,
    /// Raw bytes held by active operations or high-level returned package leases.
    /// Caller-retained low-level Vec results are outside this adapter's ownership.
    pub max_retained_bytes: u32,
    pub max_referrer_pages: usize,
    pub max_referrers: usize,
    pub max_referrer_total_bytes: usize,
    pub connect_timeout: Duration,
    pub request_timeout: Duration,
    pub operation_timeout: Duration,
    pub cleanup_timeout: Duration,
}
impl Default for RegistryLimits {
    fn default() -> Self {
        Self {
            package: PackageLimits::default(),
            max_in_flight: 4,
            max_retained_packages: 2,
            max_retained_bytes: 512 * 1024 * 1024,
            max_referrer_pages: 8,
            max_referrers: 256,
            max_referrer_total_bytes: 1024 * 1024,
            connect_timeout: Duration::from_secs(5),
            request_timeout: Duration::from_secs(30),
            operation_timeout: Duration::from_mins(5),
            cleanup_timeout: Duration::from_secs(5),
        }
    }
}
impl RegistryLimits {
    pub(crate) fn validate(self) -> Result<()> {
        self.package.validate()?;
        if self.max_in_flight == 0
            || self.max_in_flight > 32
            || self.max_retained_packages == 0
            || self.max_retained_packages > 8
            || self.max_retained_bytes == 0
            || self.max_retained_bytes > 2 * 1024 * 1024 * 1024
            || self.max_referrer_pages == 0
            || self.max_referrer_pages > 16
            || self.max_referrers == 0
            || self.max_referrers > 1024
            || self.max_referrer_total_bytes == 0
            || self.max_referrer_total_bytes > 4 * 1024 * 1024
        {
            return Err(invalid("invalid-oci-limits"));
        }
        for (duration, max) in [
            (self.connect_timeout, 30),
            (self.request_timeout, 120),
            (self.operation_timeout, 600),
            (self.cleanup_timeout, 30),
        ] {
            if duration.is_zero() || duration > Duration::from_secs(max) {
                return Err(invalid("invalid-oci-deadline"));
            }
        }
        Ok(())
    }
}

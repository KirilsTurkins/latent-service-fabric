use super::security_headers;
use crate::http::{headers, Scheme};

pub const OWNERSHIP_PROFILE: &str = "latent.browser.response-ownership.v1";
pub(super) const FORBIDDEN_BROWSER: &[&str] = &[
    "refresh",
    "content-location",
    "link",
    "clear-site-data",
    "report-to",
    "nel",
    "content-security-policy-report-only",
    "cross-origin-embedder-policy",
];
pub(super) const CONDITIONAL: &[&str] = &["location", "content-encoding", "set-cookie", "vary"];
pub(super) const HOST_CACHE: &[&str] = &["cache-control", "age"];
pub(super) const SENSITIVE_ALLOWED: &[&str] = &[
    "cookie",
    "www-authenticate",
    "proxy-authenticate",
    "authentication-info",
    "proxy-authentication-info",
];

/// Discovery only: this does not grant a field, validate its value, or change
/// wire names. Guest wire names must still be canonical lowercase HTTP tokens.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HeaderOwnership {
    HostSecurity,
    HostTransport,
    ForbiddenHopByHop,
    ForbiddenIdentity,
    ForbiddenPlatform,
    ForbiddenBrowserPolicy,
    Conditional,
    HostCacheInput,
    CredentialSensitiveAllowed,
    GuestAllowed,
}

#[must_use]
pub fn header_ownership(name: &str) -> HeaderOwnership {
    let contains = |values: &[&str]| values.iter().any(|value| name.eq_ignore_ascii_case(value));
    if security_headers(Scheme::Https).any(|owned| name.eq_ignore_ascii_case(owned.name)) {
        HeaderOwnership::HostSecurity
    } else if contains(headers::HOST_RESPONSE_FIELDS) {
        HeaderOwnership::HostTransport
    } else if contains(headers::HOP_BY_HOP) {
        HeaderOwnership::ForbiddenHopByHop
    } else if headers::private_input(name) {
        HeaderOwnership::ForbiddenIdentity
    } else if headers::prefix(name, "x-lsf-") {
        HeaderOwnership::ForbiddenPlatform
    } else if contains(FORBIDDEN_BROWSER) || headers::prefix(name, "access-control-") {
        HeaderOwnership::ForbiddenBrowserPolicy
    } else if contains(CONDITIONAL) {
        HeaderOwnership::Conditional
    } else if contains(HOST_CACHE) {
        HeaderOwnership::HostCacheInput
    } else if contains(SENSITIVE_ALLOWED) {
        HeaderOwnership::CredentialSensitiveAllowed
    } else {
        HeaderOwnership::GuestAllowed
    }
}

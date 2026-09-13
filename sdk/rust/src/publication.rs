//! Additive publication models. IDs are never authority; legacy digests remain
//! component identities. These models do not implement management transports.
use latent_core::{PackageDigest, PublicationId, ReleaseDigest, TenantId};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicationRef {
    pub id: PublicationId,
    pub tenant: TenantId,
}

/// Exactly one selector must be populated at a validated request boundary.
/// Both/empty values stay representable for rejection, never normalized.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReleaseSelector {
    pub component_digest: Option<ReleaseDigest>,
    pub publication: Option<PublicationRef>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicationIdentity {
    pub publication: PublicationRef,
    pub component_digest: ReleaseDigest,
    pub package_digest: PackageDigest,
}

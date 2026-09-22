//! Publication models. IDs are never authority; digests identify component bytes. These models do not implement management transports.
use latent_core::{PackageDigest, PublicationId, ReleaseDigest, TenantId};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicationRef {
    pub id: PublicationId,
    pub tenant: TenantId,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicationIdentity {
    pub publication: PublicationRef,
    pub component_digest: ReleaseDigest,
    pub package_digest: PackageDigest,
}

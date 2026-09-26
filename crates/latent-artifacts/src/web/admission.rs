use super::CheckedWebLayout;
use crate::{AdmissionRecheck, PackageAdmissionUpload, ReleasePolicyIdentity};
use latent_core::{ArtifactBlobDigest, PackageDigest, PlatformError, TenantId};
use std::{any::Any, sync::Arc};

/// Componentless historical admission data. The configured authority validates
/// these associations and the receipt; deserialization never grants access.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WebAdmissionBinding {
    pub tenant: TenantId,
    pub package: PackageDigest,
    pub manifest: ArtifactBlobDigest,
    pub assets: ArtifactBlobDigest,
    pub receipt: Vec<u8>,
}

/// Only the node's configured host authority may supply repository grants.
/// Publisher/build proofs and bounded policy/clock ownership remain live.
pub trait WebAdmissionGrant: Send + Sync {
    fn as_any(&self) -> &dyn Any;
    fn binding(&self) -> &WebAdmissionBinding;
    fn policy_identity(&self) -> Option<ReleasePolicyIdentity> {
        None
    }
    fn retained_bytes(&self) -> usize;
    fn check_current(&self) -> Result<(), PlatformError>;
    fn with_current(
        &self,
        action: &mut dyn FnMut(&dyn AdmissionRecheck) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError>;
}

/// Return value of the configured authority, never an externally accepted
/// publication parameter. The repository still validates exact associations.
pub struct VerifiedWebAdmission {
    pub layout: CheckedWebLayout,
    pub upload: PackageAdmissionUpload,
    pub grant: Arc<dyn WebAdmissionGrant>,
}

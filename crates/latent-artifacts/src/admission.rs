//! Host-injected supply-chain authority; uploaded and persisted data are untrusted.

mod eligibility;
mod limits;

pub(crate) use eligibility::EligibilityOwner;
pub use eligibility::ReleaseEligibility;
pub use limits::AdmissionStorageLimits;

use std::sync::Arc;

use latent_core::{PackageDigest, PlatformError, ReleaseDigest, TenantId};

use crate::CapsuleArtifact;

/// Exact raw detached evidence. Referrer association does not confer authority.
#[derive(Debug)]
pub struct AdmissionEvidence {
    pub manifest: Vec<u8>,
    pub configuration: Vec<u8>,
    pub payload: Vec<u8>,
}

/// Untrusted bounded package upload; the authenticated tenant is separate.
#[derive(Debug)]
pub struct PackageAdmissionUpload {
    pub manifest: Vec<u8>,
    pub configuration: Vec<u8>,
    pub layers: Vec<(String, Vec<u8>)>,
    pub signatures: Vec<AdmissionEvidence>,
    pub provenance: Vec<AdmissionEvidence>,
    pub sboms: Vec<AdmissionEvidence>,
}

/// Historical admission data, never a grant. The configured authority validates
/// the closed receipt profile and every identity on verification and recovery.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AdmissionBinding {
    pub tenant: TenantId,
    pub package: PackageDigest,
    pub release: ReleaseDigest,
    pub receipt: Vec<u8>,
}

/// A checker valid only inside one synchronous authority fence. The repository
/// invokes it before rename and again after synchronization before adoption.
pub trait AdmissionRecheck {
    fn check(&self) -> Result<(), PlatformError>;
    fn check_grant(&self, _grant: &dyn AdmissionGrant) -> Result<(), PlatformError> {
        Err(latent_core::PlatformError {
            code: latent_core::PlatformErrorCode::IncompatibleContract,
            message: "admission-batch-check-unsupported".to_owned(),
            retryable: false,
            details: Vec::new(),
        })
    }
}

/// Implemented by the configured trusted host authority, not request providers.
/// Its returned identity remains historical; currentness consults the live owner.
pub trait AdmissionGrant: Send + Sync {
    fn as_any(&self) -> &dyn std::any::Any;
    fn binding(&self) -> &AdmissionBinding;

    /// Bounded diagnostic identity captured by this verified proof. It is never
    /// used as authority and does not refresh the proof or trusted clock.
    fn policy_identity(&self) -> Option<crate::ReleasePolicyIdentity> {
        None
    }

    /// Conservative retained bytes including this grant's owned/shared proof data.
    fn retained_bytes(&self) -> usize;

    /// Nonblocking, no I/O, no renewal waits; expired/busy/retired state fails.
    fn check_current(&self) -> Result<(), PlatformError>;

    /// Holds the common policy/time fence through the callback. No awaits,
    /// reentry, arbitrary verifier mutation or request-controlled time samples.
    fn with_current(
        &self,
        action: &mut dyn FnMut(&dyn AdmissionRecheck) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError>;
}

/// Data returned only by the repository's configured authority invocation.
/// There is deliberately no repository publication API accepting this value.
pub struct VerifiedAdmission {
    pub artifact: CapsuleArtifact,
    pub upload: PackageAdmissionUpload,
    pub grant: Arc<dyn AdmissionGrant>,
}

/// Host configuration authority. Implementations own bounded crypto/policy work
/// and never accept stored receipt fields as substitutes for verification.
pub trait AdmissionAuthority: Send + Sync {
    fn verify(
        &self,
        tenant: &TenantId,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError>;

    fn recover(
        &self,
        binding: &AdmissionBinding,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError>;
}

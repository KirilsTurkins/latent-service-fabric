use std::fmt;
use std::hash::{Hash, Hasher};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

use latent_core::{PackageDigest, PlatformError, PlatformErrorCode, ReleaseDigest, TenantId};
use sha2::{Digest, Sha256};

use super::{AdmissionAuthority, AdmissionBinding, AdmissionGrant, AdmissionRecheck};

pub(crate) struct EligibilityOwner {
    live: AtomicBool,
    authority: Arc<dyn AdmissionAuthority>,
}

impl EligibilityOwner {
    pub(crate) fn new(authority: Arc<dyn AdmissionAuthority>) -> Self {
        Self {
            live: AtomicBool::new(true),
            authority,
        }
    }
    pub(crate) fn retire(&self) {
        self.live.store(false, Ordering::Release);
    }
    fn check(&self) -> Result<(), PlatformError> {
        if self.live.load(Ordering::Acquire) {
            Ok(())
        } else {
            Err(PlatformError {
                code: PlatformErrorCode::Unavailable,
                message: "admission-repository-retired".to_owned(),
                retryable: false,
                details: Vec::new(),
            })
        }
    }
}

/// Sealed repository-issued currentness capability, independent of cache stamps.
/// Its owner epoch does not retain the catalog root lock or an execution resource.
/// The shared host authority controls its own durable lock until retirement.
#[derive(Clone)]
pub struct ReleaseEligibility {
    pub(crate) grant: Arc<dyn AdmissionGrant>,
    owner: Arc<EligibilityOwner>,
    identity: [u8; 32],
}

impl ReleaseEligibility {
    pub(crate) fn new(grant: Arc<dyn AdmissionGrant>, owner: Arc<EligibilityOwner>) -> Self {
        let binding = grant.binding();
        let mut hash = Sha256::new();
        hash.update(b"lsf-release-eligibility-v1\0");
        for part in [
            binding.tenant.0.as_bytes(),
            binding.package.as_str().as_bytes(),
            binding.release.0.as_bytes(),
            binding.receipt.as_slice(),
        ] {
            hash.update((part.len() as u64).to_le_bytes());
            hash.update(part);
        }
        Self {
            grant,
            owner,
            identity: hash.finalize().into(),
        }
    }

    #[must_use]
    pub fn binding(&self) -> &AdmissionBinding {
        self.grant.binding()
    }
    #[must_use]
    pub fn tenant(&self) -> &TenantId {
        &self.binding().tenant
    }
    #[must_use]
    pub fn package(&self) -> &PackageDigest {
        &self.binding().package
    }
    #[must_use]
    pub fn release(&self) -> &ReleaseDigest {
        &self.binding().release
    }
    #[must_use]
    pub const fn identity(&self) -> &[u8; 32] {
        &self.identity
    }
    /// Process-local lookup digest; consumers still compare the exact token.
    #[must_use]
    pub fn cache_digest(&self) -> [u8; 32] {
        let mut hash = Sha256::new();
        hash.update(b"lsf-release-eligibility-cache-v1\0");
        hash.update((Arc::as_ptr(&self.owner) as usize).to_le_bytes());
        hash.update((Arc::as_ptr(&self.grant).cast::<()>() as usize).to_le_bytes());
        hash.update(self.identity);
        hash.finalize().into()
    }
    #[must_use]
    pub fn retained_bytes(&self) -> usize {
        std::mem::size_of::<Self>()
            .saturating_add(64)
            .saturating_add(self.grant.retained_bytes())
    }

    pub fn check_current(&self) -> Result<(), PlatformError> {
        self.owner.check()?;
        self.grant.check_current()
    }

    pub fn check_for_authority(
        &self,
        authority: &Arc<dyn AdmissionAuthority>,
    ) -> Result<(), PlatformError> {
        if !Arc::ptr_eq(&self.owner.authority, authority) {
            return Err(PlatformError {
                code: PlatformErrorCode::PermissionDenied,
                message: "admission-authority-mismatch".to_owned(),
                retryable: false,
                details: Vec::new(),
            });
        }
        self.check_current()
    }

    /// Exact configured owner identity, without acquiring or renewing trust.
    #[must_use]
    pub fn belongs_to_authority(&self, authority: &Arc<dyn AdmissionAuthority>) -> bool {
        Arc::ptr_eq(&self.owner.authority, authority)
    }

    /// Checks this private grant using an already-held common authority fence.
    pub fn check_with(&self, checker: &dyn AdmissionRecheck) -> Result<(), PlatformError> {
        self.owner.check()?;
        checker.check_grant(self.grant.as_ref())
    }

    /// One non-reentrant fence for a bounded caller-owned release set. Empty
    /// local-mode batches must be handled by the explicitly local caller.
    pub fn with_all_current(
        entries: &[Self],
        action: &mut dyn FnMut(&dyn AdmissionRecheck) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        let first = entries.first().ok_or_else(|| PlatformError {
            code: PlatformErrorCode::InvalidArgument,
            message: "empty-admission-batch".to_owned(),
            retryable: false,
            details: Vec::new(),
        })?;
        for entry in entries {
            entry.owner.check()?;
        }
        first.grant.with_current(&mut |checker| {
            let checked = BatchRecheck { entries, checker };
            checked.check()?;
            action(&checked)
        })
    }

    /// The callback is the guarded start/commit decision, not literal CPU entry.
    /// An accepted activation may finish after subsequent trust changes.
    pub fn with_current(
        &self,
        action: &mut dyn FnMut(&dyn AdmissionRecheck) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        self.owner.check()?;
        self.grant.with_current(&mut |checker| {
            let checked = OwnerRecheck {
                owner: &self.owner,
                checker,
            };
            checked.check()?;
            action(&checked)
        })
    }
}

struct OwnerRecheck<'a> {
    owner: &'a EligibilityOwner,
    checker: &'a dyn AdmissionRecheck,
}
impl AdmissionRecheck for OwnerRecheck<'_> {
    fn check(&self) -> Result<(), PlatformError> {
        self.owner.check()?;
        self.checker.check()
    }
    fn check_grant(&self, grant: &dyn AdmissionGrant) -> Result<(), PlatformError> {
        self.owner.check()?;
        self.checker.check_grant(grant)
    }
}

struct BatchRecheck<'a> {
    entries: &'a [ReleaseEligibility],
    checker: &'a dyn AdmissionRecheck,
}
impl AdmissionRecheck for BatchRecheck<'_> {
    fn check(&self) -> Result<(), PlatformError> {
        self.checker.check()?;
        for entry in self.entries {
            entry.check_with(self.checker)?;
        }
        Ok(())
    }
    fn check_grant(&self, grant: &dyn AdmissionGrant) -> Result<(), PlatformError> {
        self.check()?;
        self.checker.check_grant(grant)
    }
}

impl fmt::Debug for ReleaseEligibility {
    fn fmt(&self, output: &mut fmt::Formatter<'_>) -> fmt::Result {
        output
            .debug_struct("ReleaseEligibility")
            .field("package", self.package())
            .field("release", self.release())
            .finish_non_exhaustive()
    }
}
impl PartialEq for ReleaseEligibility {
    fn eq(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.owner, &other.owner)
            && Arc::ptr_eq(&self.grant, &other.grant)
            && self.identity == other.identity
    }
}
impl Eq for ReleaseEligibility {}
impl Hash for ReleaseEligibility {
    fn hash<H: Hasher>(&self, state: &mut H) {
        std::ptr::hash(Arc::as_ptr(&self.owner), state);
        std::ptr::hash(Arc::as_ptr(&self.grant).cast::<()>(), state);
        self.identity.hash(state);
    }
}

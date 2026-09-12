use super::{LifecycleScope, ReleaseLifecycleRecord, ReleaseLifecycleState};
use crate::{AdmissionAuthority, AdmissionRecheck, ReleaseEligibility};
use latent_core::{PackageDigest, PlatformError, PlatformErrorCode, ReleaseDigest, TenantId};
use sha2::{Digest, Sha256};
use std::{
    fmt,
    hash::{Hash, Hasher},
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Arc, RwLock, RwLockReadGuard, RwLockWriteGuard,
    },
};

/// Compact decision owner. It deliberately owns no catalog maps, files or lock.
pub(super) struct Owner {
    pub(super) fence: RwLock<()>,
    live: AtomicBool,
    healthy: AtomicBool,
    authority: Option<Arc<dyn AdmissionAuthority>>,
}
impl Owner {
    pub(super) fn new(authority: Option<Arc<dyn AdmissionAuthority>>) -> Arc<Self> {
        Arc::new(Self {
            fence: RwLock::new(()),
            live: AtomicBool::new(true),
            healthy: AtomicBool::new(true),
            authority,
        })
    }
    pub(super) fn check(&self) -> Result<(), PlatformError> {
        if !self.live.load(Ordering::Acquire) || !self.healthy.load(Ordering::Acquire) {
            Err(super::unavailable())
        } else {
            Ok(())
        }
    }
    pub(super) fn read(&self) -> Result<RwLockReadGuard<'_, ()>, PlatformError> {
        self.check()?;
        let guard = self.fence.try_read().map_err(super::lock_error)?;
        self.check()?;
        Ok(guard)
    }
    pub(super) fn write(&self) -> Result<RwLockWriteGuard<'_, ()>, PlatformError> {
        self.check()?;
        let guard = self.fence.try_write().map_err(super::lock_error)?;
        self.check()?;
        Ok(guard)
    }
    pub(super) fn poison(&self) {
        self.healthy.store(false, Ordering::Release);
    }
    pub(super) fn retire(&self) {
        self.live.store(false, Ordering::Release);
    }
}
#[derive(Clone)]
pub struct LifecycleAuthorityHandle {
    pub(super) owner: Arc<Owner>,
}
impl LifecycleAuthorityHandle {
    #[must_use]
    pub fn same_owner(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.owner, &other.owner)
    }
    #[must_use]
    pub fn required_authority(&self) -> Option<&Arc<dyn AdmissionAuthority>> {
        self.owner.authority.as_ref()
    }
    #[must_use]
    pub fn retained_bytes(&self) -> usize {
        std::mem::size_of::<Self>() + std::mem::size_of::<Owner>() + 64
    }
}
impl fmt::Debug for LifecycleAuthorityHandle {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("LifecycleAuthorityHandle")
            .field("enforced", &self.owner.authority.is_some())
            .finish_non_exhaustive()
    }
}
impl PartialEq for LifecycleAuthorityHandle {
    fn eq(&self, other: &Self) -> bool {
        self.same_owner(other)
    }
}
impl Eq for LifecycleAuthorityHandle {}

pub(super) struct Row {
    pub(super) scope: LifecycleScope,
    pub(super) release: ReleaseDigest,
    pub(super) package: Option<PackageDigest>,
    allowed_generation: AtomicU64,
}
impl Row {
    pub(super) fn new(record: &ReleaseLifecycleRecord) -> Arc<Self> {
        Arc::new(Self {
            scope: record.scope.clone(),
            release: record.release.clone(),
            package: record.package.clone(),
            allowed_generation: AtomicU64::new(
                if record.state == ReleaseLifecycleState::Admitted {
                    record.generation
                } else {
                    0
                },
            ),
        })
    }
    pub(super) fn adopt(&self, record: &ReleaseLifecycleRecord) {
        self.allowed_generation.store(
            if record.state == ReleaseLifecycleState::Admitted {
                record.generation
            } else {
                0
            },
            Ordering::Release,
        );
    }
}
/// Sealed generation capability, independent of publisher/builder proofs.
#[derive(Clone)]
pub struct LifecycleEligibility {
    pub(super) owner: Arc<Owner>,
    pub(super) row: Arc<Row>,
    pub(super) generation: u64,
}
impl LifecycleEligibility {
    #[must_use]
    pub fn scope(&self) -> &LifecycleScope {
        &self.row.scope
    }
    #[must_use]
    pub fn release(&self) -> &ReleaseDigest {
        &self.row.release
    }
    #[must_use]
    pub fn package(&self) -> Option<&PackageDigest> {
        self.row.package.as_ref()
    }
    #[must_use]
    pub fn generation(&self) -> u64 {
        self.generation
    }
    pub fn check_current(&self) -> Result<(), PlatformError> {
        self.owner.check()?;
        if self.generation == 0
            || self.row.allowed_generation.load(Ordering::Acquire) != self.generation
        {
            Err(super::error(
                PlatformErrorCode::PermissionDenied,
                "release-lifecycle-ineligible",
            ))
        } else {
            Ok(())
        }
    }
    #[must_use]
    pub fn belongs_to_catalog(&self, handle: &LifecycleAuthorityHandle) -> bool {
        Arc::ptr_eq(&self.owner, &handle.owner)
    }
    #[must_use]
    pub fn retained_bytes(&self) -> usize {
        std::mem::size_of::<Self>()
            + std::mem::size_of::<Owner>()
            + std::mem::size_of::<Row>()
            + 128
            + self.row.release.0.capacity()
            + self
                .row
                .scope
                .tenant()
                .map_or(0, |tenant| tenant.0.capacity())
            + self
                .row
                .package
                .as_ref()
                .map_or(0, |value| value.as_str().len())
    }
}
impl fmt::Debug for LifecycleEligibility {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("LifecycleEligibility")
            .field("release", self.release())
            .field("generation", &self.generation)
            .finish_non_exhaustive()
    }
}
impl PartialEq for LifecycleEligibility {
    fn eq(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.owner, &other.owner)
            && Arc::ptr_eq(&self.row, &other.row)
            && self.generation == other.generation
    }
}
impl Eq for LifecycleEligibility {}
impl Hash for LifecycleEligibility {
    fn hash<H: Hasher>(&self, state: &mut H) {
        std::ptr::hash(Arc::as_ptr(&self.owner), state);
        std::ptr::hash(Arc::as_ptr(&self.row), state);
        self.generation.hash(state);
    }
}

/// A final start/commit checker, valid only inside its non-reentrant fence.
pub trait ReleaseUseRecheck {
    fn check(&self) -> Result<(), PlatformError>;
    fn check_eligibility(&self, eligibility: &ReleaseUseEligibility) -> Result<(), PlatformError>;
}
/// The catalog lifecycle capability and the optional real signing proof travel
/// together. Public callers cannot manufacture an admitted composite.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct ReleaseUseEligibility {
    lifecycle: LifecycleEligibility,
    admission: Option<ReleaseEligibility>,
}
impl ReleaseUseEligibility {
    pub(super) fn new(
        lifecycle: LifecycleEligibility,
        admission: Option<ReleaseEligibility>,
    ) -> Result<Self, PlatformError> {
        match (&lifecycle.owner.authority, &admission) {
            (Some(authority), Some(proof))
                if lifecycle.scope().tenant() == Some(proof.tenant())
                    && lifecycle.release() == proof.release()
                    && lifecycle.package() == Some(proof.package())
                    && proof.belongs_to_authority(authority) => {}
            (None, None) => {}
            _ => return Err(super::invalid()),
        }
        // Authority equality/currentness is checked under its own fence at use.
        Ok(Self {
            lifecycle,
            admission,
        })
    }
    #[must_use]
    pub fn lifecycle(&self) -> &LifecycleEligibility {
        &self.lifecycle
    }
    #[must_use]
    pub fn admission(&self) -> Option<&ReleaseEligibility> {
        self.admission.as_ref()
    }
    #[must_use]
    pub fn scope(&self) -> &LifecycleScope {
        self.lifecycle.scope()
    }
    #[must_use]
    pub fn tenant(&self) -> Option<&TenantId> {
        self.scope().tenant()
    }
    #[must_use]
    pub fn package(&self) -> Option<&PackageDigest> {
        self.lifecycle.package()
    }
    #[must_use]
    pub fn release(&self) -> &ReleaseDigest {
        self.lifecycle.release()
    }
    #[must_use]
    pub fn generation(&self) -> u64 {
        self.lifecycle.generation()
    }
    #[must_use]
    pub fn retained_bytes(&self) -> usize {
        self.lifecycle.retained_bytes()
            + self
                .admission
                .as_ref()
                .map_or(0, ReleaseEligibility::retained_bytes)
            + std::mem::size_of::<Self>()
    }
    #[must_use]
    pub fn cache_digest(&self) -> [u8; 32] {
        let mut hash = Sha256::new();
        hash.update(b"lsf-release-use-v1\0");
        hash.update((Arc::as_ptr(&self.lifecycle.owner) as usize).to_le_bytes());
        hash.update((Arc::as_ptr(&self.lifecycle.row) as usize).to_le_bytes());
        hash.update(self.generation().to_le_bytes());
        if let Some(proof) = &self.admission {
            hash.update(proof.cache_digest());
        }
        hash.finalize().into()
    }
    #[must_use]
    pub fn belongs_to_catalog(&self, handle: &LifecycleAuthorityHandle) -> bool {
        self.lifecycle.belongs_to_catalog(handle)
            && handle.required_authority().is_some() == self.admission.is_some()
    }
    pub fn authorize_tenant(&self, tenant: &TenantId) -> Result<(), PlatformError> {
        match self.scope() {
            LifecycleScope::Tenant(actual) if actual == tenant => Ok(()),
            LifecycleScope::LocalUnscoped
                if self.admission.is_none() && self.lifecycle.owner.authority.is_none() =>
            {
                Ok(())
            }
            _ => Err(super::error(
                PlatformErrorCode::PermissionDenied,
                "release-lifecycle-tenant-mismatch",
            )),
        }
    }
    pub fn check_for_catalog(
        &self,
        handle: &LifecycleAuthorityHandle,
    ) -> Result<(), PlatformError> {
        if !self.belongs_to_catalog(handle) {
            return Err(super::error(
                PlatformErrorCode::PermissionDenied,
                "release-lifecycle-owner-mismatch",
            ));
        }
        self.check_current()
    }
    pub fn check_for_lifecycle(
        &self,
        handle: &LifecycleAuthorityHandle,
    ) -> Result<(), PlatformError> {
        self.check_for_catalog(handle)
    }
    pub fn check_for_authority(
        &self,
        authority: &Arc<dyn AdmissionAuthority>,
    ) -> Result<(), PlatformError> {
        self.lifecycle.check_current()?;
        self.admission
            .as_ref()
            .ok_or_else(super::invalid)?
            .check_for_authority(authority)
    }
    pub fn check_current(&self) -> Result<(), PlatformError> {
        self.lifecycle.check_current()?;
        if let Some(proof) = &self.admission {
            proof.check_for_authority(
                self.lifecycle
                    .owner
                    .authority
                    .as_ref()
                    .ok_or_else(super::invalid)?,
            )?;
        }
        Ok(())
    }
    pub fn check_with(&self, checker: &dyn ReleaseUseRecheck) -> Result<(), PlatformError> {
        checker.check_eligibility(self)
    }
    pub fn with_current(
        &self,
        action: &mut dyn FnMut(&dyn ReleaseUseRecheck) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        Self::with_all_current(std::slice::from_ref(self), action)
    }
    pub fn with_all_current(
        entries: &[Self],
        action: &mut dyn FnMut(&dyn ReleaseUseRecheck) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        let first = entries.first().ok_or_else(super::invalid)?;
        let _fence = first.lifecycle.owner.read()?;
        for entry in entries {
            if !Arc::ptr_eq(&first.lifecycle.owner, &entry.lifecycle.owner) {
                return Err(super::invalid());
            }
            entry.lifecycle.check_current()?;
        }
        if let Some(proof) = entries.iter().find_map(|entry| entry.admission.as_ref()) {
            proof.with_current(&mut |admission| {
                let checker = Checked {
                    owner: &first.lifecycle.owner,
                    entries,
                    admission: Some(admission),
                };
                checker.check()?;
                action(&checker)
            })
        } else {
            let checker = Checked {
                owner: &first.lifecycle.owner,
                entries,
                admission: None,
            };
            checker.check()?;
            action(&checker)
        }
    }
}
struct Checked<'a> {
    owner: &'a Arc<Owner>,
    entries: &'a [ReleaseUseEligibility],
    admission: Option<&'a dyn AdmissionRecheck>,
}
impl ReleaseUseRecheck for Checked<'_> {
    fn check(&self) -> Result<(), PlatformError> {
        self.owner.check()?;
        if let Some(checker) = self.admission {
            checker.check()?;
        }
        for entry in self.entries {
            self.check_eligibility(entry)?;
        }
        Ok(())
    }
    fn check_eligibility(&self, entry: &ReleaseUseEligibility) -> Result<(), PlatformError> {
        if !Arc::ptr_eq(self.owner, &entry.lifecycle.owner) {
            return Err(super::invalid());
        }
        entry.lifecycle.check_current()?;
        match (&entry.admission, self.admission) {
            (Some(proof), Some(checker)) => proof.check_with(checker),
            (None, None) if self.owner.authority.is_none() => Ok(()),
            _ => Err(super::invalid()),
        }
    }
}

use super::{CheckedWebLayout, WebAdmissionGrant};
use crate::{AdmissionRecheck, PublicationRef};
use latent_core::{PlatformError, PlatformErrorCode, TenantId};
use std::sync::{
    atomic::{AtomicBool, AtomicU64, Ordering},
    Arc, RwLock, RwLockReadGuard, RwLockWriteGuard,
};

/// One fixed web lifecycle fence per repository incarnation, no guest resources.
pub(crate) struct WebEpoch {
    healthy: AtomicBool,
    fence: RwLock<()>,
}
impl WebEpoch {
    pub(crate) fn new() -> Self {
        Self {
            healthy: AtomicBool::new(true),
            fence: RwLock::new(()),
        }
    }
    pub(crate) fn retire(&self) {
        self.healthy.store(false, Ordering::Release);
    }
    pub(crate) fn check(&self) -> Result<(), PlatformError> {
        if self.healthy.load(Ordering::Acquire) {
            Ok(())
        } else {
            Err(unavailable("web-catalog-reopen-required"))
        }
    }
    fn read(&self) -> Result<RwLockReadGuard<'_, ()>, PlatformError> {
        let guard = self
            .fence
            .try_read()
            .map_err(|_| unavailable("web-lifecycle-busy"))?;
        self.check()?;
        Ok(guard)
    }
    pub(crate) fn write(&self) -> Result<RwLockWriteGuard<'_, ()>, PlatformError> {
        let guard = self
            .fence
            .try_write()
            .map_err(|_| unavailable("web-lifecycle-busy"))?;
        self.check()?;
        Ok(guard)
    }
}

/// Updated only under the catalog's exclusive `WebEpoch` fence. Old grants keep
/// this tiny cell, so removing/replacing a record never leaves a live old token.
pub(crate) struct WebGeneration(AtomicU64);
impl WebGeneration {
    pub(crate) fn new(generation: u64) -> Self {
        Self(AtomicU64::new(generation))
    }
    pub(crate) fn replace(&self, generation: u64) {
        self.0.store(generation, Ordering::Release);
    }
}

/// Sealed exact publication/layout/generation plus current admission. No bytes,
/// receipt, package digest or independently constructed layout can create this.
#[derive(Clone)]
pub struct WebUseEligibility {
    publication: PublicationRef,
    layout: Arc<CheckedWebLayout>,
    grant: Arc<dyn WebAdmissionGrant>,
    owner: Arc<WebEpoch>,
    generation: Arc<WebGeneration>,
    accepted_generation: u64,
    // A copied eligibility token cannot detach retained metadata from its lease.
    _retention: Arc<super::WebReadPermit>,
}
impl WebUseEligibility {
    pub(crate) fn new(
        publication: PublicationRef,
        layout: Arc<CheckedWebLayout>,
        grant: Arc<dyn WebAdmissionGrant>,
        owner: Arc<WebEpoch>,
        generation: Arc<WebGeneration>,
        accepted_generation: u64,
        retention: Arc<super::WebReadPermit>,
    ) -> Result<Self, PlatformError> {
        let binding = grant.binding();
        if accepted_generation == 0
            || generation.0.load(Ordering::Acquire) != accepted_generation
            || publication != PublicationRef::package(publication.scope.clone(), layout.package())?
            || publication.scope.tenant() != Some(&binding.tenant)
            || &binding.package != layout.package()
            || &binding.manifest != layout.manifest_digest()
            || &binding.assets != layout.assets_digest()
        {
            return Err(super::invalid("web-grant-association"));
        }
        Ok(Self {
            publication,
            layout,
            grant,
            owner,
            generation,
            accepted_generation,
            _retention: retention,
        })
    }
    #[must_use]
    pub fn publication(&self) -> &PublicationRef {
        &self.publication
    }
    #[must_use]
    pub fn layout(&self) -> &CheckedWebLayout {
        &self.layout
    }
    #[must_use]
    pub const fn generation(&self) -> u64 {
        self.accepted_generation
    }
    #[must_use]
    pub fn retained_bytes(&self) -> usize {
        std::mem::size_of::<Self>()
            .saturating_add(1024)
            .saturating_add(self.layout.retained_bytes())
            .saturating_add(self.grant.retained_bytes())
    }

    pub fn check_current(&self, tenant: &TenantId) -> Result<(), PlatformError> {
        self.with_current(tenant, &mut |_| Ok(()))
    }

    /// The synchronous start/response-acceptance decision, never the duration of
    /// an async send or invocation. Accepted work retains its real read/activation
    /// charges through completion and may finish after a later revocation.
    pub fn with_current(
        &self,
        tenant: &TenantId,
        action: &mut dyn FnMut(&dyn AdmissionRecheck) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        if self.publication.scope.tenant() != Some(tenant) {
            return Err(super::failure(
                PlatformErrorCode::PermissionDenied,
                "web-tenant-mismatch",
            ));
        }
        let _fence = self.owner.read()?;
        self.check_generation()?;
        self.grant.with_current(&mut |checker| {
            let checked = Recheck {
                token: self,
                inner: checker,
            };
            checked.check()?;
            action(&checked)
        })
    }

    fn check_generation(&self) -> Result<(), PlatformError> {
        self.owner.check()?;
        if self.generation.0.load(Ordering::Acquire) != self.accepted_generation {
            return Err(super::failure(
                PlatformErrorCode::PermissionDenied,
                "web-generation-stale",
            ));
        }
        Ok(())
    }
}

struct Recheck<'a> {
    token: &'a WebUseEligibility,
    inner: &'a dyn AdmissionRecheck,
}
impl AdmissionRecheck for Recheck<'_> {
    fn check(&self) -> Result<(), PlatformError> {
        self.token.check_generation()?;
        self.inner.check()
    }
    fn check_grant(&self, grant: &dyn crate::AdmissionGrant) -> Result<(), PlatformError> {
        self.check()?;
        self.inner.check_grant(grant)
    }
    fn check_web_grant(&self, grant: &dyn WebAdmissionGrant) -> Result<(), PlatformError> {
        self.check()?;
        self.inner.check_web_grant(grant)
    }
}
impl std::fmt::Debug for WebUseEligibility {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("WebUseEligibility")
            .field("publication", &self.publication)
            .field("generation", &self.accepted_generation)
            .finish_non_exhaustive()
    }
}
fn unavailable(reason: &'static str) -> PlatformError {
    super::failure(PlatformErrorCode::Unavailable, reason)
}

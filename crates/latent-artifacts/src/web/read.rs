use super::{CheckedWebLayout, WebUseEligibility};
use crate::{AdmissionRecheck, PublicationRef};
use latent_core::{PlatformError, TenantId};
use std::sync::{Arc, Mutex};

/// Shared catalog response/read ownership. Per-asset/render limits still apply;
/// dormant publications have no read slot, buffer, worker or timer.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WebReadLimits {
    pub maximum_reads: usize,
    pub maximum_bytes: usize,
}
impl Default for WebReadLimits {
    fn default() -> Self {
        Self {
            maximum_reads: 32,
            maximum_bytes: 64 * 1024 * 1024,
        }
    }
}
impl WebReadLimits {
    pub fn validate(self) -> Result<(), PlatformError> {
        let hard = Self::default();
        if self.maximum_reads == 0
            || self.maximum_reads > hard.maximum_reads
            || self.maximum_bytes == 0
            || self.maximum_bytes > hard.maximum_bytes
        {
            return Err(super::exhausted());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct WebReadSnapshot {
    pub active_reads: usize,
    pub retained_bytes: usize,
}
pub(crate) struct WebReadBudget {
    limits: WebReadLimits,
    state: Mutex<WebReadSnapshot>,
}
impl WebReadBudget {
    pub(crate) fn new(limits: WebReadLimits) -> Result<Self, PlatformError> {
        limits.validate()?;
        Ok(Self {
            limits,
            state: Mutex::new(WebReadSnapshot::default()),
        })
    }
    pub(crate) fn reserve(
        self: &Arc<Self>,
        bytes: usize,
    ) -> Result<Arc<WebReadPermit>, PlatformError> {
        let mut state = self.state.try_lock().map_err(|_| super::exhausted())?;
        let retained_bytes = state
            .retained_bytes
            .checked_add(bytes)
            .ok_or_else(super::exhausted)?;
        if bytes == 0
            || state.active_reads >= self.limits.maximum_reads
            || retained_bytes > self.limits.maximum_bytes
        {
            return Err(super::exhausted());
        }
        state.active_reads += 1;
        state.retained_bytes = retained_bytes;
        Ok(Arc::new(WebReadPermit {
            owner: Arc::clone(self),
            bytes,
        }))
    }
    pub(crate) fn snapshot(&self) -> Result<WebReadSnapshot, PlatformError> {
        self.state
            .try_lock()
            .map(|state| *state)
            .map_err(|_| super::exhausted())
    }
}
pub(crate) struct WebReadPermit {
    owner: Arc<WebReadBudget>,
    bytes: usize,
}
impl Drop for WebReadPermit {
    fn drop(&mut self) {
        let mut state = self
            .owner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.active_reads -= 1;
        state.retained_bytes -= self.bytes;
    }
}

/// One coherent immutable association plus bounded response ownership. Asset
/// URLs derive from this selection, and never from a mutable deployment alias.
pub struct WebSelection {
    pub(crate) eligibility: WebUseEligibility,
    pub(crate) _permit: Arc<WebReadPermit>,
}
impl WebSelection {
    #[must_use]
    pub fn publication(&self) -> &PublicationRef {
        self.eligibility.publication()
    }
    #[must_use]
    pub fn layout(&self) -> &CheckedWebLayout {
        self.eligibility.layout()
    }
    #[must_use]
    pub fn eligibility(&self) -> &WebUseEligibility {
        &self.eligibility
    }
    pub fn asset_url(&self, path: &str) -> Result<String, PlatformError> {
        self.layout().asset_url(self.publication(), path)
    }
    pub fn with_current(
        &self,
        tenant: &TenantId,
        action: &mut dyn FnMut(&dyn AdmissionRecheck) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        self.eligibility.with_current(tenant, action)
    }
}

/// Integrity-checked immutable asset/renderer bytes. Reading historical bytes
/// is not permission to use them: call `with_current` at the response/execution
/// acceptance decision, and retain this owner until cleanup really finishes.
pub struct WebBlobRead {
    pub(crate) selection: WebSelection,
    pub(crate) bytes: Box<[u8]>,
    pub(crate) media_type: Box<str>,
}
impl WebBlobRead {
    #[must_use]
    pub fn selection(&self) -> &WebSelection {
        &self.selection
    }
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }
    #[must_use]
    pub fn media_type(&self) -> &str {
        &self.media_type
    }
    pub fn with_current(
        &self,
        tenant: &TenantId,
        action: &mut dyn FnMut(&dyn AdmissionRecheck) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        self.selection.with_current(tenant, action)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn read_capacity_is_retained_until_the_last_consumer_finishes() {
        let owner = Arc::new(
            WebReadBudget::new(WebReadLimits {
                maximum_reads: 2,
                maximum_bytes: 10,
            })
            .unwrap(),
        );
        let permit = owner.reserve(7).unwrap();
        let consumer = Arc::clone(&permit);
        drop(permit);
        assert!(owner.reserve(4).is_err());
        let other = owner.reserve(3).unwrap();
        assert_eq!(
            owner.snapshot().unwrap(),
            WebReadSnapshot {
                active_reads: 2,
                retained_bytes: 10
            }
        );
        assert!(owner.reserve(1).is_err());
        drop(consumer);
        assert_eq!(
            owner.snapshot().unwrap(),
            WebReadSnapshot {
                active_reads: 1,
                retained_bytes: 3
            }
        );
        drop(other);
        assert_eq!(owner.snapshot().unwrap(), WebReadSnapshot::default());
        assert!(owner.reserve(usize::MAX).is_err());
    }
}

use std::sync::Arc;

use latent_core::PlatformError;
use latent_policy::capability::{PolicyStore, SealedPolicyDecision};
use latent_state::namespace::catalog::NamespaceRead;

use super::{denied, gate::Gate, identity, NamespaceAuthority};

/// Host-owned cursor authority. The view identity comes from the actual affine
/// `ProtectedStoreView` owner; public wire handles identify this private resource,
/// never serialize its namespace/caller/position fields as permission.
pub struct ScopedPage {
    gate: Arc<Gate>,
    view: String,
    position: Option<Vec<u8>>,
}
impl ScopedPage {
    /// Internal physical resume position, never accepted from a guest cursor.
    #[must_use]
    pub fn position(&self) -> Option<&[u8]> {
        self.position.as_deref()
    }

    pub fn advance(&mut self, position: Option<Vec<u8>>) -> Result<(), PlatformError> {
        if position
            .as_ref()
            .is_some_and(|value| value.is_empty() || value.len() > 4096)
        {
            return Err(denied());
        }
        self.position = position;
        Ok(())
    }
}
impl NamespaceAuthority {
    pub fn bind_page(&self, actual_view_identity: &str) -> Result<ScopedPage, PlatformError> {
        identity(actual_view_identity)?;
        self.gate.check()?;
        Ok(ScopedPage {
            gate: Arc::clone(&self.gate),
            view: actual_view_identity.into(),
            position: None,
        })
    }

    /// Invoke both before an engine pull and before publishing its bytes/counts.
    /// A different caller, activation (even with reused ID), entity or view cannot
    /// transfer the resource. Current policy/reincarnation still invalidates it.
    pub fn with_page_access(
        &self,
        store: &PolicyStore,
        operation: &SealedPolicyDecision<'_>,
        namespace: &NamespaceRead,
        page: &ScopedPage,
        actual_view_identity: &str,
        action: impl FnOnce() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        if !Arc::ptr_eq(&self.gate, &page.gate) || page.view != actual_view_identity {
            return Err(denied());
        }
        self.with_operation(store, operation, namespace, "page-next", action)
    }
}

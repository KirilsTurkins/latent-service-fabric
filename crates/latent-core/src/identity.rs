//! Invocation identity propagated through local and remote calls.

use crate::{Metadata, ServiceId, TenantId};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[non_exhaustive]
pub enum PrincipalKind {
    User,
    Service,
    Node,
    Trigger,
    Administrator,
    Anonymous,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvocationPrincipal {
    pub subject: String,
    pub kind: PrincipalKind,
    pub tenant: Option<TenantId>,
    pub service: Option<ServiceId>,
    pub claims: Metadata,
}

impl InvocationPrincipal {
    /// Canonical subject for a node-derived service caller. This spelling grants
    /// no authority; admission must still check kind, tenant and selected target.
    #[must_use]
    pub fn local_service_subject(tenant: &TenantId, service: &ServiceId) -> String {
        format!(
            "service:{}:{}:{}:{}",
            tenant.0.len(),
            tenant.0,
            service.0.len(),
            service.0
        )
    }
}

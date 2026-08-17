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

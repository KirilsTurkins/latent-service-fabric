use latent_core::{InvocationPrincipal, PlatformError, PlatformErrorCode, PrincipalKind};
use std::sync::Arc;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ManagementOperation {
    Tenant,
    NodeInventory,
    NodeControl,
    AuditTenant,
    AuditNode,
}

/// Authorization uses the same trusted identity extension as invocation.
pub trait ManagementPolicy: Send + Sync {
    fn authorize(
        &self,
        principal: &InvocationPrincipal,
        operation: ManagementOperation,
    ) -> Result<(), PlatformError>;

    /// Capture this owner's original node-operator decision. Mutable owners
    /// retain their original authorization stamps and reject a later refreshed
    /// grant. This default supplies no mutation authority.
    fn retain_node_control(
        &self,
        principal: &InvocationPrincipal,
    ) -> Result<Arc<dyn ManagementDecision>, PlatformError> {
        self.authorize(principal, ManagementOperation::NodeControl)?;
        Err(PlatformError {
            code: PlatformErrorCode::Unavailable,
            message: "retained node-operator authorization unavailable".into(),
            retryable: false,
            details: Vec::new(),
        })
    }
}

/// An original decision retained by the actual installed management-policy
/// owner. IDs, caller claims in protocol payloads and receipts cannot create it.
pub trait ManagementDecision: Send + Sync {
    /// Exactly one short callback under the original current authorization.
    /// No native I/O, audit flush, guest, wait or authorization refresh.
    fn with_current(
        &self,
        action: &mut dyn FnMut() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError>;
}

/// Tenant management requires an administrator. Global inventory additionally
/// requires the trusted node-operator claim supplied by the embedding listener.
#[derive(Debug, Clone, Copy, Default)]
pub struct LocalManagementPolicy;

impl ManagementPolicy for LocalManagementPolicy {
    fn authorize(
        &self,
        principal: &InvocationPrincipal,
        operation: ManagementOperation,
    ) -> Result<(), PlatformError> {
        if principal.kind != PrincipalKind::Administrator
            || (matches!(
                operation,
                ManagementOperation::NodeInventory
                    | ManagementOperation::NodeControl
                    | ManagementOperation::AuditNode
            ) && principal
                .claims
                .get("latent.node.operator")
                .map(String::as_str)
                != Some("true"))
        {
            return Err(PlatformError {
                code: PlatformErrorCode::PermissionDenied,
                message: "management operation is not permitted".to_owned(),
                retryable: false,
                details: Vec::new(),
            });
        }
        Ok(())
    }

    fn retain_node_control(
        &self,
        principal: &InvocationPrincipal,
    ) -> Result<Arc<dyn ManagementDecision>, PlatformError> {
        self.authorize(principal, ManagementOperation::NodeControl)?;
        // Local rules are immutable and the principal comes only from the
        // embedding listener's authenticated extension. Its original deadline
        // and node-close fence remain on the shared native reservation.
        Ok(Arc::new(LocalDecision(principal.clone())))
    }
}
struct LocalDecision(InvocationPrincipal);
impl ManagementDecision for LocalDecision {
    fn with_current(
        &self,
        action: &mut dyn FnMut() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        LocalManagementPolicy.authorize(&self.0, ManagementOperation::NodeControl)?;
        action()
    }
}

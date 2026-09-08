use latent_core::{InvocationPrincipal, PlatformError, PlatformErrorCode, PrincipalKind};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ManagementOperation {
    Tenant,
    NodeInventory,
}

/// Authorization uses the same trusted identity extension as invocation.
pub trait ManagementPolicy: Send + Sync {
    fn authorize(
        &self,
        principal: &InvocationPrincipal,
        operation: ManagementOperation,
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
            || (operation == ManagementOperation::NodeInventory
                && principal
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
}

use latent_activation::{ActivationRequest, ActivationStatus};
use latent_core::{
    ActivationId, CancelDisposition, InvocationPrincipal, PlatformError, PlatformErrorCode,
    PrincipalKind, TenantId,
};
use latent_node::{ActivationHandle, LocalActivationManager};

use crate::conformance::WorkCounter;

/// A scoped local test port. Starting returns the real affine lifecycle owner;
/// no task, status cache, cancellation registry, or budget ledger is added.
pub trait NodeHarness: Send + Sync {
    fn start(&self, request: ActivationRequest) -> Result<ActivationHandle, PlatformError>;
    fn status(&self, id: &ActivationId) -> Result<Option<ActivationStatus>, PlatformError>;
    fn cancel(&self, id: &ActivationId, reason: &str) -> Result<CancelDisposition, PlatformError>;
}

/// The embedding supplies an already authenticated principal. All operations
/// stay in its exact tenant scope, including administrator operations. Claims,
/// request metadata, and knowledge of an activation ID cannot change that scope.
pub struct ScopedNodeHarness<'a> {
    manager: &'a LocalActivationManager,
    principal: &'a InvocationPrincipal,
    tenant: &'a TenantId,
    work: WorkCounter,
}

impl<'a> ScopedNodeHarness<'a> {
    pub fn new(
        manager: &'a LocalActivationManager,
        principal: &'a InvocationPrincipal,
        work: WorkCounter,
    ) -> Result<Self, PlatformError> {
        let tenant = authenticated_tenant(principal)?;
        Ok(Self {
            manager,
            principal,
            tenant,
            work,
        })
    }
}

impl NodeHarness for ScopedNodeHarness<'_> {
    fn start(&self, request: ActivationRequest) -> Result<ActivationHandle, PlatformError> {
        self.work
            .before_command(true)
            .map_err(|_| super::work_limit())?;
        authorize_request(self.principal, self.tenant, &request)?;
        self.manager.start(request)
    }

    fn status(&self, id: &ActivationId) -> Result<Option<ActivationStatus>, PlatformError> {
        self.work
            .before_command(false)
            .map_err(|_| super::work_limit())?;
        identifier(&id.0)?;
        self.manager.status(self.tenant, id)
    }

    fn cancel(&self, id: &ActivationId, reason: &str) -> Result<CancelDisposition, PlatformError> {
        self.work
            .before_command(false)
            .map_err(|_| super::work_limit())?;
        identifier(&id.0)?;
        if reason.len() > 256 || reason.chars().any(char::is_control) {
            return Err(super::error(
                PlatformErrorCode::InvalidArgument,
                "invalid-harness-cancellation-reason",
            ));
        }
        self.manager.cancel_for(self.tenant, id, reason)
    }
}

fn authorize_request(
    principal: &InvocationPrincipal,
    tenant: &TenantId,
    request: &ActivationRequest,
) -> Result<(), PlatformError> {
    authenticated_tenant(&request.principal)?;
    if request.principal != *principal || request.target.tenant != *tenant {
        return Err(super::error(
            PlatformErrorCode::PermissionDenied,
            "harness-principal-scope-mismatch",
        ));
    }
    Ok(())
}

fn authenticated_tenant(principal: &InvocationPrincipal) -> Result<&TenantId, PlatformError> {
    if principal.kind == PrincipalKind::Anonymous
        || (principal.kind == PrincipalKind::Service && principal.service.is_none())
    {
        return Err(super::error(
            PlatformErrorCode::Unauthenticated,
            "harness-principal-required",
        ));
    }
    let tenant = principal.tenant.as_ref().ok_or_else(|| {
        super::error(
            PlatformErrorCode::Unauthenticated,
            "harness-principal-required",
        )
    })?;
    identifier(&principal.subject)?;
    identifier(&tenant.0)?;
    if let Some(service) = &principal.service {
        identifier(&service.0)?;
    }
    if principal.claims.len() > 16 {
        return Err(super::error(
            PlatformErrorCode::ResourceExhausted,
            "harness-principal-too-large",
        ));
    }
    let mut available = 8 * 1024_usize;
    for (key, value) in &principal.claims {
        if key.capacity() > 512 || value.capacity() > 512 {
            return Err(super::error(
                PlatformErrorCode::ResourceExhausted,
                "harness-principal-too-large",
            ));
        }
        available = available
            .checked_sub(key.capacity())
            .and_then(|n| n.checked_sub(value.capacity()))
            .ok_or_else(|| {
                super::error(
                    PlatformErrorCode::ResourceExhausted,
                    "harness-principal-too-large",
                )
            })?;
    }
    Ok(tenant)
}

fn identifier(value: &String) -> Result<(), PlatformError> {
    if value.is_empty()
        || value.capacity() > 512
        || value.chars().any(|c| c.is_control() || c.is_whitespace())
    {
        return Err(super::error(
            PlatformErrorCode::InvalidArgument,
            "invalid-harness-identifier",
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests;

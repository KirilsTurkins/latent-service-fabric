//! Concrete ownership bridge; it adds no queue, task, status cache, or budget ledger.
mod owned;
use super::{
    authenticated_tenant, CancellationCommand, InvocationCancellation, InvocationCommand,
    InvocationLimits, InvocationResponse, InvocationRuntime, StatusQuery,
};
use latent_activation::{ActivationRequest, ActivationStatus};
use latent_core::{BoxFuture, CancelDisposition, PlatformError};
use latent_node::LocalActivationManager;
use owned::LocalInvocation;

#[derive(Clone)]
/// Owns the local manager binding and its direct-call authentication bounds.
/// Configure the bridge, service adapter, and manager with compatible limits;
/// the default bridge uses the same ingress limits as the default service.
pub struct LocalInvocationRuntime {
    manager: LocalActivationManager,
    limits: InvocationLimits,
}
impl LocalInvocationRuntime {
    #[must_use]
    pub fn new(manager: LocalActivationManager) -> Self {
        Self::with_limits(manager, InvocationLimits::default())
            .expect("default invocation limits are valid")
    }

    /// Uses the service's configured authentication bounds for direct status
    /// and cancellation calls. The manager independently enforces its limits.
    pub fn with_limits(
        manager: LocalActivationManager,
        limits: InvocationLimits,
    ) -> Result<Self, PlatformError> {
        limits.validate()?;
        Ok(Self { manager, limits })
    }
}
impl InvocationRuntime for LocalInvocationRuntime {
    fn invoke(
        &self,
        command: InvocationCommand,
        cancellation: InvocationCancellation,
    ) -> BoxFuture<'_, Result<InvocationResponse, PlatformError>> {
        // In particular, do not move start() into an async block: identity must
        // be reserved before this method returns an unpolled future.
        let started = self.manager.start(activation_request(command));
        match started {
            Ok(handle) => Box::pin(LocalInvocation::new(handle, cancellation)),
            Err(error) => Box::pin(std::future::ready(Err(error))),
        }
    }
    fn cancel(
        &self,
        command: CancellationCommand,
    ) -> BoxFuture<'_, Result<CancelDisposition, PlatformError>> {
        let result = authenticated_tenant(&command.principal, &self.limits).and_then(|tenant| {
            self.manager
                .cancel_for(tenant, &command.activation_id, &command.reason)
        });
        Box::pin(std::future::ready(result))
    }
    fn get_activation(
        &self,
        query: StatusQuery,
    ) -> BoxFuture<'_, Result<Option<ActivationStatus>, PlatformError>> {
        let result = authenticated_tenant(&query.principal, &self.limits)
            .and_then(|tenant| self.manager.status(tenant, &query.activation_id));
        Box::pin(std::future::ready(result))
    }
}
fn activation_request(command: InvocationCommand) -> ActivationRequest {
    let request = command.request;
    ActivationRequest {
        activation_id: request.requested_activation_id,
        parent_activation_id: request.parent_activation_id,
        root_activation_id: request.root_activation_id,
        principal: command.principal,
        target: request.target,
        deadline_unix_millis: request.deadline_unix_millis,
        priority: request.priority,
        trace: command.trace,
        idempotency_key: request.idempotency_key,
        retry_attempt: 0,
        budget: request.budget,
        metadata: request.metadata,
        input: request.payload,
        input_media_type: request.media_type,
    }
}

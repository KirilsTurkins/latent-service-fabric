//! Actual namespace management over the node's single protected engine.
mod audit;
mod authorization;
mod dispatcher;
mod inspection;
mod mutation;
mod recovery;
mod response;
pub use recovery::StateManagementRecoveryAdmission;
#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod tests;

use super::{OwnedPhase4Response, Phase4Call, Phase4Runtime};
use crate::{
    invocation::AuthenticatedInvocationContext,
    management::{ManagementDecision, ManagementOperation, ManagementPolicy},
};
use latent_artifacts::{ArtifactRepository, PublicationRef};
use latent_core::{
    ActivationClock, BoxFuture, PlatformError, PlatformErrorCode, ReleaseDigest, ServiceId,
    StateNamespaceId,
};
use latent_node::PolicyCallBinding;
use latent_policy::capability::PolicyStore;
use latent_rpc::{control::v1 as c, phase4 as contract};
use latent_state::{
    namespace::{catalog::NamespaceCatalog, NamespaceError, NamespaceQuota},
    protected_store::{ProtectedStoreError, ProtectedStoreOwner},
    store_io::StoreIoError,
};
use std::{
    sync::Arc,
    time::{Duration, Instant},
};

/// Actual retained request/work/response admission. The implementation belongs
/// to the node's bounded recovery owner (#397), not an alternate wire pool.
pub trait StateManagementAdmission: Send + Sync {
    /// Projects the actual installed global owner. Equal configuration is not
    /// identity, and constructing a replacement pool cannot satisfy this port.
    fn native_capacity(&self) -> latent_core::native_capacity::NativeCapacityOwner;
    /// Reserve before returning the operation future. `request_bytes` includes
    /// the decoded request; `work_bytes` includes all native page/codec buffers.
    fn reserve_recovery(
        &self,
        request_bytes: usize,
        work_bytes: usize,
        response_bytes: usize,
        deadline: Instant,
    ) -> Result<Arc<dyn StateManagementReservation>, PlatformError>;
}
pub trait StateManagementReservation: Send + Sync {
    /// Identity of the actual retained affine reservation, without re-admission.
    fn uses_native_capacity(
        &self,
        owner: &latent_core::native_capacity::NativeCapacityOwner,
    ) -> bool;
    fn reserved_response_bytes(&self) -> usize;
    /// The real owner's short currentness/cancellation fence, without I/O.
    fn with_live(&self, action: &mut dyn FnMut()) -> Result<(), PlatformError>;
}

/// Trusted installed target constraints. Descriptive configuration grants no
/// authority: the exact artifact owner and current policy must both seal access.
pub struct StateManagementBinding {
    pub publication: PublicationRef,
    pub component: ReleaseDigest,
    pub service: ServiceId,
    pub namespace: StateNamespaceId,
    pub incarnation: u64,
    pub state_schema: String,
    pub result_policy: String,
    pub maximum_quota: NamespaceQuota,
    pub state: PolicyCallBinding,
}
pub struct StateManagementServices {
    pub store: Arc<ProtectedStoreOwner>,
    pub namespaces: Arc<NamespaceCatalog>,
    pub policy: Arc<PolicyStore>,
    pub artifacts: Arc<dyn ArtifactRepository>,
    pub authorization: Arc<dyn ManagementPolicy>,
    pub admission: Arc<dyn StateManagementAdmission>,
    pub clock: Arc<dyn ActivationClock>,
    pub audit: Option<latent_audit::AuditHandle>,
}
struct Inner {
    services: StateManagementServices,
    bindings: Vec<Arc<StateManagementBinding>>,
    dispatcher: Option<latent_effects::runtime::DispatcherManagementPort>,
}
struct AdmittedRequest {
    context: AuthenticatedInvocationContext,
    request: contract::Request,
    binding: Option<Arc<StateManagementBinding>>,
    node_decision: Option<Arc<dyn ManagementDecision>>,
    deadline: Instant,
    permit: Arc<dyn StateManagementReservation>,
}
#[derive(Clone)]
pub struct StateManagementBackend(Arc<Inner>);
const WORK_BYTES: usize = 8 * 1024 * 1024;
const RESPONSE_BYTES: usize = 4 * contract::MAX_RESPONSE_BYTES + 16384;

impl StateManagementBackend {
    pub fn new(
        services: StateManagementServices,
        bindings: Vec<StateManagementBinding>,
    ) -> Result<Self, PlatformError> {
        if !services
            .store
            .uses_native_capacity(&services.admission.native_capacity())
        {
            return Err(invalid());
        }
        if bindings.is_empty() || bindings.len() > 128 || bindings.capacity() > 128 {
            return Err(capacity());
        }
        for (index, binding) in bindings.iter().enumerate() {
            authorization::validate_binding(binding)?;
            if bindings[..index].iter().any(|other| {
                other.publication == binding.publication
                    && other.namespace == binding.namespace
                    && other.incarnation == binding.incarnation
            }) {
                return Err(invalid());
            }
        }
        Ok(Self(Arc::new(Inner {
            services,
            bindings: bindings.into_iter().map(Arc::new).collect(),
            dispatcher: None,
        })))
    }

    /// Installs only a sealed handle to the existing node dispatcher. A foreign
    /// store or an already shared backend cannot create an alternate owner.
    pub fn with_dispatcher(
        mut self,
        dispatcher: latent_effects::runtime::DispatcherManagementPort,
    ) -> Result<Self, PlatformError> {
        if !dispatcher.uses_store(&self.0.services.store)
            || !dispatcher.uses_native_capacity(&self.0.services.admission.native_capacity())
        {
            return Err(invalid());
        }
        Arc::get_mut(&mut self.0).ok_or_else(invalid)?.dispatcher = Some(dispatcher);
        Ok(self)
    }

    /// Reserves real recovery capacity synchronously; lookup/admission happens
    /// only after exact publication and current policy authorization.
    #[must_use]
    pub fn execute_state(
        &self,
        context: AuthenticatedInvocationContext,
        request: contract::Request,
    ) -> BoxFuture<'_, Result<OwnedPhase4Response, PlatformError>> {
        let admission = self.admit(context, request);
        Box::pin(async move {
            let AdmittedRequest {
                context,
                request,
                binding,
                node_decision,
                deadline,
                permit,
            } = admission?;
            if request.is_node_management() {
                return dispatcher::execute(
                    Arc::clone(&self.0),
                    context,
                    request,
                    node_decision.ok_or_else(invalid)?,
                    deadline,
                    permit,
                )
                .await;
            }
            let binding = binding.ok_or_else(invalid)?;
            let access =
                authorization::authorize(&self.0.services, &binding, &context, &request, deadline)
                    .await?;
            let pending = audit::begin(&self.0, &access, &context, &request).await?;
            match request {
                contract::Request::InspectNamespace(value) => {
                    inspection::inspect(
                        Arc::clone(&self.0),
                        value,
                        access,
                        permit,
                        deadline,
                        pending,
                    )
                    .await
                }
                contract::Request::GetStateOperationReceipt(value) => {
                    inspection::receipt(
                        Arc::clone(&self.0),
                        value,
                        access,
                        permit,
                        deadline,
                        pending,
                    )
                    .await
                }
                contract::Request::MutateNamespace(value) => {
                    mutation::mutate(
                        Arc::clone(&self.0),
                        value,
                        access,
                        permit,
                        deadline,
                        pending,
                    )
                    .await
                }
                _ => Err(unsupported()),
            }
        })
    }
    fn admit(
        &self,
        context: AuthenticatedInvocationContext,
        request: contract::Request,
    ) -> Result<AdmittedRequest, PlatformError> {
        request.validate().map_err(|error| match error {
            contract::ValidationError::Capacity => capacity(),
            contract::ValidationError::UnsupportedProfile => unsupported(),
            _ => invalid(),
        })?;
        let binding = self.binding(&context, &request)?;
        let node = request.is_node_management();
        // Capture the original operator decision before returning the future.
        // Polling later must not replace a revoked decision with a new grant.
        let node_decision = if node {
            Some(
                self.0
                    .services
                    .authorization
                    .retain_node_control(context.principal())?,
            )
        } else {
            None
        };
        let now = self.0.services.clock.monotonic_now();
        let deadline = context
            .transport_expires_at()
            .unwrap_or(now + Duration::from_secs(30));
        if now >= deadline || deadline.saturating_duration_since(now) > Duration::from_secs(30) {
            return Err(expired());
        }
        let (work_bytes, response_bytes) = if node {
            (dispatcher::WORK_BYTES, dispatcher::RESPONSE_BYTES)
        } else {
            (WORK_BYTES, RESPONSE_BYTES)
        };
        let permit = self.0.services.admission.reserve_recovery(
            request
                .encoded_len()
                .checked_mul(4)
                .and_then(|bytes| bytes.checked_add(32768))
                .ok_or_else(capacity)?,
            work_bytes,
            response_bytes,
            deadline,
        )?;
        if permit.reserved_response_bytes() < response_bytes
            || !permit.uses_native_capacity(&self.0.services.admission.native_capacity())
        {
            return Err(capacity());
        }
        Ok(AdmittedRequest {
            context,
            request,
            binding,
            node_decision,
            deadline,
            permit,
        })
    }
    fn binding(
        &self,
        context: &AuthenticatedInvocationContext,
        request: &contract::Request,
    ) -> Result<Option<Arc<StateManagementBinding>>, PlatformError> {
        if request.is_node_management() {
            if context.principal().tenant.is_none() || self.0.dispatcher.is_none() {
                return Err(denied());
            }
            self.0
                .services
                .authorization
                .authorize(context.principal(), ManagementOperation::NodeControl)?;
            return Ok(None);
        }
        let target = target(request)?;
        let selector = target.namespace.as_ref().ok_or_else(invalid)?;
        let principal = context.principal();
        if principal
            .tenant
            .as_ref()
            .is_none_or(|tenant| tenant.0 != selector.tenant)
        {
            return Err(denied());
        }
        self.0
            .services
            .authorization
            .authorize(principal, ManagementOperation::Tenant)?;
        let publication = target
            .authorization_publication
            .as_ref()
            .ok_or_else(invalid)?;
        let binding = self
            .0
            .bindings
            .iter()
            .find(|binding| {
                binding.publication.id.as_str() == publication.id
                    && binding
                        .publication
                        .scope
                        .tenant()
                        .is_some_and(|tenant| tenant.0 == selector.tenant)
                    && binding.namespace.0 == selector.namespace
                    && binding.incarnation.to_string() == selector.incarnation
            })
            .cloned()
            .ok_or_else(denied)?;
        Ok(Some(binding))
    }
}
impl Phase4Runtime for StateManagementBackend {
    fn execute(
        &self,
        call: Phase4Call,
    ) -> BoxFuture<'_, Result<OwnedPhase4Response, PlatformError>> {
        let (context, request) = call.into_parts();
        self.execute_state(context, request)
    }
}
fn target(request: &contract::Request) -> Result<&c::InspectNamespaceRequest, PlatformError> {
    match request {
        contract::Request::InspectNamespace(value) => Ok(value),
        contract::Request::MutateNamespace(value) => value.namespace.as_ref().ok_or_else(invalid),
        contract::Request::GetStateOperationReceipt(value) => {
            value.namespace.as_ref().ok_or_else(invalid)
        }
        _ => Err(unsupported()),
    }
}
fn error(code: PlatformErrorCode, message: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: message.into(),
        retryable: false,
        details: vec![],
    }
}
fn denied() -> PlatformError {
    error(
        PlatformErrorCode::PermissionDenied,
        "namespace-access-denied",
    )
}
fn invalid() -> PlatformError {
    error(
        PlatformErrorCode::InvalidArgument,
        "invalid-namespace-management-request",
    )
}
fn capacity() -> PlatformError {
    error(
        PlatformErrorCode::ResourceExhausted,
        "namespace-management-capacity",
    )
}
fn expired() -> PlatformError {
    error(
        PlatformErrorCode::DeadlineExceeded,
        "namespace-management-deadline",
    )
}
fn unsupported() -> PlatformError {
    error(
        PlatformErrorCode::Unavailable,
        "namespace-management-operation-unavailable",
    )
}
fn missing() -> PlatformError {
    error(
        PlatformErrorCode::NotFound,
        "namespace-management-record-not-found",
    )
}
fn namespace_error(value: NamespaceError) -> PlatformError {
    match value {
        NamespaceError::Conflict | NamespaceError::InUse => error(
            PlatformErrorCode::StateConflict,
            "namespace-operation-conflict",
        ),
        NamespaceError::Capacity => capacity(),
        NamespaceError::PermissionDenied => denied(),
        NamespaceError::Invalid => invalid(),
        _ => unsupported(),
    }
}
fn protected_error(_value: ProtectedStoreError) -> PlatformError {
    unsupported()
}
fn io_error(_value: StoreIoError) -> PlatformError {
    unsupported()
}

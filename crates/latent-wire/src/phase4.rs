//! Authenticated Phase 4 adapters over the node's existing state/runtime owners.
//!
//! No listener, engine, executor, recovery worker, or capacity pool is created.
//! A configured runtime must resolve the current target and seal its real policy
//! before lookup; structural validation and authenticated tenant shape are not
//! result-read authority. No default permissive runtime is supplied.

mod lease;
mod public_error;
mod state_management;
pub use state_management::{
    StateManagementAdmission, StateManagementBackend, StateManagementBinding,
    StateManagementRecoveryAdmission, StateManagementReservation, StateManagementServices,
};
#[cfg(test)]
mod tests;

use crate::{
    invocation::{take_context, AuthenticatedInvocationContext, PrincipalPolicy},
    management::{
        ManagementLimits, ManagementOperation, ManagementPolicy, ManagementServiceAdapter,
    },
};
use latent_core::{ActivationClock, BoxFuture, PlatformError, PlatformErrorCode};
use latent_rpc::{control::v1 as c, phase4 as contract, transaction::v1 as t};
pub use lease::Phase4ResponseService;
use std::sync::Arc;
use tonic::{Request, Response, Status};

/// Constructed by the adapter after authentication, tenant comparison and finite
/// structural validation. The original context/deadline and preconditions survive
/// unchanged. The domain owner still seals current publication/data permissions.
pub struct Phase4Call {
    context: AuthenticatedInvocationContext,
    request: contract::Request,
}
impl Phase4Call {
    #[must_use]
    pub const fn context(&self) -> &AuthenticatedInvocationContext {
        &self.context
    }
    #[must_use]
    pub const fn request(&self) -> &contract::Request {
        &self.request
    }
    #[must_use]
    pub fn into_parts(self) -> (AuthenticatedInvocationContext, contract::Request) {
        (self.context, self.request)
    }
}

/// The actual node-owned response/recovery reservation and current read gate.
/// Implementations retain physical ownership until all body/frame holders drop;
/// returning a response, disconnect or requested cancellation is not retirement.
pub trait Phase4ResponseOwner: Send + Sync {
    fn reserved_bytes(&self) -> usize;
    /// Execute `publish` exactly once under the current policy/publication and
    /// namespace acceptance fence. This callback is short and performs no I/O.
    /// Original execution authority is never refreshed by this read fence.
    fn with_current(&self, publish: &mut dyn FnMut()) -> Result<(), PlatformError>;
}

pub struct OwnedPhase4Response {
    response: contract::Response,
    owner: Arc<dyn Phase4ResponseOwner>,
}
impl OwnedPhase4Response {
    #[must_use]
    pub fn new(response: contract::Response, owner: Arc<dyn Phase4ResponseOwner>) -> Self {
        Self { response, owner }
    }
}

/// Trusted composition port to #388/#397 and the established domain owners.
/// Admission reserves real work/response capacity before the future is returned.
/// Recovery calls use the reserved recovery lane even for reads. Dropping the
/// future must retain accepted physical work on its actual cleanup owner.
pub trait Phase4Runtime: Send + Sync {
    fn execute(
        &self,
        call: Phase4Call,
    ) -> BoxFuture<'_, Result<OwnedPhase4Response, PlatformError>>;
}

#[derive(Clone)]
pub struct Phase4Services {
    pub principals: Arc<dyn PrincipalPolicy>,
    pub management: Arc<dyn ManagementPolicy>,
    pub clock: Arc<dyn ActivationClock>,
}
#[derive(Clone)]
pub struct Phase4ServiceAdapter {
    runtime: Arc<dyn Phase4Runtime>,
    services: Phase4Services,
    limits: ManagementLimits,
}
impl ManagementServiceAdapter {
    /// Reuse the authenticated transport's exact management/principal owners.
    #[must_use]
    pub fn phase4_adapter(&self, runtime: Arc<dyn Phase4Runtime>) -> Phase4ServiceAdapter {
        let shared = self.shared_services();
        Phase4ServiceAdapter {
            runtime,
            services: Phase4Services {
                principals: shared.principals,
                management: shared.authorization,
                clock: shared.clock,
            },
            limits: self.limits().clone(),
        }
    }
}
impl Phase4ServiceAdapter {
    pub fn with_services(
        runtime: Arc<dyn Phase4Runtime>,
        limits: ManagementLimits,
        services: Phase4Services,
    ) -> Result<Self, PlatformError> {
        limits.validate()?;
        Ok(Self {
            runtime,
            services,
            limits,
        })
    }
    #[must_use]
    pub fn state_server(
        self,
    ) -> Phase4ResponseService<c::state_service_server::StateServiceServer<Self>> {
        let input = self
            .limits
            .max_request_bytes
            .min(contract::MAX_REQUEST_BYTES);
        let output = self
            .limits
            .max_response_bytes
            .min(contract::MAX_RESPONSE_BYTES);
        Phase4ResponseService::new(
            c::state_service_server::StateServiceServer::new(self)
                .max_decoding_message_size(input)
                .max_encoding_message_size(output),
        )
    }
    #[must_use]
    pub fn transaction_server(
        self,
    ) -> Phase4ResponseService<t::transaction_service_server::TransactionServiceServer<Self>> {
        let input = self
            .limits
            .max_request_bytes
            .min(contract::MAX_REQUEST_BYTES);
        let output = self
            .limits
            .max_response_bytes
            .min(contract::MAX_RESPONSE_BYTES);
        Phase4ResponseService::new(
            t::transaction_service_server::TransactionServiceServer::new(self)
                .max_decoding_message_size(input)
                .max_encoding_message_size(output),
        )
    }
    #[must_use]
    pub fn dispatcher_server(
        self,
    ) -> Phase4ResponseService<c::dispatcher_service_server::DispatcherServiceServer<Self>> {
        let input = self
            .limits
            .max_request_bytes
            .min(contract::MAX_REQUEST_BYTES);
        let output = self
            .limits
            .max_response_bytes
            .min(contract::MAX_RESPONSE_BYTES);
        Phase4ResponseService::new(
            c::dispatcher_service_server::DispatcherServiceServer::new(self)
                .max_decoding_message_size(input)
                .max_encoding_message_size(output),
        )
    }
    fn context<T>(
        &self,
        request: &mut Request<T>,
    ) -> Result<AuthenticatedInvocationContext, Status> {
        take_context(
            request,
            &self.limits.auth,
            self.services.principals.as_ref(),
        )
    }
    async fn execute(
        &self,
        context: AuthenticatedInvocationContext,
        request: contract::Request,
    ) -> Result<(contract::Response, lease::ResponseLease), Status> {
        request.validate().map_err(validation_status)?;
        if request.encoded_len() > self.limits.max_request_bytes {
            return Err(validation_status(contract::ValidationError::Capacity));
        }
        if request.is_node_management() {
            self.services
                .management
                .authorize(context.principal(), ManagementOperation::NodeControl)
                .map_err(crate::invocation::platform_status)?;
        } else {
            self.services
                .principals
                .authorize_target(
                    context.principal(),
                    request
                        .tenant()
                        .ok_or_else(|| validation_status(contract::ValidationError::Shape))?,
                )
                .map_err(crate::invocation::platform_status)?;
            if request.is_management() {
                self.services
                    .management
                    .authorize(context.principal(), ManagementOperation::Tenant)
                    .map_err(crate::invocation::platform_status)?;
            }
        }
        if context
            .transport_expires_at()
            .is_some_and(|deadline| self.services.clock.monotonic_now() >= deadline)
        {
            return Err(Status::deadline_exceeded(
                "the original request deadline has expired",
            ));
        }
        // Keep bounded selector/precondition metadata without cloning guest
        // payloads, expected-version lists or authorization contexts.
        let original = request.association();
        let mut owned = self
            .runtime
            .execute(Phase4Call { context, request })
            .await
            .map_err(crate::invocation::platform_status)?;
        owned
            .response
            .validate_association(&original)
            .map_err(|_| Status::internal("invalid Phase 4 runtime response"))?;
        public_error::sanitize(&mut owned.response, &self.limits.auth)?;
        let encoded = owned.response.encoded_len();
        if encoded > self.limits.max_response_bytes {
            return Err(validation_status(contract::ValidationError::Capacity));
        }
        let required = encoded
            .checked_mul(4)
            .and_then(|n| n.checked_add(16384))
            .ok_or_else(|| validation_status(contract::ValidationError::Capacity))?;
        if required > owned.owner.reserved_bytes() {
            return Err(Status::resource_exhausted(
                "Phase 4 response reservation is insufficient",
            ));
        }
        let lease = lease::ResponseLease::new(owned.owner);
        lease.check().map_err(crate::invocation::platform_status)?;
        Ok((owned.response, lease))
    }
}

fn validation_status(error: contract::ValidationError) -> Status {
    match error {
        contract::ValidationError::Capacity => {
            Status::resource_exhausted("Phase 4 data exceeds configured limits")
        }
        contract::ValidationError::UnsupportedProfile => {
            Status::failed_precondition("unsupported Phase 4 profile")
        }
        contract::ValidationError::Shape | contract::ValidationError::Association => {
            Status::invalid_argument("invalid Phase 4 request")
        }
    }
}
fn fence_error() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::Internal,
        message: "invalid Phase 4 publication fence".into(),
        retryable: false,
        details: Vec::new(),
    }
}

macro_rules! service {
    ($service:path; $(($name:ident,$request:ty,$response:ty,$variant:ident)),+ $(,)?) => {
        #[tonic::async_trait]
        impl $service for Phase4ServiceAdapter {
        $(
        async fn $name(&self,mut request:Request<$request>)->Result<Response<$response>,Status> {
            let context=self.context(&mut request)?;
            let (response,lease)=self.execute(context,contract::Request::from(request.into_inner())).await?;
            let contract::Response::$variant(value)=response else { return Err(Status::internal("invalid Phase 4 response type")); };
            let mut response=Response::new(*value);
            response.extensions_mut().insert(lease);
            Ok(response)
        }
        )+
        }
    };
}
service!(c::state_service_server::StateService;
    (inspect_namespace,c::InspectNamespaceRequest,c::InspectNamespaceResponse,InspectNamespace),
    (mutate_namespace,c::MutateNamespaceRequest,c::MutateNamespaceResponse,MutateNamespace),
    (select_entity,c::SelectEntityRequest,c::SelectEntityResponse,SelectEntity),
    (mutate_state,c::MutateStateRequest,c::MutateStateResponse,MutateState),
    (plan_effect_mutation,c::PlanEffectMutationRequest,c::PlanEffectMutationResponse,PlanEffectMutation),
    (get_state_operation_receipt,c::GetStateOperationReceiptRequest,c::GetStateOperationReceiptResponse,GetStateOperationReceipt));
service!(c::dispatcher_service_server::DispatcherService;
    (inspect_dispatcher,c::InspectDispatcherRequest,c::InspectDispatcherResponse,InspectDispatcher),
    (control_dispatcher,c::ControlDispatcherRequest,c::ControlDispatcherResponse,ControlDispatcher),
    (get_dispatcher_operation,c::GetDispatcherOperationRequest,c::GetDispatcherOperationResponse,GetDispatcherOperation));
service!(t::transaction_service_server::TransactionService;
    (invoke_command,t::InvokeCommandRequest,t::InvokeCommandResponse,InvokeCommand),
    (query,t::QueryRequest,t::QueryResponse,Query),
    (lookup_command,t::LookupCommandRequest,t::LookupCommandResponse,LookupCommand),
    (lookup_commit,t::LookupCommitRequest,t::LookupCommitResponse,LookupCommit),
    (get_effect,t::GetEffectRequest,t::GetEffectResponse,GetEffect),
    (list_effect_history,t::ListEffectHistoryRequest,t::ListEffectHistoryResponse,ListEffectHistory),
    (cancel_command,t::CancelCommandRequest,t::CancelCommandResponse,CancelCommand));

//! Explicit command/query/recovery clients over the existing bounded transport.
//!
//! Recovery selectors describe the original business request. They confer no
//! authority, and neither cancellation nor dropping a future proves abort.
//! Only a server-confirmed durable abort fence can accompany an explicit attempt.

mod models;
use crate::management;
pub use crate::management::CallOptions;
pub use models::*;
use std::{future::Future, pin::Pin};

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RecoveryIdentity {
    pub namespace: Option<NamespaceSelector>,
    pub command: Option<CommandSelector>,
    pub activation_id: Option<String>,
    pub operation_id: Option<String>,
    pub attempt_id: Option<String>,
    pub receipt_id: Option<String>,
    pub retry_request_id: Option<String>,
    pub effect_id: Option<String>,
    pub fingerprint_sha256: Option<Vec<u8>>,
    pub expected_abort: Option<AbortFence>,
    pub authorization_publication: Option<management::PublicationRef>,
    pub expected_versions: Vec<ExpectedVersion>,
    pub expected_generation: Option<u64>,
    pub expected_version: Option<Vec<u8>>,
    pub expected_policy_digest: Option<String>,
    pub dispatcher_action: Option<DispatcherAction>,
    pub dispatcher_expected_generation: Option<DispatcherGeneration>,
    pub effect_mutation: Option<PlanEffectMutationRequest>,
    pub effect_plan: Option<EffectManagementPlan>,
}

/// A validated durable observation survives a later local transport/cleanup error.
/// It contains bounded recovery metadata; the application payload is recovered
/// explicitly rather than copied into a failure object.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommandObservation {
    pub command_id: String,
    pub attempt_id: String,
    pub outcome: CommandOutcome,
    pub metadata_durable: bool,
    pub application_state_committed: bool,
    pub fingerprint_sha256: Vec<u8>,
    pub commit: Option<CommitReceipt>,
    pub proven_abort: Option<AbortFence>,
    pub source: Option<SourceIdentity>,
    pub retention: Option<LinkedRetention>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ObservedOutcome {
    Command(Box<CommandObservation>),
    State(Box<StateOperationReceipt>),
    Namespace(Box<NamespaceOperationReceipt>),
    Effect(Box<EffectReceipt>),
    Dispatcher(Box<DispatcherOperationReceipt>),
    /// A checked preparation descriptor supplies no mutation or provider authority.
    EffectPlan(Box<EffectManagementPlan>),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResponseMetadata {
    pub transport: management::ResponseMetadata,
    pub identity: RecoveryIdentity,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ClientResponse<Response> {
    pub value: Response,
    pub metadata: ResponseMetadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ClientFailure {
    pub transport: Box<management::ClientFailure>,
    pub identity: Box<RecoveryIdentity>,
    pub observed: Option<ObservedOutcome>,
}
impl std::fmt::Display for ClientFailure {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.transport.fmt(formatter)
    }
}
impl std::error::Error for ClientFailure {}

pub type ClientFuture<'call, Response> =
    Pin<Box<dyn Future<Output = Result<ClientResponse<Response>, ClientFailure>> + Send + 'call>>;

macro_rules! operation {
    ($method:ident, $request:ident, $response:ident) => {
        fn $method(&self, request: $request, options: CallOptions) -> ClientFuture<'_, $response>;
    };
}
pub trait TransactionClient: Send + Sync {
    operation!(invoke_command, InvokeCommandRequest, InvokeCommandResponse);
    operation!(query, QueryRequest, QueryResponse);
    operation!(lookup_command, LookupCommandRequest, LookupCommandResponse);
    operation!(lookup_commit, LookupCommitRequest, LookupCommitResponse);
    operation!(get_effect, GetEffectRequest, GetEffectResponse);
    operation!(
        list_effect_history,
        ListEffectHistoryRequest,
        ListEffectHistoryResponse
    );
    operation!(cancel_command, CancelCommandRequest, CancelCommandResponse);
    operation!(
        mutate_namespace,
        MutateNamespaceRequest,
        MutateNamespaceResponse
    );
    operation!(
        inspect_namespace,
        InspectNamespaceRequest,
        InspectNamespaceResponse
    );
    operation!(select_entity, SelectEntityRequest, SelectEntityResponse);
    operation!(mutate_state, MutateStateRequest, MutateStateResponse);
    operation!(
        plan_effect_mutation,
        PlanEffectMutationRequest,
        PlanEffectMutationResponse
    );
    operation!(
        get_state_operation_receipt,
        GetStateOperationReceiptRequest,
        GetStateOperationReceiptResponse
    );
    operation!(
        inspect_dispatcher,
        InspectDispatcherRequest,
        InspectDispatcherResponse
    );
    operation!(
        control_dispatcher,
        ControlDispatcherRequest,
        ControlDispatcherResponse
    );
    operation!(
        get_dispatcher_operation,
        GetDispatcherOperationRequest,
        GetDispatcherOperationResponse
    );
}

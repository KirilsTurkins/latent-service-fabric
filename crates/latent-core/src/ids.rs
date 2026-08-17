//! Strongly typed identifiers.

macro_rules! string_id {
    ($name:ident) => {
        #[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
        pub struct $name(pub String);
    };
}

macro_rules! numeric_id {
    ($name:ident, $inner:ty) => {
        #[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
        pub struct $name(pub $inner);
    };
}

string_id!(TenantId);
string_id!(NamespaceId);
string_id!(ServiceId);
string_id!(ReleaseDigest);
string_id!(RevisionId);
string_id!(ContractId);
string_id!(InterfaceId);
string_id!(FunctionId);
string_id!(ActivationId);
string_id!(NodeId);
string_id!(CellId);
string_id!(CapabilityId);
string_id!(CapabilityHandleId);
string_id!(EffectId);
string_id!(WorkflowId);
string_id!(WorkflowInstanceId);
string_id!(ContinuationId);
string_id!(StateNamespaceId);
string_id!(StateTransactionId);
string_id!(EntityKey);
string_id!(LeaseId);
string_id!(TriggerId);
string_id!(PolicyId);
string_id!(BindingId);
string_id!(DeploymentId);
string_id!(RouteId);
string_id!(PublisherId);
string_id!(ArtifactReference);
string_id!(IdempotencyKey);
string_id!(TraceId);
string_id!(SpanId);
string_id!(AuditEventId);
string_id!(SecretReference);
string_id!(BlobDigest);
string_id!(ProviderId);

numeric_id!(RouteGeneration, u64);
numeric_id!(RevisionGeneration, u64);
numeric_id!(SequenceNumber, u64);
numeric_id!(VersionToken, u64);

//! Transactional keyed state, entity lease, and state backend interfaces.

#![forbid(unsafe_code)]

use latent_core::{
    ActivationId, BoxFuture, EntityKey, LeaseId, Metadata, PlatformError, StateNamespaceId,
    StateTransactionId, VersionToken,
};

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct StateKey(pub Vec<u8>);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StateValue {
    pub bytes: Vec<u8>,
    pub media_type: String,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VersionedValue {
    pub value: StateValue,
    pub version: VersionToken,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StateContext {
    pub activation_id: ActivationId,
    pub namespace: StateNamespaceId,
    pub entity: Option<EntityKey>,
    pub snapshot_hint: Option<VersionToken>,
    pub read_budget_bytes: u64,
    pub write_budget_bytes: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StateMutation {
    Put { key: StateKey, value: StateValue },
    Delete { key: StateKey },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StateReadObservation {
    pub key: StateKey,
    pub observed_version: Option<VersionToken>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StateTransaction {
    pub id: StateTransactionId,
    pub context: StateContext,
    pub reads: Vec<StateReadObservation>,
    pub mutations: Vec<StateMutation>,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommitReceipt {
    pub transaction_id: StateTransactionId,
    pub committed_version: VersionToken,
    pub committed_at_unix_millis: u64,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EntityLease {
    pub id: LeaseId,
    pub namespace: StateNamespaceId,
    pub entity: EntityKey,
    pub owner: String,
    pub expires_at_unix_millis: u64,
}

pub trait StateBackend: Send + Sync {
    fn begin<'a>(
        &'a self,
        context: StateContext,
    ) -> BoxFuture<'a, Result<StateTransaction, PlatformError>>;

    fn read<'a>(
        &'a self,
        transaction: &'a mut StateTransaction,
        key: &'a StateKey,
    ) -> BoxFuture<'a, Result<Option<VersionedValue>, PlatformError>>;

    fn scan<'a>(
        &'a self,
        transaction: &'a mut StateTransaction,
        prefix: &'a StateKey,
        limit: u32,
    ) -> BoxFuture<'a, Result<Vec<(StateKey, VersionedValue)>, PlatformError>>;

    fn stage<'a>(
        &'a self,
        transaction: &'a mut StateTransaction,
        mutation: StateMutation,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn commit<'a>(
        &'a self,
        transaction: StateTransaction,
    ) -> BoxFuture<'a, Result<CommitReceipt, PlatformError>>;

    fn rollback<'a>(
        &'a self,
        transaction: StateTransaction,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;
}

pub trait EntityLeaseManager: Send + Sync {
    fn acquire<'a>(
        &'a self,
        namespace: &'a StateNamespaceId,
        entity: &'a EntityKey,
        owner: &'a str,
        ttl_millis: u64,
    ) -> BoxFuture<'a, Result<EntityLease, PlatformError>>;

    fn renew<'a>(
        &'a self,
        lease: &'a EntityLease,
        ttl_millis: u64,
    ) -> BoxFuture<'a, Result<EntityLease, PlatformError>>;

    fn release<'a>(&'a self, lease: EntityLease) -> BoxFuture<'a, Result<(), PlatformError>>;
}

use std::time::{Duration, Instant};

use latent_core::{EntityKey, StateNamespaceId, TenantId};

/// Host-derived routing scope. Construction validates shape, never authority.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct EntityScope {
    pub(super) tenant: TenantId,
    pub(super) namespace: StateNamespaceId,
    pub(super) incarnation: u64,
    pub(super) entity: EntityKey,
}

impl EntityScope {
    /// # Errors
    /// Returns `InvalidScope` for empty identities/keys or a zero incarnation.
    pub fn new(
        tenant: TenantId,
        namespace: StateNamespaceId,
        incarnation: u64,
        entity: EntityKey,
    ) -> Result<Self, EntityLaneError> {
        if tenant.0.is_empty() || namespace.0.is_empty() || incarnation == 0 || entity.0.is_empty()
        {
            return Err(EntityLaneError::InvalidScope);
        }
        Ok(Self {
            tenant,
            namespace,
            incarnation,
            entity,
        })
    }

    #[must_use]
    pub fn tenant(&self) -> &TenantId {
        &self.tenant
    }
    #[must_use]
    pub fn namespace(&self) -> &StateNamespaceId {
        &self.namespace
    }
    #[must_use]
    pub fn incarnation(&self) -> u64 {
        self.incarnation
    }
    #[must_use]
    pub fn entity(&self) -> &EntityKey {
        &self.entity
    }
}

/// All capacities are mandatory and finite; zero disables admission by error.
#[derive(Clone, Debug)]
pub struct EntityLaneLimits {
    pub global_queued: usize,
    pub tenant_queued: usize,
    pub entity_queued: usize,
    pub global_keys: usize,
    pub tenant_keys: usize,
    pub global_active: usize,
    pub tenant_active: usize,
    pub global_bytes: u64,
    pub tenant_bytes: u64,
    pub entity_bytes: u64,
    pub scope_bytes: usize,
    pub command_identity_bytes: usize,
    pub maximum_wait_age: Duration,
}

impl EntityLaneLimits {
    pub(super) fn validate(&self) -> Result<(), EntityLaneError> {
        if [
            self.global_queued,
            self.tenant_queued,
            self.entity_queued,
            self.global_keys,
            self.tenant_keys,
            self.global_active,
            self.tenant_active,
            self.scope_bytes,
            self.command_identity_bytes,
        ]
        .contains(&0)
            || [self.global_bytes, self.tenant_bytes, self.entity_bytes].contains(&0)
            || self.maximum_wait_age.is_zero()
        {
            return Err(EntityLaneError::InvalidLimits);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EntityLaneLimit {
    GlobalQueue,
    TenantQueue,
    EntityQueue,
    GlobalKeys,
    TenantKeys,
    GlobalBytes,
    TenantBytes,
    EntityBytes,
    ScopeBytes,
    CommandIdentityBytes,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EntityLaneError {
    InvalidLimits,
    InvalidScope,
    InvalidCommandIdentity,
    Expired,
    NestedTransactionalCall,
    Duplicate,
    Backpressure(EntityLaneLimit),
    StaleFence,
    Exhausted,
    Poisoned,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EntityCallKind {
    Root,
    /// Synchronous children of a transaction are unsupported for every key.
    SynchronousTransactionalChild,
}

/// The host supplies canonical caller/operation/command/attempt identity bytes.
/// These bytes are internal, bounded and never projected by errors or Debug.
pub struct EntityLaneRequest<T> {
    pub(super) scope: EntityScope,
    pub(super) command_identity: Vec<u8>,
    pub(super) payload: T,
    pub(super) retained_bytes: u64,
    pub(super) deadline: Instant,
    pub(super) call_kind: EntityCallKind,
}

impl<T> EntityLaneRequest<T> {
    pub fn new(
        scope: EntityScope,
        command_identity: Vec<u8>,
        payload: T,
        retained_bytes: u64,
        deadline: Instant,
        call_kind: EntityCallKind,
    ) -> Self {
        Self {
            scope,
            command_identity,
            payload,
            retained_bytes,
            deadline,
            call_kind,
        }
    }

    pub fn scope(&self) -> &EntityScope {
        &self.scope
    }
    pub fn payload(&self) -> &T {
        &self.payload
    }
    pub fn command_identity(&self) -> &[u8] {
        &self.command_identity
    }
    pub fn into_payload(self) -> T {
        self.payload
    }
}

pub struct EntitySubmitError<T> {
    pub reason: EntityLaneError,
    pub request: EntityLaneRequest<T>,
}

impl<T> std::fmt::Debug for EntitySubmitError<T> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("EntitySubmitError")
            .field("reason", &self.reason)
            .finish_non_exhaustive()
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EntityRejection {
    WaitExpired,
    AuthorityChanged,
    CancelledBeforeExecution,
}

pub struct EntityRejected<T> {
    pub reason: EntityRejection,
    pub request: EntityLaneRequest<T>,
}

pub enum EntityDispatch<T> {
    Ready(super::EntityExecution<T>),
    Rejected(EntityRejected<T>),
}

pub enum EntityCancellation<T> {
    Queued(EntityLaneRequest<T>),
    ActiveRequested,
    Retired,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EntityWaitStatus {
    Queued,
    Active {
        generation: u64,
        cleanup: bool,
        cancellation_requested: bool,
    },
    /// Only local eligibility retired; recover durable outcomes from the store.
    Retired,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct EntityLaneSnapshot {
    pub keys: usize,
    pub queued: usize,
    pub active: usize,
    pub cleanup: usize,
    pub queued_bytes: u64,
    pub active_bytes: u64,
}

impl EntityLaneSnapshot {
    #[must_use]
    pub fn retained_bytes(self) -> u64 {
        self.queued_bytes + self.active_bytes
    }
}

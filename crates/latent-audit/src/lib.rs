//! Immutable administrative and security audit event interfaces.

#![forbid(unsafe_code)]

use latent_core::{AuditEventId, BoxFuture, Metadata, PlatformError, TenantId};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AuditOutcome {
    Succeeded,
    Denied,
    Failed,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuditActor {
    pub subject: String,
    pub actor_type: String,
    pub tenant: Option<TenantId>,
    pub attributes: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuditEvent {
    pub id: AuditEventId,
    pub actor: AuditActor,
    pub action: String,
    pub resource: String,
    pub outcome: AuditOutcome,
    pub occurred_at_unix_millis: u64,
    pub reason: Option<String>,
    pub attributes: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuditQuery {
    pub tenant: Option<TenantId>,
    pub actor: Option<String>,
    pub action: Option<String>,
    pub resource_prefix: Option<String>,
    pub from_unix_millis: Option<u64>,
    pub to_unix_millis: Option<u64>,
    pub limit: u32,
}

pub trait AuditStore: Send + Sync {
    fn append<'a>(&'a self, event: AuditEvent) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn query<'a>(
        &'a self,
        query: AuditQuery,
    ) -> BoxFuture<'a, Result<Vec<AuditEvent>, PlatformError>>;
}

pub trait AuditPublisher: Send + Sync {
    fn publish<'a>(&'a self, event: AuditEvent) -> BoxFuture<'a, Result<(), PlatformError>>;
}

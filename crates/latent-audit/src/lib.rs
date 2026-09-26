//! Immutable administrative and security audit event interfaces.

#![forbid(unsafe_code)]

mod durable;
mod phase2;
pub use durable::*;

pub use phase2::{
    BoundedPhase2AuditJournal, Phase2AuditCursor, Phase2AuditEvent, Phase2AuditEventKind,
    Phase2AuditIdentity, Phase2AuditLimits, Phase2AuditPage, Phase2AuditSnapshot,
};

use latent_core::{Metadata, TenantId};

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "kebab-case")]
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

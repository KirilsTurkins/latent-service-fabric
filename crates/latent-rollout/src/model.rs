use latent_artifacts::{ReleaseAuditAck, ReleaseAuditStatus};
use latent_control_store::rollouts::RolloutOperationReceipt;
use latent_core::PlatformError;

/// The exact store preview plus the maximum acknowledgement encoding allowance.
pub struct MutationPreview<'a> {
    pub receipt: &'a RolloutOperationReceipt,
    pub replayed: bool,
    pub audit_ack: ReleaseAuditAck,
    pub observation: Option<crate::RolloutObservation>,
}

/// A rename-committed receipt remains a committed result even when sync or audit
/// acknowledgement is uncertain. Inspect the independent fields explicitly.
pub struct MutationResult {
    pub receipt: RolloutOperationReceipt,
    pub replayed: bool,
    pub durability: Result<(), PlatformError>,
    pub audit_ack: ReleaseAuditAck,
    pub observation: Option<crate::RolloutObservation>,
}

#[derive(Debug)]
pub struct RolloutFailure {
    pub error: PlatformError,
    pub audit_ack: ReleaseAuditAck,
}

impl RolloutFailure {
    pub(crate) fn new(error: PlatformError, audit_ack: ReleaseAuditAck) -> Self {
        Self {
            error: crate::bounded(error),
            audit_ack,
        }
    }
}

pub(crate) const fn no_attempt() -> ReleaseAuditAck {
    ReleaseAuditAck {
        status: ReleaseAuditStatus::AuditUnavailable,
        attempt_sequence: None,
    }
}

pub(crate) const fn maximum_ack() -> ReleaseAuditAck {
    ReleaseAuditAck {
        status: ReleaseAuditStatus::OutcomeUnknown,
        attempt_sequence: Some(u64::MAX),
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
#[expect(
    clippy::struct_excessive_bools,
    reason = "Snapshot records independent startup, worker lifetime, admission and failure facts that may coexist"
)]
pub struct CoordinatorSnapshot {
    pub queued_commands: usize,
    pub active_commands: usize,
    pub retained_request_bytes: usize,
    pub response_owners: usize,
    pub response_bytes: usize,
    pub accepted_commands: u64,
    pub completed_commands: u64,
    pub worker_live: bool,
    pub worker_started: bool,
    pub worker_completed: bool,
    pub closed: bool,
    pub failed: bool,
    pub canary_windows: usize,
    pub canary_metadata_bytes: usize,
}

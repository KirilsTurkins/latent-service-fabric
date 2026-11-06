//! Mandatory finite audit composition for publication maintenance on a bounded
//! control worker. Authentication remains the calling host adapter's duty.
mod identity;

use super::{ReleaseAuditAck, ReleaseAuditStatus};
use crate::{
    DirectoryArtifactRepository, PublicationDeletionLookup, PublicationDeletionReceipt,
    PublicationDeletionRequest, PublicationReclamationLookup, PublicationReclamationReceipt,
    PublicationReclamationRequest, PublicationRetentionLookup, PublicationRetentionReceipt,
    PublicationRetentionRequest,
};
use latent_audit::{AuditAttempt, AuditHandle, AuditOperationAttempt, AuditOperationResult};
use latent_core::{PlatformError, PlatformErrorCode};
use serde::Serialize;
use std::time::Duration;

/// Host-only requests. The scope/actor must come from the authenticated adapter,
/// never from untrusted JSON or a caller's possession of publication identifiers.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", content = "request", rename_all = "kebab-case")]
pub enum PublicationMaintenanceRequest {
    Retention(PublicationRetentionRequest),
    Deletion(PublicationDeletionRequest),
    Reclamation(PublicationReclamationRequest),
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", content = "receipt", rename_all = "kebab-case")]
pub enum PublicationMaintenanceReceipt {
    Retention(PublicationRetentionReceipt),
    Deletion(PublicationDeletionReceipt),
    Reclamation(PublicationReclamationReceipt),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicationMaintenanceResult {
    pub receipt: PublicationMaintenanceReceipt,
    pub replay: bool,
}

/// Catalog disposition and audit durability are deliberately separate. Losing
/// the audit acknowledgement cannot turn a committed unlink into a rejection.
#[derive(Debug)]
pub struct PublicationMaintenanceOutcome {
    pub result: Result<PublicationMaintenanceResult, PlatformError>,
    pub audit: ReleaseAuditAck,
}

/// One affine attempt. The journal reserves the attempt AND its outcome before
/// any mutation is permitted. No emergency-revocation exception applies here.
pub struct PublicationAuditGuard {
    audit: AuditHandle,
    identity: Option<AuditOperationAttempt>,
    attempt: Option<AuditAttempt>,
    ack: ReleaseAuditAck,
    previewed: bool,
}
impl PublicationAuditGuard {
    #[must_use]
    pub fn new(audit: &AuditHandle) -> Self {
        Self {
            audit: audit.clone(),
            identity: None,
            attempt: None,
            ack: ReleaseAuditAck {
                status: ReleaseAuditStatus::AuditUnavailable,
                attempt_sequence: None,
            },
            previewed: false,
        }
    }

    /// Call only after complete response preflight, outside native catalog
    /// fences, on an existing bounded control worker. Waiting opens no worker.
    pub fn preview(
        &mut self,
        request: &PublicationMaintenanceRequest,
        result: &PublicationMaintenanceResult,
    ) -> Result<(), PlatformError> {
        if self.previewed {
            return Err(invalid());
        }
        self.previewed = true;
        let identity = identity::attempt(request, result)?;
        // Validate both complete outcome envelopes before the durable attempt.
        // The worst-case timestamp avoids a later decimal-width surprise.
        let mut committed = identity::committed(&identity);
        committed.occurred_at_unix_millis = u64::MAX;
        self.audit.preflight_conclusion(&identity, &committed)?;
        let mut unknown = identity::unknown();
        unknown.occurred_at_unix_millis = u64::MAX;
        self.audit.preflight_conclusion(&identity, &unknown)?;
        let attempt = self
            .audit
            .reserve_control_critical(&identity)?
            .begin()
            .blocking_wait()?;
        self.ack.attempt_sequence = Some(attempt.sequence());
        self.ack.status = ReleaseAuditStatus::OutcomeUnknown;
        self.identity = Some(identity);
        self.attempt = Some(attempt);
        self.attempt
            .as_mut()
            .expect("retained attempt")
            .mutation_started()
    }

    /// May be called after success or error. Only the exact retained catalog
    /// receipt establishes Committed; an absent/evicted receipt is Unknown.
    /// This function never invokes a mutation or creates a replacement ID.
    pub fn finish(mut self, repository: &DirectoryArtifactRepository) -> ReleaseAuditAck {
        let Some(attempt) = self.attempt.take() else {
            return self.ack;
        };
        let conclusion = lookup(
            repository,
            self.identity.as_ref().expect("retained identity"),
        )
        .unwrap_or_else(|_| identity::unknown());
        let known = conclusion.result == AuditOperationResult::Committed;
        if attempt.finish(conclusion).blocking_wait().is_ok() && known {
            self.ack.status = ReleaseAuditStatus::Durable;
        }
        self.ack
    }
}

impl DirectoryArtifactRepository {
    /// Mandatory-audit host facade. Response preflight runs before journal
    /// admission; native owners recheck all fences after it. Requests, deadlines,
    /// content budgets and original-operation semantics remain the native ones.
    /// This is synchronous and belongs only on a bounded control worker.
    pub fn audited_publication_maintenance(
        &self,
        audit: &AuditHandle,
        request: &PublicationMaintenanceRequest,
        timeout: Duration,
        preflight: &mut dyn FnMut(&PublicationMaintenanceResult) -> Result<(), PlatformError>,
    ) -> PublicationMaintenanceOutcome {
        let mut guard = PublicationAuditGuard::new(audit);
        let mut preview = |result: PublicationMaintenanceResult| {
            preflight(&result)?;
            guard.preview(request, &result)
        };
        let result = match request {
            PublicationMaintenanceRequest::Retention(request) => self
                .change_publication_retention(request, timeout, &mut |v| {
                    preview(PublicationMaintenanceResult {
                        receipt: PublicationMaintenanceReceipt::Retention(v.receipt.clone()),
                        replay: v.replay,
                    })
                })
                .map(|v| PublicationMaintenanceResult {
                    receipt: PublicationMaintenanceReceipt::Retention(v.receipt),
                    replay: v.replay,
                }),
            PublicationMaintenanceRequest::Deletion(request) => self
                .tombstone_publications(request, timeout, &mut |v| {
                    preview(PublicationMaintenanceResult {
                        receipt: PublicationMaintenanceReceipt::Deletion(v.receipt.clone()),
                        replay: v.replay,
                    })
                })
                .map(|v| PublicationMaintenanceResult {
                    receipt: PublicationMaintenanceReceipt::Deletion(v.receipt),
                    replay: v.replay,
                }),
            PublicationMaintenanceRequest::Reclamation(request) => self
                .reclaim_tombstoned_publications(request, timeout, &mut |v| {
                    preview(PublicationMaintenanceResult {
                        receipt: PublicationMaintenanceReceipt::Reclamation(v.receipt.clone()),
                        replay: v.replay,
                    })
                })
                .map(|v| PublicationMaintenanceResult {
                    receipt: PublicationMaintenanceReceipt::Reclamation(v.receipt),
                    replay: v.replay,
                }),
        };
        PublicationMaintenanceOutcome {
            result,
            audit: guard.finish(self),
        }
    }
}

/// Reconcile only this owner's recovered attempts, after native catalog recovery
/// and before generic release-audit reconciliation or new mutation admission.
/// Unknown or evicted receipts remain Unknown. Uncertain catalog health refuses
/// reconciliation so a future healthy reopen can still inspect the original ID.
pub async fn reconcile_publication_maintenance_audit(
    audit: &AuditHandle,
    repository: &DirectoryArtifactRepository,
) -> Result<(), PlatformError> {
    for pending in audit.pending_attempts()? {
        if identity::owns(pending.attempt().action) {
            let conclusion = lookup(repository, pending.attempt())?;
            audit
                .reconcile(pending.sequence(), conclusion)?
                .wait()
                .await?;
        }
    }
    Ok(())
}

fn lookup(
    repository: &DirectoryArtifactRepository,
    expected: &AuditOperationAttempt,
) -> Result<latent_audit::AuditOperationConclusion, PlatformError> {
    use latent_audit::AuditControlAction as Action;
    let scope = super::mapping::lifecycle_scope(&expected.scope);
    let receipt = match expected.action {
        Action::PublicationPin | Action::PublicationUnpin => {
            match repository.publication_retention_operation(&scope, &expected.operation_id)? {
                PublicationRetentionLookup::Found(r) => {
                    Some(PublicationMaintenanceReceipt::Retention(r))
                }
                PublicationRetentionLookup::Unknown => None,
                PublicationRetentionLookup::Uncertain => return Err(uncertain()),
            }
        }
        Action::PublicationDelete => {
            match repository.publication_deletion_operation(&scope, &expected.operation_id)? {
                PublicationDeletionLookup::Found(r) => {
                    Some(PublicationMaintenanceReceipt::Deletion(r))
                }
                PublicationDeletionLookup::Unknown => None,
                PublicationDeletionLookup::Uncertain => return Err(uncertain()),
            }
        }
        Action::PublicationReclaim => {
            match repository.publication_reclamation_operation(&scope, &expected.operation_id)? {
                PublicationReclamationLookup::Found(r) => {
                    Some(PublicationMaintenanceReceipt::Reclamation(r))
                }
                PublicationReclamationLookup::Unknown => None,
                PublicationReclamationLookup::Uncertain => return Err(uncertain()),
            }
        }
        _ => return Err(invalid()),
    };
    let Some(receipt) = receipt else {
        return Ok(identity::unknown());
    };
    let request = identity::request(&receipt);
    let actual = identity::attempt(
        &request,
        &PublicationMaintenanceResult {
            receipt,
            replay: expected.replay,
        },
    )?;
    // Timestamp is observational; every captured authority/precondition/digest
    // and replay flag must match. It is not refreshed during recovery.
    let mut normalized = actual;
    normalized.occurred_at_unix_millis = expected.occurred_at_unix_millis;
    Ok(if normalized == *expected {
        identity::committed(expected)
    } else {
        identity::unknown()
    })
}

fn invalid() -> PlatformError {
    crate::publication_retention::failure(
        PlatformErrorCode::InvalidArgument,
        "publication-audit-preview-invalid",
    )
}
fn uncertain() -> PlatformError {
    crate::publication_retention::failure(
        PlatformErrorCode::Unavailable,
        "publication-audit-original-outcome-uncertain-reopen",
    )
}

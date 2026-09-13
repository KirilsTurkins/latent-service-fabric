//! Inline managed deployment auditing; this module starts no control worker.
mod mapping;
mod recovery;
mod rejection;
#[cfg(all(test, unix))]
mod tests;

pub use recovery::reconcile_deployment_audit;
pub use rejection::{record_rejection, DeploymentRejectionIdentity};

use latent_artifacts::ReleaseAuditAck;
use latent_audit::{AuditAttempt, AuditHandle, AuditOperationAttempt};
use latent_control_store::{
    deployment_operations::{
        DeploymentOperationCommit, DeploymentOperationRead, DeploymentOperationReceipt,
        PreparedDeploymentOperation,
    },
    DeploymentStore,
};
use std::time::Instant;

/// Precharge this finite allowance for the helper's identity and codec scratch.
/// Audit queue payloads and the store response retain their independent charges.
pub const MAX_AUDIT_RETAINED_BYTES: usize =
    latent_control_store::deployment_operations::MAX_OPERATION_SCRATCH_BYTES;

pub struct ManagedDeploymentAudit {
    attempt: Option<AuditAttempt>,
    expected: AuditOperationAttempt,
    acknowledgement: ReleaseAuditAck,
    started: bool,
}

impl ManagedDeploymentAudit {
    /// Call only after the exact success/error transport response is preflighted.
    pub async fn begin(
        audit: &AuditHandle,
        receipt: &DeploymentOperationReceipt,
        replayed: bool,
        expires: Instant,
    ) -> crate::Result<Self> {
        check_deadline(expires)?;
        let expected = mapping::attempt(receipt, replayed)?;
        audit.preflight_conclusion(&expected, &mapping::conclusion(&expected, Some(receipt)))?;
        audit.preflight_conclusion(&expected, &mapping::conclusion(&expected, None))?;
        let reservation = audit.try_reserve_critical(&expected)?;
        check_deadline(expires)?;
        let attempt = tokio::time::timeout_at(expires.into(), reservation.begin().wait())
            .await
            .map_err(|_| deadline())??;
        // commit checks the absolute deadline again even if this ready result
        // was delivered after expiry. The returned guard preserves the ack.
        let acknowledgement = crate::audit::ack(attempt.sequence(), false);
        Ok(Self {
            attempt: Some(attempt),
            expected,
            acknowledgement,
            started: false,
        })
    }

    #[must_use]
    pub const fn acknowledgement(&self) -> ReleaseAuditAck {
        self.acknowledgement
    }

    #[must_use]
    pub fn matches(&self, actual: &DeploymentOperationCommit) -> bool {
        actual.replayed == self.expected.replay && mapping::matches(&self.expected, &actual.receipt)
    }

    /// The marker and exact-owner synchronous commit have no suspension point.
    pub fn commit(
        &mut self,
        repository: &dyn DeploymentStore,
        prepared: PreparedDeploymentOperation,
        expires: Instant,
    ) -> crate::Result<DeploymentOperationRead<DeploymentOperationCommit>> {
        check_deadline(expires)?;
        if self.started
            || prepared.replayed() != self.expected.replay
            || !mapping::matches(&self.expected, prepared.preview())
        {
            return Err(invalid());
        }
        let attempt = self.attempt.as_mut().ok_or_else(invalid)?;
        attempt.mutation_started()?;
        self.started = true;
        repository.commit_operation(prepared)
    }

    /// Caller loss during this wait may leave Unknown; exact receipt lookup is
    /// the independent recovery surface. This does not grant execution authority.
    pub async fn finish(
        mut self,
        repository: &dyn DeploymentStore,
        actual: Option<&DeploymentOperationCommit>,
        expires: Instant,
    ) -> ReleaseAuditAck {
        let terminal = match actual {
            Some(actual) if !self.matches(actual) => mapping::conclusion(&self.expected, None),
            Some(actual) if actual.durability.is_ok() => {
                mapping::conclusion(&self.expected, Some(&actual.receipt))
            }
            _ => recovery::lookup(repository, &self.expected, expires)
                .await
                .unwrap_or_else(|_| mapping::conclusion(&self.expected, None)),
        };
        let known = terminal.result == latent_audit::AuditOperationResult::Committed;
        let Some(attempt) = self.attempt.take() else {
            return self.acknowledgement;
        };
        let persisted = tokio::time::timeout_at(expires.into(), attempt.finish(terminal).wait())
            .await
            .is_ok_and(|result| result.is_ok())
            && Instant::now() < expires;
        self.acknowledgement = crate::audit::ack(
            self.acknowledgement
                .attempt_sequence
                .expect("accepted attempt"),
            known && persisted,
        );
        self.acknowledgement
    }
}

fn check_deadline(expires: Instant) -> crate::Result<()> {
    if Instant::now() >= expires {
        Err(deadline())
    } else {
        Ok(())
    }
}
fn deadline() -> latent_core::PlatformError {
    crate::error(
        latent_core::PlatformErrorCode::DeadlineExceeded,
        "deployment-audit-deadline",
    )
}
fn invalid() -> latent_core::PlatformError {
    crate::error(
        latent_core::PlatformErrorCode::InvalidArgument,
        "deployment-audit-identity-mismatch",
    )
}

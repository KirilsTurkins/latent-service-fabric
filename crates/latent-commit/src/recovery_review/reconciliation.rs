//! First-profile review of actual staged older history. A Pending/no-attempt
//! effect and an old KnownFailed receipt may both precede a later remote send.
//! The original restored rows supply no general redrive/nonexecution proof.

mod page;
pub use page::{ReconciliationCursor, RestoreEffectFact, RestoreEffectPage, RestoreEffectReview};

use super::{
    atomic_error, checkpoint, review_snapshot, source, RecoveryReviewError, RecoveryReviewOwners,
    RecoveryReviewRequest, ReviewedRestoreInput,
};
use crate::atomic::{self, CommandRecord, Outcome};
use latent_effects::{
    dispatch::{Disposition, EffectRecord},
    dispatch_store::effect_management::{
        EffectManagementCatalog, EffectManagementPlan, PLAN_PREFIX,
    },
};
use latent_state::{
    embedded::{Family, ReadView, RowKey, StoreError},
    namespace::{history::history_key, namespace_record_key},
    recovery::{snapshot::visit_view, RecoveryGuard, RecoveryStatus},
};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::time::Instant;

/// Descriptive copies only. Changing these public counts cannot change the
/// private plan, original guard, grant, effect disposition or retry proof.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct RestoreReconciliationCounts {
    pub namespaces: u64,
    pub pending_commands: u64,
    pub terminal_commands: u64,
    pub historical_aborts: u64,
    pub expired_command_floors: u64,
    pub inbox_rows: u64,
    pub nonterminal_effects: u64,
    pub pending_without_attempt: u64,
    pub known_failed: u64,
    pub uncertain: u64,
    pub dispatching: u64,
    pub retry_scheduled: u64,
    pub policy_blocked: u64,
    pub terminal_effects: u64,
    pub provider_acknowledged: u64,
    pub provider_confirmed: u64,
    pub administrator_terminated: u64,
    pub expired_effects: u64,
    pub original_dead_letters: u64,
    pub unfinished_management_plans: u64,
    pub unfinished_migrations: u64,
}
impl RestoreReconciliationCounts {
    fn observe(
        &mut self,
        view: &ReadView,
        key: &RowKey,
        bytes: &[u8],
    ) -> Result<(), RecoveryReviewError> {
        match key.family {
            Family::Namespace if key.key.starts_with(b"ns-v1\0") => add(&mut self.namespaces)?,
            Family::Command => {
                let (format, _) = atomic::durable_row_format(key, bytes).map_err(atomic_error)?;
                if format == "latent.command-retired.v1" {
                    add(&mut self.expired_command_floors)?;
                } else {
                    let record = CommandRecord::decode(bytes).map_err(atomic_error)?;
                    if record.outcome() == Outcome::Pending {
                        add(&mut self.pending_commands)?;
                    } else {
                        add(&mut self.terminal_commands)?;
                        if record.outcome() == Outcome::Aborted {
                            add(&mut self.historical_aborts)?;
                        }
                    }
                }
            }
            Family::Inbox => add(&mut self.inbox_rows)?,
            Family::Outbox => {
                self.effect(
                    &EffectRecord::decode(bytes)
                        .map_err(|_| RecoveryReviewError::Source(StoreError::Corrupt))?,
                )?;
            }
            Family::Maintenance if key.key.starts_with(PLAN_PREFIX) => {
                let plan = EffectManagementPlan::decode(bytes)
                    .map_err(|_| RecoveryReviewError::Source(StoreError::Corrupt))?;
                // Expiry is not physical retirement. The original linked
                // reservation remains protective until its real receipt exists.
                if EffectManagementCatalog::lookup(view, &plan)
                    .map_err(|_| RecoveryReviewError::Source(StoreError::Corrupt))?
                    .is_none()
                {
                    add(&mut self.unfinished_management_plans)?;
                }
            }
            Family::Maintenance
                if key
                    .key
                    .starts_with(latent_state::recovery::migration::PROGRESS_PREFIX) =>
            {
                let progress =
                    latent_state::recovery::migration::AggregateMigrationProgress::decode(bytes)
                        .map_err(source)?;
                if !progress.completed() {
                    add(&mut self.unfinished_migrations)?;
                }
            }
            _ => {}
        }
        Ok(())
    }

    fn effect(&mut self, record: &EffectRecord) -> Result<(), RecoveryReviewError> {
        if record.disposition().terminal() {
            add(&mut self.terminal_effects)?;
            match RestoreEffectFact::capture(record) {
                RestoreEffectFact::ProviderConfirmed => add(&mut self.provider_confirmed)?,
                RestoreEffectFact::ProviderAcknowledged => add(&mut self.provider_acknowledged)?,
                RestoreEffectFact::Expired => add(&mut self.expired_effects)?,
                RestoreEffectFact::AdministratorTerminated => {
                    add(&mut self.administrator_terminated)?;
                }
                RestoreEffectFact::OriginalDeadLetter => add(&mut self.original_dead_letters)?,
                RestoreEffectFact::UnknownSinceSnapshot => {
                    return Err(RecoveryReviewError::Source(StoreError::Corrupt));
                }
            }
        } else {
            add(&mut self.nonterminal_effects)?;
            match record.disposition() {
                Disposition::Pending if record.attempts() == 0 => {
                    add(&mut self.pending_without_attempt)?;
                }
                Disposition::KnownFailed => add(&mut self.known_failed)?,
                Disposition::Uncertain => add(&mut self.uncertain)?,
                Disposition::Dispatching => add(&mut self.dispatching)?,
                Disposition::RetryScheduled => add(&mut self.retry_scheduled)?,
                Disposition::PolicyBlocked => add(&mut self.policy_blocked)?,
                _ => return Err(RecoveryReviewError::Source(StoreError::Corrupt)),
            }
        }
        Ok(())
    }
}

/// No native view, current authority or resume approval is retained here.
/// The host keeps its SAME original view/custody/auth/audit/capacity physically
/// alive through each page and encoded response. Cursors are job-local only.
#[derive(Serialize)]
pub struct RestoreReconciliationPlan {
    #[serde(skip)]
    view_identity: usize,
    #[serde(skip)]
    deadline: Instant,
    operation_digest: [u8; 32],
    snapshot_digest: [u8; 32],
    window_digest: [u8; 32],
    original_guard: Vec<u8>,
    runtime_digest: [u8; 32],
    source_store_identity: Vec<u8>,
    observed_store_identity: Vec<u8>,
    rows_digest: [u8; 32],
    rows: u64,
    logical_bytes: u64,
    counts: RestoreReconciliationCounts,
}
impl RestoreReconciliationPlan {
    /// Review actual fully staged rows with installed original codecs/evidence.
    /// Root must independently prove Fresh destination and external controls;
    /// neither matching identity bytes nor this plan supplies that proof.
    pub fn capture(
        view: &ReadView,
        input: &ReviewedRestoreInput,
        request: RecoveryReviewRequest<'_>,
        owners: &mut impl RecoveryReviewOwners,
        mut current: impl FnMut() -> Result<(), StoreError>,
    ) -> Result<Self, RecoveryReviewError> {
        checkpoint(request.deadline, &mut current)?;
        if request.metadata.runtime_digest != input.runtime_digest() {
            return Err(RecoveryReviewError::Review(StoreError::Conflict));
        }
        let guard = RecoveryGuard::capture(view)
            .map_err(source)?
            .ok_or(RecoveryReviewError::Review(StoreError::Conflict))?;
        let window_digest = input.window().digest().map_err(source)?;
        if guard.status() != RecoveryStatus::ReconciliationRequired
            || guard.operation_digest() != input.operation_digest()
            || guard.snapshot_digest() != input.window().snapshot_digest()
            || guard.window_digest() != window_digest
        {
            return Err(RecoveryReviewError::Review(StoreError::Conflict));
        }
        require_layout(view, input)?;
        let reviewed = review_snapshot(view, request, owners, &mut current)?;
        let mut counts = RestoreReconciliationCounts::default();
        let mut refusal = None;
        let walked = visit_view(view, request.deadline, |_, key, bytes| {
            let observed = (|| {
                checkpoint(request.deadline, &mut current)?;
                counts.observe(view, key, bytes)
            })();
            observed.map_err(|error| {
                refusal = Some(error);
                StoreError::Invalid
            })
        });
        if let Some(error) = refusal {
            return Err(error);
        }
        let walked = walked.map_err(source)?;
        if counts.namespaces
            != u64::try_from(input.window().namespaces().len())
                .map_err(|_| RecoveryReviewError::Capacity)?
        {
            return Err(RecoveryReviewError::Review(StoreError::Conflict));
        }
        checkpoint(request.deadline, &mut current)?;
        Ok(Self {
            view_identity: view.identity(),
            deadline: request.deadline,
            operation_digest: input.operation_digest(),
            snapshot_digest: guard.snapshot_digest(),
            window_digest,
            original_guard: guard.encode().map_err(source)?,
            runtime_digest: request.metadata.runtime_digest,
            source_store_identity: input.current().source_controls().store_identity().encode(),
            observed_store_identity: reviewed.source_controls().store_identity().encode(),
            rows_digest: walked.digest,
            rows: walked.rows,
            logical_bytes: walked.logical_bytes,
            counts,
        })
    }

    #[must_use]
    pub const fn counts(&self) -> RestoreReconciliationCounts {
        self.counts
    }
    #[must_use]
    pub const fn rows_digest(&self) -> [u8; 32] {
        self.rows_digest
    }
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, RecoveryReviewError> {
        let bytes = serde_json::to_vec(self)
            .map_err(|_| RecoveryReviewError::Review(StoreError::Invalid))?;
        if bytes.len() > 16 * 1024 {
            return Err(RecoveryReviewError::Capacity);
        }
        Ok(bytes)
    }
    pub fn digest(&self) -> Result<[u8; 32], RecoveryReviewError> {
        let mut hash = Sha256::new();
        hash.update(b"latent-original-restore-reconciliation-v1\0");
        hash.update(self.canonical_bytes()?);
        Ok(hash.finalize().into())
    }

    /// Conservative first-profile prerequisite ONLY. Pending/no-attempt and
    /// prior KnownFailed work cannot be dismissed by acknowledging a loss window.
    /// Actual current permissions, physical retirement, continuity, fresh root,
    /// critical audit and explicit namespace/dispatcher resume remain separate.
    pub fn require_terminal_review(
        &self,
        view: &ReadView,
        mut current: impl FnMut() -> Result<(), StoreError>,
    ) -> Result<(), RecoveryReviewError> {
        checkpoint(self.deadline, &mut current)?;
        self.require_view(view)?;
        if self.counts.nonterminal_effects != 0
            || self.counts.pending_commands != 0
            || self.counts.unfinished_management_plans != 0
            || self.counts.unfinished_migrations != 0
        {
            return Err(RecoveryReviewError::Review(StoreError::Conflict));
        }
        checkpoint(self.deadline, &mut current)
    }

    fn require_view(&self, view: &ReadView) -> Result<(), RecoveryReviewError> {
        if view.identity() != self.view_identity
            || view
                .get(&latent_state::recovery::guard_key())
                .map_err(source)?
                .as_deref()
                != Some(self.original_guard.as_slice())
        {
            return Err(RecoveryReviewError::Review(StoreError::Conflict));
        }
        Ok(())
    }
}

fn require_layout(
    view: &ReadView,
    input: &ReviewedRestoreInput,
) -> Result<(), RecoveryReviewError> {
    for window in input.window().namespaces() {
        let (record, _) = window.snapshot().decode().map_err(source)?;
        let key = RowKey {
            family: Family::Namespace,
            key: namespace_record_key(&record.tenant, &record.id)
                .map_err(|_| RecoveryReviewError::Review(StoreError::Invalid))?,
        };
        let history_key = history_key(&record.tenant, &record.id, record.version.incarnation)
            .map_err(|_| RecoveryReviewError::Review(StoreError::Invalid))?;
        let proposed = window.proposed_history().map_err(source)?;
        if view.get(&key).map_err(source)?.as_deref() != Some(window.snapshot().record.as_slice())
            || view.get(&history_key).map_err(source)?.as_deref()
                != Some(
                    proposed
                        .encode()
                        .map_err(|_| RecoveryReviewError::Review(StoreError::Invalid))?
                        .as_slice(),
                )
        {
            return Err(RecoveryReviewError::Review(StoreError::Conflict));
        }
    }
    Ok(())
}

fn add(value: &mut u64) -> Result<(), RecoveryReviewError> {
    *value = value.checked_add(1).ok_or(RecoveryReviewError::Capacity)?;
    Ok(())
}

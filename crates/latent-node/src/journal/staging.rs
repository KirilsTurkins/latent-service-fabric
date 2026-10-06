//! One fixed observation from the original command host; no business authority.
use std::sync::{Arc, Weak};

use latent_core::{ActivationId, ActivationPhase, PlatformError, PlatformErrorCode};
use latent_executor::transaction::{
    TransactionStagingIdentity, TransactionStagingObserver, TransactionStagingProgress,
};

use super::{error, Inner, LocalActivationJournal, TERMINAL_RESERVE_BYTES};

pub(super) const RECORD_BYTES: usize = 2048;

/// Privileged descriptive staging evidence. It records neither persistence nor
/// a terminal disposition and cannot authorize retry, commitment or delivery.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TransactionStagingWitness {
    pub activation_serial: u64,
    pub command_id: String,
    pub attempt_id: String,
    pub transaction_id: String,
    pub publication_id: String,
    pub staged_mutations: u32,
    pub captured_intents: u32,
    pub state_write_bytes: u64,
    pub observed_at_unix_millis: u64,
}

pub(super) struct BoundStaging {
    identity: Arc<TransactionStagingIdentity>,
    observed: Option<(TransactionStagingProgress, u64)>,
}
impl BoundStaging {
    pub(super) fn witness(&self, serial: u64) -> Option<TransactionStagingWitness> {
        let (progress, observed_at_unix_millis) = self.observed?;
        Some(TransactionStagingWitness {
            activation_serial: serial,
            command_id: self.identity.command_id.clone(),
            attempt_id: self.identity.attempt_id.clone(),
            transaction_id: self.identity.transaction_id.clone(),
            publication_id: self.identity.publication_id.clone(),
            staged_mutations: progress.staged_mutations,
            captured_intents: progress.captured_intents,
            state_write_bytes: progress.state_write_bytes,
            observed_at_unix_millis,
        })
    }
}

pub(super) fn bind(
    journal: &LocalActivationJournal,
    id: &ActivationId,
    serial: u64,
    identity: TransactionStagingIdentity,
) -> Result<Arc<dyn TransactionStagingObserver>, PlatformError> {
    let hex = |value: &str| {
        value.len() == 64
            && value
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    };
    if id.0.len() > 512
        || !hex(&identity.command_id)
        || !hex(&identity.attempt_id)
        || !hex(&identity.transaction_id)
        || !identity
            .publication_id
            .strip_prefix("publication:sha256:")
            .is_some_and(hex)
    {
        return Err(error(
            PlatformErrorCode::InvalidArgument,
            "invalid-transaction-staging-identity",
        ));
    }
    let mut state = journal.inner.lock();
    let record = state.records.get_mut(id).ok_or_else(|| {
        error(
            PlatformErrorCode::PermissionDenied,
            "transaction-staging-owner-unavailable",
        )
    })?;
    if record.serial != serial
        || record.staging.is_some()
        || record.status.terminal_state.is_some()
        || record.granted_budget.is_none()
        || !matches!(
            record.status.phase,
            ActivationPhase::Admitted | ActivationPhase::Queued
        )
    {
        return Err(error(
            PlatformErrorCode::PermissionDenied,
            "transaction-staging-owner-mismatch",
        ));
    }
    let bytes = record
        .bytes
        .checked_add(RECORD_BYTES)
        .ok_or_else(super::capacity)?;
    if bytes > journal.inner.config.maximum_record_bytes - TERMINAL_RESERVE_BYTES {
        return Err(super::capacity());
    }
    let identity = Arc::new(identity);
    record.staging = Some(BoundStaging {
        identity: Arc::clone(&identity),
        observed: None,
    });
    record.bytes = bytes;
    Ok(Arc::new(Observer {
        journal: Arc::downgrade(&journal.inner),
        id: id.clone(),
        serial,
        identity,
    }))
}

struct Observer {
    journal: Weak<Inner>,
    id: ActivationId,
    serial: u64,
    identity: Arc<TransactionStagingIdentity>,
}
impl TransactionStagingObserver for Observer {
    fn observe(&self, progress: TransactionStagingProgress) {
        let Some(journal) = self.journal.upgrade() else {
            return;
        };
        let sample = journal.clock.sample();
        let mut state = journal.lock();
        let Some(record) = state.records.get_mut(&self.id) else {
            return;
        };
        let (Some(bound), Some(grant)) = (&mut record.staging, &record.granted_budget) else {
            return;
        };
        if record.serial != self.serial
            || !Arc::ptr_eq(&bound.identity, &self.identity)
            || record.status.terminal_state.is_some()
            || !matches!(
                record.status.phase,
                ActivationPhase::Materializing | ActivationPhase::Running
            )
            || progress.staged_mutations > 128
            || progress.captured_intents == 0
            || progress.captured_intents > grant.effect_count.min(128)
            || progress.state_write_bytes == 0
            || progress.state_write_bytes > grant.state_write_bytes
        {
            return;
        }
        let previous = bound.observed.map_or(
            TransactionStagingProgress {
                staged_mutations: 0,
                captured_intents: 0,
                state_write_bytes: 0,
            },
            |(value, _)| value,
        );
        if progress.captured_intents != previous.captured_intents + 1
            || progress.staged_mutations < previous.staged_mutations
            || progress.state_write_bytes < previous.state_write_bytes
        {
            return;
        }
        bound.observed = Some((
            progress,
            sample
                .unix_millis()
                .max(record.status.last_updated_unix_millis),
        ));
    }
}

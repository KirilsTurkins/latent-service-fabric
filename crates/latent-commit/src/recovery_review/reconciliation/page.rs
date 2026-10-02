//! Original metadata pages on the SAME retained native view. No cursor is a
//! cross-RPC access token, retry qualification or accepted provider request.

use super::{checkpoint, source, RecoveryReviewError, RestoreReconciliationPlan};
use latent_effects::{
    authority::DurableEffectAuthority,
    dispatch::{
        effect_record_version, AttemptIdentity, Disposition, EffectManagementFact, EffectRecord,
    },
    dispatch_store::{DispatchCatalog, DispatchStoreError, EFFECT_PREFIX},
};
use latent_state::embedded::{Family, ReadView, StoreError};
use serde::Serialize;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum RestoreEffectFact {
    UnknownSinceSnapshot,
    ProviderAcknowledged,
    ProviderConfirmed,
    AdministratorTerminated,
    Expired,
    OriginalDeadLetter,
}
impl RestoreEffectFact {
    pub(super) fn capture(record: &EffectRecord) -> Self {
        match record.disposition() {
            Disposition::ProviderAcknowledged => {
                if record
                    .management()
                    .is_some_and(|stamp| stamp.fact() == EffectManagementFact::ProviderConfirmed)
                {
                    Self::ProviderConfirmed
                } else {
                    Self::ProviderAcknowledged
                }
            }
            Disposition::Expired => Self::Expired,
            Disposition::DeadLettered => {
                if record.management().is_some_and(|stamp| {
                    stamp.fact() == EffectManagementFact::AdministratorTerminated
                }) {
                    Self::AdministratorTerminated
                } else {
                    Self::OriginalDeadLetter
                }
            }
            _ => Self::UnknownSinceSnapshot,
        }
    }
}

/// Every association is decoded from the original closed effect/history owner.
/// Payload digest/size are descriptions; payload bytes and credentials stay
/// private. Missing history never manufactures an AttemptIdentity or proof.
#[derive(Serialize)]
pub struct RestoreEffectReview {
    authority: DurableEffectAuthority,
    disposition: Disposition,
    fact: RestoreEffectFact,
    original_attempt: Option<AttemptIdentity>,
    owner_epoch: u64,
    claim_generation: u64,
    attempts: u32,
    row_version: [u8; 32],
}
impl RestoreEffectReview {
    fn capture(view: &ReadView, bytes: &[u8]) -> Result<Self, RecoveryReviewError> {
        let record = EffectRecord::decode(bytes)
            .map_err(|_| RecoveryReviewError::Source(StoreError::Corrupt))?;
        let authority = record
            .authority()
            .map_err(|_| RecoveryReviewError::Source(StoreError::Corrupt))?;
        let original_attempt = if record.disposition() == Disposition::Dispatching {
            None
        } else {
            DispatchCatalog::last_completed_attempt(view, &authority.link().effect).map_err(
                |error| match error {
                    DispatchStoreError::Storage(error) => source(error),
                    _ => RecoveryReviewError::Source(StoreError::Corrupt),
                },
            )?
        };
        Ok(Self {
            authority,
            disposition: record.disposition(),
            fact: RestoreEffectFact::capture(&record),
            original_attempt,
            owner_epoch: record.owner_epoch(),
            claim_generation: record.claim_generation(),
            attempts: record.attempts(),
            row_version: effect_record_version(bytes)
                .map_err(|_| RecoveryReviewError::Source(StoreError::Corrupt))?,
        })
    }

    #[must_use]
    pub fn authority(&self) -> &DurableEffectAuthority {
        &self.authority
    }
    #[must_use]
    pub const fn disposition(&self) -> Disposition {
        self.disposition
    }
    #[must_use]
    pub const fn fact(&self) -> RestoreEffectFact {
        self.fact
    }
    #[must_use]
    pub fn original_attempt(&self) -> Option<&AttemptIdentity> {
        self.original_attempt.as_ref()
    }
    #[must_use]
    pub const fn row_version(&self) -> [u8; 32] {
        self.row_version
    }
}

#[derive(Serialize)]
pub struct ReconciliationCursor {
    #[serde(skip)]
    view_identity: usize,
    plan_digest: [u8; 32],
    exclusive_after: Vec<u8>,
}
#[derive(Serialize)]
pub struct RestoreEffectPage {
    rows: Vec<RestoreEffectReview>,
    resume: Option<ReconciliationCursor>,
}
impl RestoreEffectPage {
    #[must_use]
    pub fn rows(&self) -> &[RestoreEffectReview] {
        &self.rows
    }
    #[must_use]
    pub fn into_parts(self) -> (Vec<RestoreEffectReview>, Option<ReconciliationCursor>) {
        (self.rows, self.resume)
    }
}

impl RestoreReconciliationPlan {
    /// One bounded page, preserving native `resume` rather than assuming a
    /// short page is complete. Retain the original request deadline/native view
    /// and current whole-unit read/audit owner through encoding and reply drop.
    pub fn effect_page(
        &self,
        view: &ReadView,
        cursor: Option<ReconciliationCursor>,
        maximum_rows: usize,
        maximum_bytes: usize,
        mut current: impl FnMut() -> Result<(), StoreError>,
    ) -> Result<RestoreEffectPage, RecoveryReviewError> {
        if maximum_rows == 0
            || maximum_rows > 128
            || maximum_bytes == 0
            || maximum_bytes > 1024 * 1024
        {
            return Err(RecoveryReviewError::Review(StoreError::Invalid));
        }
        checkpoint(self.deadline, &mut current)?;
        self.require_view(view)?;
        let plan_digest = self.digest()?;
        if cursor.as_ref().is_some_and(|cursor| {
            cursor.view_identity != self.view_identity
                || cursor.plan_digest != plan_digest
                || cursor.exclusive_after.len() != EFFECT_PREFIX.len() + 32
                || !cursor.exclusive_after.starts_with(EFFECT_PREFIX)
        }) {
            return Err(RecoveryReviewError::Review(StoreError::Conflict));
        }
        let page = view
            .scan_after(
                Family::Outbox,
                EFFECT_PREFIX,
                cursor
                    .as_ref()
                    .map(|cursor| cursor.exclusive_after.as_slice()),
                maximum_rows,
                maximum_bytes,
            )
            .map_err(source)?;
        let mut rows = Vec::with_capacity(page.rows.len());
        for (_, bytes) in page.rows {
            checkpoint(self.deadline, &mut current)?;
            rows.push(RestoreEffectReview::capture(view, &bytes)?);
        }
        let result = RestoreEffectPage {
            rows,
            resume: page.resume.map(|exclusive_after| ReconciliationCursor {
                view_identity: self.view_identity,
                plan_digest,
                exclusive_after,
            }),
        };
        let encoded = serde_json::to_vec(&result)
            .map_err(|_| RecoveryReviewError::Review(StoreError::Invalid))?;
        if encoded.len() > maximum_bytes {
            return Err(RecoveryReviewError::Capacity);
        }
        checkpoint(self.deadline, &mut current)?;
        Ok(result)
    }
}

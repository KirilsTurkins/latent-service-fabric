//! The original decoded owners determine each retained association. Inventory
//! counts are per format and conservatively overlap when a row needs several
//! independent decoders; they never replace the physical-row tenant census.

use super::{
    artifacts::Artifacts, atomic_error, source, RecoveryReviewError, RecoveryReviewOwners,
};
use crate::atomic::{self, CommandRecord, DurableResult, Outcome};
use latent_effects::{
    dispatch::{Disposition, EffectManagementFact, EffectRecord},
    dispatch_store,
    payload::PayloadRecord,
};
use latent_state::{
    embedded::{Family, ReadView, RowKey, StoreError},
    namespace::{
        compatibility::{RetainedCount, RetainedFormat, RetainedInventory, RetainedKind},
        history::NamespaceHistory,
        NamespaceRecord, NamespaceStatus,
    },
    recovery::snapshot::SnapshotClosure,
};

#[derive(Default)]
pub(super) struct Inventory {
    formats: RetainedInventory,
    artifacts: Artifacts,
}
impl Inventory {
    pub(super) fn formats(&self) -> &RetainedInventory {
        &self.formats
    }
    pub(super) fn finish(self) -> SnapshotClosure {
        SnapshotClosure {
            inventory: self.formats,
            required_artifacts: self.artifacts.finish(),
        }
    }
    pub(super) fn observe(
        &mut self,
        view: &ReadView,
        key: &RowKey,
        bytes: &[u8],
        owners: &mut impl RecoveryReviewOwners,
    ) -> Result<(), RecoveryReviewError> {
        // This is the real physical charge. Caller-provided row counts or byte
        // labels cannot hide required payloads or truncate the inventory.
        let charge = latent_state::tenant::row_charge(key, bytes).map_err(source)?;
        match key.family {
            Family::Namespace if key.key.starts_with(b"ns-v1\0") => {
                let namespace = NamespaceRecord::decode(bytes)
                    .map_err(|_| RecoveryReviewError::Source(StoreError::Corrupt))?;
                if namespace.status == NamespaceStatus::Active {
                    return Err(RecoveryReviewError::Review(StoreError::Conflict));
                }
                NamespaceHistory::capture(view, &namespace).map_err(source)?;
                self.artifacts.digest(&namespace.state_schema)?;
            }
            Family::Command | Family::Attempt => self.command_row(key, bytes, charge, owners)?,
            Family::Result => self.result_row(key, bytes, charge)?,
            Family::Inbox => {
                let (identity, version) =
                    atomic::durable_row_format(key, bytes).map_err(atomic_error)?;
                self.format(
                    RetainedKind::InboxIdentity,
                    &format!("{identity}/{version}"),
                    charge,
                    false,
                )?;
            }
            Family::Outbox => self.effect(
                &EffectRecord::decode(bytes).map_err(effect_error)?,
                charge,
                owners,
            )?,
            Family::PayloadReference => {
                let payload = PayloadRecord::decode(bytes).map_err(effect_error)?;
                let (identity, version) = payload.durable_format();
                self.format(
                    RetainedKind::EffectPayload,
                    &format!("{identity}/{version}"),
                    charge,
                    false,
                )?;
            }
            // All other host rows have already passed their original closed
            // codec/link/tenant owner, including guards, quotas and management
            // reservations. Unsupported new producer formats refuse upstream.
            _ => {}
        }
        Ok(())
    }

    fn command_row(
        &mut self,
        key: &RowKey,
        bytes: &[u8],
        charge: u64,
        owners: &mut impl RecoveryReviewOwners,
    ) -> Result<(), RecoveryReviewError> {
        match atomic::durable_row_format(key, bytes) {
            Ok((identity, version)) => {
                let kind = if key.family == Family::Command {
                    RetainedKind::CommandFingerprint
                } else {
                    RetainedKind::CommandAttempt
                };
                if identity == "latent.command-retired.v1" {
                    return self.format(kind, &format!("{identity}/{version}"), charge, false);
                }
                let record = CommandRecord::decode(bytes).map_err(atomic_error)?;
                self.format(
                    kind,
                    &format!("{identity}/{version}"),
                    charge,
                    record.outcome() == Outcome::Pending,
                )?;
                self.command(&record, charge, owners)
            }
            Err(atomic::AtomicError::UnsupportedFormat) if key.family == Family::Attempt => {
                let (identity, version) =
                    dispatch_store::durable_row_format(key, bytes).map_err(source)?;
                self.format(
                    RetainedKind::CommandAttempt,
                    &format!("{identity}/{version}"),
                    charge,
                    identity == "latent.effect-attempt-pending.v1",
                )
            }
            Err(error) => Err(atomic_error(error)),
        }
    }

    fn result_row(
        &mut self,
        key: &RowKey,
        bytes: &[u8],
        charge: u64,
    ) -> Result<(), RecoveryReviewError> {
        let (identity, version) = atomic::durable_row_format(key, bytes).map_err(atomic_error)?;
        let kind = if identity == "latent.result.v1" {
            match DurableResult::decode(bytes)
                .map_err(atomic_error)?
                .outcome()
            {
                Outcome::Committed => RetainedKind::SuccessResult,
                Outcome::Rejected => RetainedKind::RejectionResult,
                Outcome::Aborted => RetainedKind::CommandAttempt,
                Outcome::Pending => return Err(RecoveryReviewError::Source(StoreError::Corrupt)),
            }
        } else if identity == "latent.result-expired.v1" {
            RetainedKind::CommandFingerprint
        } else {
            RetainedKind::CommandAttempt
        };
        self.format(
            kind,
            &format!("{identity}/{version}"),
            charge,
            identity == "latent.result-pending.v1",
        )
    }

    fn command(
        &mut self,
        record: &CommandRecord,
        charge: u64,
        owners: &mut impl RecoveryReviewOwners,
    ) -> Result<(), RecoveryReviewError> {
        let original = record.source();
        let digest = owners
            .publication(original)
            .map_err(RecoveryReviewError::Review)?;
        self.artifacts.source(original, digest)?;
        let pending = record.outcome() == Outcome::Pending;
        self.format(
            RetainedKind::CommandFingerprint,
            &original.input_format,
            charge,
            pending,
        )?;
        let result_kind = match record.outcome() {
            Outcome::Committed => RetainedKind::SuccessResult,
            Outcome::Rejected => RetainedKind::RejectionResult,
            Outcome::Aborted => RetainedKind::CommandAttempt,
            Outcome::Pending => {
                // Either terminal business outcome is still possible. Their
                // original declared output decoder must remain independently installed.
                self.format(
                    RetainedKind::RejectionResult,
                    &original.result_format,
                    charge,
                    true,
                )?;
                RetainedKind::SuccessResult
            }
        };
        self.format(result_kind, &original.result_format, charge, pending)?;
        if let Some(inbox) = record.inbox_identity() {
            let identity = super::original_inbox_profile_identity(record.key(), original, inbox)
                .map_err(source)?;
            let digest = owners
                .inbox_profile(record.key(), original, inbox)
                .map_err(RecoveryReviewError::Review)?;
            self.artifacts.observe(&identity, digest)?;
            self.format(RetainedKind::InboxIdentity, &identity, charge, pending)?;
        }
        Ok(())
    }
    fn effect(
        &mut self,
        record: &EffectRecord,
        charge: u64,
        owners: &mut impl RecoveryReviewOwners,
    ) -> Result<(), RecoveryReviewError> {
        let authority = record.authority().map_err(effect_error)?;
        let profile = authority.profile();
        let artifacts = owners
            .dispatch_profile(authority.scope(), profile)
            .map_err(RecoveryReviewError::Review)?;
        self.artifacts.profile(profile, artifacts)?;
        let unresolved = !record.disposition().terminal()
            || (record.management().is_some_and(|stamp| {
                stamp.fact() == EffectManagementFact::AdministratorTerminated
            }) && record
                .latest()
                .is_some_and(|receipt| receipt.disposition == Disposition::Uncertain));
        let (identity, version) = record.durable_format();
        self.format(
            RetainedKind::EffectEnvelope,
            &format!("{identity}/{version}"),
            charge,
            unresolved,
        )?;
        self.format(
            RetainedKind::EffectEnvelope,
            &format!("latent.intent.v{}", profile.intent_format),
            charge,
            unresolved,
        )?;
        self.format(
            RetainedKind::EffectPayload,
            &profile.payload_format,
            charge,
            unresolved,
        )?;
        self.format(
            RetainedKind::AdapterProfile,
            &profile.adapter,
            charge,
            unresolved,
        )?;
        self.format(
            RetainedKind::AdapterProfile,
            &profile.idempotency_profile,
            charge,
            unresolved,
        )
    }
    fn format(
        &mut self,
        kind: RetainedKind,
        identity: &str,
        charge: u64,
        unresolved: bool,
    ) -> Result<(), RecoveryReviewError> {
        super::artifacts::bounded(identity).map_err(RecoveryReviewError::Review)?;
        self.formats
            .observe(
                RetainedFormat {
                    kind,
                    identity: identity.to_owned(),
                },
                RetainedCount {
                    rows: 1,
                    bytes: charge,
                    unresolved: u64::from(unresolved),
                },
            )
            .map_err(|error| match error {
                latent_state::namespace::NamespaceError::Capacity => RecoveryReviewError::Capacity,
                _ => RecoveryReviewError::Review(StoreError::Invalid),
            })
    }
}

fn effect_error(error: latent_effects::authority::AuthorityError) -> RecoveryReviewError {
    source(match error {
        latent_effects::authority::AuthorityError::Capacity => StoreError::Capacity,
        latent_effects::authority::AuthorityError::UnsupportedFormat => {
            StoreError::UnsupportedFormat
        }
        _ => StoreError::Corrupt,
    })
}

use latent_state::embedded::{
    AtomicBatch, EmbeddedStore, ExpectedRow, Family, ReadView, RowMutation, StoreError,
};

use crate::authority::{AuthorityError, DurableEffectAuthority, EffectTime};
use crate::dispatch::{AttemptIdentity, AttemptReceipt, Disposition, EffectRecord, RetryProof};
use crate::payload::PayloadRecord;

use super::codec::{
    DispatchStoreError, HistoryRecord, HistoryReservation, OwnerRecord, HISTORY_PREFIX,
};
use super::{
    effect_payload_key, effect_row_key, storage_error, DueRecord, DUE_PREFIX, EFFECT_PREFIX,
};

#[cfg(test)]
mod tests;
mod validation;
mod write;

/// Captured process fence, distinct from business namespace incarnation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DispatchEpoch(u64);

impl DispatchEpoch {
    #[must_use]
    pub const fn generation(self) -> u64 {
        self.0
    }
}

#[derive(Debug)]
pub struct ClaimedEffect {
    pub authority: DurableEffectAuthority,
    pub attempt: AttemptIdentity,
    pub payload: PayloadRecord,
}

#[derive(Debug, Default)]
pub struct DuePage {
    pub rows: Vec<DueRecord>,
    pub resume: Option<Vec<u8>>,
    pub next_due_millis: Option<u64>,
}

#[derive(Debug)]
pub struct HistoryPage {
    pub rows: Vec<HistoryRecord>,
    pub pending_slots: usize,
    pub resume: Option<Vec<u8>>,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct DispatchCounts {
    pub pending: u64,
    pub active: u64,
    pub acknowledged: u64,
    pub known_failed: u64,
    pub uncertain: u64,
    pub retry_scheduled: u64,
    pub blocked: u64,
    pub expired: u64,
    pub dead_lettered: u64,
    pub payload_bytes: u64,
    pub oldest_unresolved_millis: Option<u64>,
}

/// Logical borrowed-store ports. The protected node owner executes them on its
/// fixed workers; this catalog retains neither an engine nor native snapshot.
pub struct DispatchCatalog;

impl DispatchCatalog {
    /// Only the fresh exclusive node startup owner may advance this fence.
    /// The protected root must prove the previous process physically retired.
    /// An admitted external restore checkpoint rejects epoch/clock rollback;
    /// ordinary wall time never manufactures continuity or restore approval.
    pub fn begin_exclusive_epoch(
        store: &EmbeddedStore,
        time: EffectTime,
        minimum_checkpoint: Option<(u64, u64)>,
    ) -> Result<DispatchEpoch, DispatchStoreError> {
        let view = store.snapshot()?;
        let key = OwnerRecord::key();
        let previous = view.get(&key)?;
        let old = previous.as_deref().map(OwnerRecord::decode).transpose()?;
        if let Some((minimum_epoch, minimum_clock)) = minimum_checkpoint {
            if old.is_none_or(|old| old.epoch < minimum_epoch || old.clock_floor < minimum_clock) {
                return Err(DispatchStoreError::StaleEpoch);
            }
        }
        let epoch = old.map_or(Ok(1), |old| {
            old.epoch.checked_add(1).ok_or(StoreError::Capacity)
        })?;
        let mut owner = OwnerRecord {
            epoch,
            clock_floor: old.map_or(0, |old| old.clock_floor),
        };
        owner.observe(time)?;
        drop(view);
        store.apply(AtomicBatch {
            expectations: vec![ExpectedRow {
                key: key.clone(),
                value: previous,
            }],
            mutations: vec![RowMutation {
                key,
                value: Some(owner.encode()?),
            }],
        })?;
        Ok(DispatchEpoch(epoch))
    }

    pub fn due_page(
        view: &ReadView,
        now_millis: u64,
        exclusive_after: Option<&[u8]>,
        maximum_rows: usize,
        maximum_bytes: usize,
    ) -> Result<DuePage, StoreError> {
        let page = view.scan_after(
            Family::Maintenance,
            DUE_PREFIX,
            exclusive_after,
            maximum_rows,
            maximum_bytes,
        )?;
        let mut rows = Vec::with_capacity(page.rows.len());
        let mut next_due_millis = None;
        for (key, bytes) in page.rows {
            let row = DueRecord::decode(&key, &bytes)?;
            if row.due_millis > now_millis {
                next_due_millis = Some(row.due_millis);
                break;
            }
            rows.push(row);
        }
        Ok(DuePage {
            rows,
            resume: if next_due_millis.is_some() {
                None
            } else {
                page.resume
            },
            next_due_millis,
        })
    }

    /// Provider queue/byte and authority physical reservations precede this
    /// call. No send is allowed until this CAS and `begin_send` both succeed.
    pub fn claim(
        store: &EmbeddedStore,
        epoch: DispatchEpoch,
        due: &DueRecord,
        time: EffectTime,
    ) -> Result<ClaimedEffect, DispatchStoreError> {
        let view = store.snapshot()?;
        let mut writer = write::WriteSet::new(&view, epoch, time)?;
        let mut loaded = write::Loaded::read(&view, &due.effect)?;
        writer.expect_due(&view, due, &loaded)?;
        let payload_key = effect_payload_key(&due.effect)?;
        let payload_bytes = view.get(&payload_key)?.ok_or(StoreError::Corrupt)?;
        let payload = PayloadRecord::decode(&payload_bytes).map_err(storage_error)?;
        let authority = loaded.record.authority().map_err(storage_error)?;
        payload.verify(&authority).map_err(storage_error)?;
        let attempt = match loaded.record.claim(epoch.0, time) {
            Ok(attempt) => attempt,
            Err(error) => {
                // Persist actual negative dispositions, but never delete due
                // work merely because a technical counter exhausted.
                if matches!(
                    loaded.record.disposition(),
                    Disposition::Expired | Disposition::DeadLettered | Disposition::PolicyBlocked
                ) {
                    writer.replace(loaded)?;
                    drop(view);
                    writer.apply(store)?;
                }
                return Err(error.into());
            }
        };
        writer.expect(payload_key, Some(payload_bytes));
        writer.reserve_attempt(&loaded.record)?;
        writer.replace(loaded)?;
        drop(view);
        writer.apply(store)?;
        Ok(ClaimedEffect {
            authority,
            attempt,
            payload,
        })
    }

    pub fn begin_send(
        store: &EmbeddedStore,
        epoch: DispatchEpoch,
        claim: &AttemptIdentity,
        time: EffectTime,
    ) -> Result<(), DispatchStoreError> {
        let view = store.snapshot()?;
        let mut writer = write::WriteSet::new(&view, epoch, time)?;
        let mut loaded = write::Loaded::read(&view, claim.effect())?;
        loaded.record.check_claim(claim)?;
        writer.verify_attempt(&view, &loaded.record)?;
        loaded.record.begin_send(claim)?;
        writer.replace(loaded)?;
        drop(view);
        writer.apply(store)
    }

    pub fn complete(
        store: &EmbeddedStore,
        epoch: DispatchEpoch,
        claim: &AttemptIdentity,
        receipt: AttemptReceipt,
        retry: Option<(RetryProof, u64)>,
        time: EffectTime,
    ) -> Result<Disposition, DispatchStoreError> {
        if receipt.observed_at_millis > time.unix_millis {
            return Err(AuthorityError::Invalid.into());
        }
        let view = store.snapshot()?;
        let mut writer = write::WriteSet::new(&view, epoch, time)?;
        let mut loaded = write::Loaded::read(&view, claim.effect())?;
        loaded.record.check_claim(claim)?;
        let slot = writer.release_attempt(&view, &loaded.record)?;
        loaded.record.complete(claim, receipt)?;
        writer.history(&loaded.record, Some(claim.clone()), slot)?;
        if let Some((proof, delay)) = retry {
            // Failure of a claimed retry proof preserves the actual receipt.
            // It never converts uncertain provider acceptance to known failure.
            if loaded.record.schedule_retry(proof, time, delay).is_ok() {
                writer.schedule(&loaded.record)?;
            }
        }
        let disposition = loaded.record.disposition();
        writer.replace(loaded)?;
        drop(view);
        writer.apply(store)?;
        Ok(disposition)
    }

    pub fn block_eligible(
        store: &EmbeddedStore,
        epoch: DispatchEpoch,
        due: &DueRecord,
        time: EffectTime,
    ) -> Result<(), DispatchStoreError> {
        let view = store.snapshot()?;
        let mut writer = write::WriteSet::new(&view, epoch, time)?;
        let mut loaded = write::Loaded::read(&view, &due.effect)?;
        writer.expect_due(&view, due, &loaded)?;
        loaded.record.block_eligible(time)?;
        writer.replace(loaded)?;
        drop(view);
        writer.apply(store)
    }

    /// One page only. Startup owns the cursor and calls until `None`, retaining
    /// no backlog vector. `old_process_retired` is affirmative exclusive-root
    /// recovery evidence; a local lease/deadline cannot substitute for it.
    pub fn recover_page(
        store: &EmbeddedStore,
        epoch: DispatchEpoch,
        exclusive_after: Option<&[u8]>,
        old_process_retired: bool,
        time: EffectTime,
    ) -> Result<Option<Vec<u8>>, DispatchStoreError> {
        let view = store.snapshot()?;
        let page = view.scan_after(
            Family::Outbox,
            EFFECT_PREFIX,
            exclusive_after,
            16,
            1024 * 1024,
        )?;
        drop(view);
        for (key, bytes) in page.rows {
            super::validate_row(&key, &bytes)?;
            write::recover_one(store, epoch, &key, old_process_retired, time)?;
        }
        Ok(page.resume)
    }

    pub fn history_page(
        view: &ReadView,
        effect: &str,
        exclusive_after: Option<&[u8]>,
        maximum_rows: usize,
        maximum_bytes: usize,
    ) -> Result<HistoryPage, StoreError> {
        if maximum_rows > 128 || maximum_bytes > 1024 * 1024 {
            return Err(StoreError::Invalid);
        }
        let mut prefix = HISTORY_PREFIX.to_vec();
        prefix.extend_from_slice(
            &super::effect_identity::parse(effect).map_err(|_| StoreError::Invalid)?,
        );
        let page = view.scan_after(
            Family::Attempt,
            &prefix,
            exclusive_after,
            maximum_rows,
            maximum_bytes,
        )?;
        let mut rows = Vec::with_capacity(page.rows.len());
        let mut pending_slots = 0;
        for (key, bytes) in page.rows {
            if HistoryReservation::present(&bytes) {
                super::validate_row(&key, &bytes)?;
                pending_slots += 1;
            } else {
                rows.push(HistoryRecord::decode(&key, &bytes)?);
            }
        }
        Ok(HistoryPage {
            rows,
            pending_slots,
            resume: page.resume,
        })
    }

    /// Scalar accumulation over finite pages; no full backlog in RAM. Execute
    /// on the storage workers with bounded decode/page scratch reservation.
    pub fn counts(view: &ReadView) -> Result<DispatchCounts, StoreError> {
        let mut counts = DispatchCounts::default();
        let mut cursor = None;
        loop {
            let page = view.scan_after(
                Family::Outbox,
                EFFECT_PREFIX,
                cursor.as_deref(),
                16,
                1024 * 1024,
            )?;
            for (key, bytes) in page.rows {
                super::validate_row(&key, &bytes)?;
                let record = EffectRecord::decode(&bytes).map_err(storage_error)?;
                counts.observe(&record)?;
            }
            cursor = page.resume;
            if cursor.is_none() {
                return Ok(counts);
            }
        }
    }
}

impl DispatchCounts {
    fn observe(&mut self, record: &EffectRecord) -> Result<(), StoreError> {
        let count = match record.disposition() {
            Disposition::Pending => &mut self.pending,
            Disposition::Dispatching => &mut self.active,
            Disposition::ProviderAcknowledged => &mut self.acknowledged,
            Disposition::KnownFailed => &mut self.known_failed,
            Disposition::Uncertain => &mut self.uncertain,
            Disposition::RetryScheduled => &mut self.retry_scheduled,
            Disposition::PolicyBlocked => &mut self.blocked,
            Disposition::Expired => &mut self.expired,
            Disposition::DeadLettered => &mut self.dead_lettered,
        };
        *count = count.checked_add(1).ok_or(StoreError::Capacity)?;
        if !record.disposition().terminal() {
            let authority = record.authority().map_err(storage_error)?;
            self.payload_bytes = self
                .payload_bytes
                .checked_add(authority.payload_bytes())
                .ok_or(StoreError::Capacity)?;
            self.oldest_unresolved_millis = Some(
                self.oldest_unresolved_millis
                    .map_or(authority.committed_at_millis(), |oldest| {
                        oldest.min(authority.committed_at_millis())
                    }),
            );
        }
        Ok(())
    }
}

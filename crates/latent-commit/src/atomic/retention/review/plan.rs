use crate::atomic::{AtomicError, MaintenanceClock, MaintenanceProgress, ResultMaintenanceOwner};
use latent_state::embedded::{AtomicBatch, ExpectedRow, ReadView, RowKey, RowMutation};

/// One finite physical callback. It never retains a native view or increments
/// a bound to accommodate a large closure. Exact duplicates must agree.
#[derive(Default)]
pub(super) struct Plan {
    pub batch: AtomicBatch,
    bytes: usize,
}
impl Plan {
    pub fn expect(&mut self, row: ExpectedRow) -> Result<(), AtomicError> {
        if let Some(old) = self
            .batch
            .expectations
            .iter()
            .find(|old| old.key == row.key)
        {
            return if old.value == row.value {
                Ok(())
            } else {
                Err(AtomicError::Corrupt)
            };
        }
        self.charge(&row.key, row.value.as_deref())?;
        if self.batch.expectations.len() >= 512 {
            return Err(AtomicError::Limit);
        }
        self.batch.expectations.push(row);
        Ok(())
    }
    pub fn mutation(&mut self, key: RowKey, value: Option<Vec<u8>>) -> Result<(), AtomicError> {
        if self.batch.mutations.iter().any(|old| old.key == key) {
            return Err(AtomicError::Corrupt);
        }
        self.charge(&key, value.as_deref())?;
        if self.batch.mutations.len() >= 512 {
            return Err(AtomicError::Limit);
        }
        self.batch.mutations.push(RowMutation { key, value });
        Ok(())
    }
    pub fn replace(
        &mut self,
        key: RowKey,
        old: Option<Vec<u8>>,
        new: Option<Vec<u8>>,
    ) -> Result<(), AtomicError> {
        self.expect(ExpectedRow {
            key: key.clone(),
            value: old,
        })?;
        self.mutation(key, new)
    }
    pub fn append(&mut self, batch: AtomicBatch) -> Result<(), AtomicError> {
        if batch.expectations.len() > 512 || batch.mutations.len() > 512 {
            return Err(AtomicError::Limit);
        }
        let mut bytes = self.bytes;
        let mut expectations = self.batch.expectations.len();
        for (index, row) in batch.expectations.iter().enumerate() {
            if batch.expectations[..index]
                .iter()
                .any(|old| old.key == row.key)
            {
                return Err(AtomicError::Corrupt);
            }
            if let Some(old) = self
                .batch
                .expectations
                .iter()
                .find(|old| old.key == row.key)
            {
                if old.value != row.value {
                    return Err(AtomicError::Corrupt);
                }
            } else {
                expectations += 1;
                bytes = append_charge(bytes, &row.key, row.value.as_deref())?;
            }
        }
        for (index, row) in batch.mutations.iter().enumerate() {
            if self.batch.mutations.iter().any(|old| old.key == row.key)
                || batch.mutations[..index]
                    .iter()
                    .any(|old| old.key == row.key)
            {
                return Err(AtomicError::Corrupt);
            }
            bytes = append_charge(bytes, &row.key, row.value.as_deref())?;
        }
        if expectations > 512 || self.batch.mutations.len() + batch.mutations.len() > 512 {
            return Err(AtomicError::Limit);
        }
        // Validation above has no mutation or large clone. Once it succeeds,
        // moving the already bounded rows cannot leave a partial composed plan.
        for row in batch.expectations {
            if !self.batch.expectations.iter().any(|old| old.key == row.key) {
                self.batch.expectations.push(row);
            }
        }
        self.batch.mutations.extend(batch.mutations);
        self.bytes = bytes;
        Ok(())
    }
    fn charge(&mut self, key: &RowKey, value: Option<&[u8]>) -> Result<(), AtomicError> {
        self.bytes = self
            .bytes
            .checked_add(key.key.len() + value.map_or(0, <[u8]>::len))
            .ok_or(AtomicError::Limit)?;
        if u64::try_from(self.bytes).map_err(|_| AtomicError::Limit)?
            > ResultMaintenanceOwner::RETAINED_BYTES / 2
        {
            return Err(AtomicError::Limit);
        }
        Ok(())
    }
}

fn append_charge(bytes: usize, key: &RowKey, value: Option<&[u8]>) -> Result<usize, AtomicError> {
    let next = bytes
        .checked_add(key.key.len() + value.map_or(0, <[u8]>::len))
        .ok_or(AtomicError::Limit)?;
    if u64::try_from(next).map_err(|_| AtomicError::Limit)?
        > ResultMaintenanceOwner::RETAINED_BYTES / 2
    {
        return Err(AtomicError::Limit);
    }
    Ok(next)
}

pub(super) fn progress(
    view: &ReadView,
    key: &latent_core::transaction_contract::CommandKey,
    clock: MaintenanceClock,
) -> Result<(MaintenanceProgress, Option<ExpectedRow>), AtomicError> {
    let (usage, _, _) = crate::atomic::writer::Usage::read(view, key)?;
    if !usage.accounted {
        return Err(AtomicError::UnsupportedFormat);
    }
    let (mut progress, fence) = if let Some(progress) = usage.review_clock {
        (progress, None)
    } else {
        // An explicitly installed original global anchor is a valid first
        // observation. Its exact bytes are fenced; subsequent steps consume the
        // namespace's already reserved fixed-size clock slot.
        let key = MaintenanceProgress::key();
        let bytes = view.get(&key)?.ok_or(AtomicError::RecoveryRequired)?;
        (
            MaintenanceProgress::decode(&bytes)?,
            Some(ExpectedRow {
                key,
                value: Some(bytes),
            }),
        )
    };
    progress.cursor = None;
    clock.next(&progress)?;
    Ok((progress, fence))
}
pub(super) fn advance(
    usage: &mut crate::atomic::writer::Usage,
    mut progress: MaintenanceProgress,
    clock: MaintenanceClock,
    reclaimed: u64,
    retired: bool,
) -> Result<MaintenanceProgress, AtomicError> {
    progress.generation = progress
        .generation
        .checked_add(1)
        .ok_or(AtomicError::Limit)?;
    progress.unix_millis = clock.time.unix_millis;
    progress.monotonic_millis = clock.monotonic_millis;
    progress.visited = progress.visited.checked_add(1).ok_or(AtomicError::Limit)?;
    progress.retired = progress
        .retired
        .checked_add(u64::from(retired))
        .ok_or(AtomicError::Limit)?;
    progress.reclaimed_bytes = progress
        .reclaimed_bytes
        .checked_add(reclaimed)
        .ok_or(AtomicError::Limit)?;
    progress.encode()?;
    usage.review_clock = Some(progress.clone());
    Ok(progress)
}

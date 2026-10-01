use super::{codec, guard_key, quota_key, row_charge, TenantRecord, TenantUsage};
use crate::embedded::{AtomicBatch, ExpectedRow, Family, ReadView, RowMutation, StoreError};
use latent_core::TenantId;

/// Absolute old/new category contributions captured by the actual domain
/// owner. Checked removal cannot borrow another tenant's capacity. Domain
/// owners retain their original exact row CAS and promised recovery reserves.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct TenantDelta {
    pub removed: TenantUsage,
    pub added: TenantUsage,
}
impl TenantDelta {
    fn apply(self, current: TenantUsage) -> Result<TenantUsage, StoreError> {
        let mut next = [0; 12];
        for (index, ((current, removed), added)) in current
            .values()
            .into_iter()
            .zip(self.removed.values())
            .zip(self.added.values())
            .enumerate()
        {
            next[index] = current
                .checked_sub(removed)
                .ok_or(StoreError::Corrupt)?
                .checked_add(added)
                .ok_or(StoreError::Capacity)?;
        }
        Ok(TenantUsage::from_values(next))
    }
}

/// A bounded logical plan, without a native view or host authority. Appending
/// multiple domain contributions merges ONE aggregate mutation with one original
/// expected value. Generation advances once per complete physical envelope.
pub struct PreparedTenantUpdate {
    tenant: TenantId,
    captured: Option<codec::Captured>,
    delta: TenantDelta,
}
pub fn prepare_update(
    view: &ReadView,
    tenant: &TenantId,
    delta: TenantDelta,
) -> Result<PreparedTenantUpdate, StoreError> {
    let captured = codec::capture(view, tenant)?;
    if let Some(captured) = &captured {
        let usage = delta.apply(captured.record.usage)?;
        if !usage.within(captured.record.quota.limits) {
            return Err(StoreError::Capacity);
        }
    }
    Ok(PreparedTenantUpdate {
        tenant: tenant.clone(),
        captured,
        delta,
    })
}

/// Charge the original finite namespace/history/schema/operation rows. Every
/// mutation needs its exact old expectation. A management receipt is at most
/// 8192 bytes; an absent-original receipt and a floor decrement therefore share
/// the same aggregate CAS. Caller still proves current permission and scope.
pub fn prepare_metadata_update(
    view: &ReadView,
    tenant: &TenantId,
    batch: &AtomicBatch,
) -> Result<PreparedTenantUpdate, StoreError> {
    prepare_update(view, tenant, metadata_delta(batch)?)
}
fn metadata_delta(batch: &AtomicBatch) -> Result<TenantDelta, StoreError> {
    if batch.mutations.len() > 1024 || batch.expectations.len() > 1024 {
        return Err(StoreError::Capacity);
    }
    let mut delta = TenantDelta::default();
    for (index, row) in batch
        .mutations
        .iter()
        .enumerate()
        .filter(|(_, row)| row.key.family == Family::Namespace)
    {
        if batch.mutations[..index]
            .iter()
            .any(|old| old.key == row.key)
        {
            return Err(StoreError::Corrupt);
        }
        let mut matching = batch.expectations.iter().filter(|old| old.key == row.key);
        let original = matching.next().ok_or(StoreError::Corrupt)?;
        if matching.next().is_some() {
            return Err(StoreError::Corrupt);
        }
        for (value, usage) in [
            (original.value.as_deref(), &mut delta.removed),
            (row.value.as_deref(), &mut delta.added),
        ] {
            if let Some(value) = value {
                if value.len() > 8192 {
                    return Err(StoreError::Capacity);
                }
                usage.metadata_rows = usage
                    .metadata_rows
                    .checked_add(1)
                    .ok_or(StoreError::Capacity)?;
                usage.metadata_bytes = usage
                    .metadata_bytes
                    .checked_add(row_charge(&row.key, value)?)
                    .ok_or(StoreError::Capacity)?;
            }
        }
    }
    Ok(delta)
}

impl PreparedTenantUpdate {
    #[must_use]
    pub fn is_legacy(&self) -> bool {
        self.captured.is_none()
    }
    /// One immutable origin can prepare a later appended management slice.
    /// No new snapshot or guessed counter is used for that composition.
    pub fn metadata_slice(&self, batch: &AtomicBatch) -> Result<Self, StoreError> {
        Ok(Self {
            tenant: self.tenant.clone(),
            captured: self.captured.as_ref().map(|old| codec::Captured {
                guard: old.guard.clone(),
                record: old.record.clone(),
                bytes: old.bytes.clone(),
            }),
            delta: metadata_delta(batch)?,
        })
    }

    /// Validates every candidate before changing the supplied bounded plan.
    /// Legacy appends only the absent guard expectation, preserving original
    /// six-row mutation caps while fencing setup against an older business plan.
    pub fn append_to(&self, batch: &mut AtomicBatch) -> Result<(), StoreError> {
        let guard = ExpectedRow {
            key: guard_key(),
            value: self.captured.as_ref().map(|old| old.guard.clone()),
        };
        check_expectation(batch, &guard)?;
        if batch.mutations.iter().any(|row| row.key == guard.key) {
            return Err(StoreError::Corrupt);
        }
        if let Some(captured) = &self.captured {
            self.append_installed(batch, &guard, captured)
        } else {
            if batch
                .mutations
                .iter()
                .any(|row| row.key.key.starts_with(super::QUOTA_PREFIX) || row.key == guard.key)
            {
                return Err(StoreError::Corrupt);
            }
            check_size(batch, &[&guard], None)?;
            add_expectation(batch, guard);
            Ok(())
        }
    }
    fn append_installed(
        &self,
        batch: &mut AtomicBatch,
        guard: &ExpectedRow,
        captured: &codec::Captured,
    ) -> Result<(), StoreError> {
        let expected = ExpectedRow {
            key: quota_key(&self.tenant)?,
            value: Some(captured.bytes.clone()),
        };
        check_expectation(batch, &expected)?;
        let mut positions = batch
            .mutations
            .iter()
            .enumerate()
            .filter(|(_, row)| row.key == expected.key);
        let position = positions.next().map(|(index, _)| index);
        if positions.next().is_some() {
            return Err(StoreError::Corrupt);
        }
        let mut record = if let Some(index) = position {
            if !batch.expectations.iter().any(|row| row.key == expected.key) {
                return Err(StoreError::Corrupt);
            }
            let record = TenantRecord::decode(
                batch.mutations[index]
                    .value
                    .as_deref()
                    .ok_or(StoreError::Corrupt)?,
            )?;
            if record.quota != captured.record.quota
                || Some(record.generation) != captured.record.generation.checked_add(1)
            {
                return Err(StoreError::Corrupt);
            }
            record
        } else {
            let mut record = captured.record.clone();
            record.generation = record
                .generation
                .checked_add(1)
                .ok_or(StoreError::Capacity)?;
            record
        };
        record.usage = self.delta.apply(record.usage)?;
        if !record.usage.within(record.quota.limits) {
            return Err(StoreError::Capacity);
        }
        let mutation = RowMutation {
            key: expected.key.clone(),
            value: Some(record.encode()?),
        };
        check_size(batch, &[guard, &expected], Some((&mutation, position)))?;
        add_expectation(batch, guard.clone());
        add_expectation(batch, expected);
        if let Some(index) = position {
            batch.mutations[index] = mutation;
        } else {
            batch.mutations.push(mutation);
        }
        Ok(())
    }
}

fn check_expectation(batch: &AtomicBatch, expected: &ExpectedRow) -> Result<(), StoreError> {
    let mut matching = batch
        .expectations
        .iter()
        .filter(|row| row.key == expected.key);
    if let Some(row) = matching.next() {
        if matching.next().is_some() {
            return Err(StoreError::Corrupt);
        }
        if row.value != expected.value {
            return Err(StoreError::Conflict);
        }
    }
    Ok(())
}
fn add_expectation(batch: &mut AtomicBatch, expected: ExpectedRow) {
    if !batch.expectations.iter().any(|row| row.key == expected.key) {
        batch.expectations.push(expected);
    }
}
fn check_size(
    batch: &AtomicBatch,
    expectations: &[&ExpectedRow],
    mutation: Option<(&RowMutation, Option<usize>)>,
) -> Result<(), StoreError> {
    let added = expectations
        .iter()
        .filter(|row| !batch.expectations.iter().any(|old| old.key == row.key))
        .count();
    if batch.expectations.len() + added > 1024
        || batch.mutations.len()
            + usize::from(mutation.is_some_and(|(_, position)| position.is_none()))
            > 1024
    {
        return Err(StoreError::Capacity);
    }
    let mut bytes = 0usize;
    for row in &batch.expectations {
        bytes = charge(bytes, row.key.key.len(), row.value.as_deref())?;
    }
    for (index, row) in batch.mutations.iter().enumerate() {
        if mutation.is_some_and(|(_, position)| position == Some(index)) {
            continue;
        }
        bytes = charge(bytes, row.key.key.len(), row.value.as_deref())?;
    }
    for row in expectations
        .iter()
        .filter(|row| !batch.expectations.iter().any(|old| old.key == row.key))
    {
        bytes = charge(bytes, row.key.key.len(), row.value.as_deref())?;
    }
    if let Some((row, _)) = mutation {
        charge(bytes, row.key.key.len(), row.value.as_deref())?;
    }
    Ok(())
}
fn charge(before: usize, key: usize, value: Option<&[u8]>) -> Result<usize, StoreError> {
    let bytes = before
        .checked_add(key)
        .and_then(|bytes| bytes.checked_add(value.map_or(0, <[u8]>::len)))
        .ok_or(StoreError::Capacity)?;
    if bytes > 4 * 1024 * 1024 {
        return Err(StoreError::Capacity);
    }
    Ok(bytes)
}

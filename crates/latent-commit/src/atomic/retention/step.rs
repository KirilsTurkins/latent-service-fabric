use super::{ExpiredResult, MaintenanceClock, MaintenanceProgress, ResultMaintenanceOwner};
use crate::atomic::{
    record::{attempt_row_key, result_row_key},
    validate_linked_row,
    writer::{fenced_error, Usage},
    AtomicError, CommandRecord, DurableResult, Outcome,
};
use latent_core::{StateNamespaceId, TenantId};
use latent_state::{
    embedded::{AtomicBatch, EmbeddedStore, ExpectedRow, Family, ReadView, RowKey, RowMutation},
    namespace::{namespace_record_key, NamespaceRecord},
};

impl ResultMaintenanceOwner {
    /// Explicit maintenance-policy operation, including installation on an old
    /// store and recovery after boot/history changes. The host must verify clock
    /// continuity and history provenance before supplying this observation.
    /// A CAS checks the original progress; anchoring never removes a response.
    pub fn anchor(
        &self,
        store: &EmbeddedStore,
        expected_generation: Option<u64>,
        clock: MaintenanceClock,
        mut authorize: impl FnMut(Option<&CommandRecord>) -> Result<(), AtomicError>,
    ) -> Result<MaintenanceProgress, AtomicError> {
        let _physical_step = self.enter()?;
        authorize(None)?;
        clock.validate()?;
        let view = store.snapshot()?;
        let old = view.get(&MaintenanceProgress::key())?;
        let previous = old
            .as_deref()
            .map(MaintenanceProgress::decode)
            .transpose()?;
        if previous.as_ref().map(|p| p.generation) != expected_generation {
            return Err(AtomicError::Conflict);
        }
        let generation = previous.as_ref().map_or(Ok(1), |p| {
            clock.time.check(p.unix_millis)?;
            p.generation.checked_add(1).ok_or(AtomicError::Limit)
        })?;
        let mut progress = MaintenanceProgress::anchor(clock, generation);
        if let Some(previous) = previous {
            progress.visited = previous.visited;
            progress.retired = previous.retired;
            progress.reclaimed_bytes = previous.reclaimed_bytes;
        }
        let mut batch = AtomicBatch::default();
        replace(
            &mut batch,
            MaintenanceProgress::key(),
            old,
            progress.encode()?,
        );
        store
            .apply_fenced(batch, || authorize(None))
            .map_err(fenced_error)?;
        Ok(progress)
    }

    /// Inspect at most one indexed command per physical callback. Response
    /// retirement and generation-safe paging progress share one durable fence.
    /// The caller uses existing recovery admission and the original I/O deadline;
    /// no elapsed deadline can release this callback's live physical permit.
    pub fn step(
        &self,
        store: &EmbeddedStore,
        clock: MaintenanceClock,
        mut authorize: impl FnMut(Option<&CommandRecord>) -> Result<(), AtomicError>,
    ) -> Result<MaintenanceProgress, AtomicError> {
        let _physical_step = self.enter()?;
        authorize(None)?;
        let view = store.snapshot()?;
        latent_state::recovery::require_ready(&view)?;
        let old = view
            .get(&MaintenanceProgress::key())?
            .ok_or(AtomicError::RecoveryRequired)?;
        let mut progress = MaintenanceProgress::decode(&old)?;
        clock.next(&progress)?;
        let page = view.scan_after(
            Family::Command,
            b"command-v1\0",
            progress.cursor.as_deref(),
            1,
            128 * 1024,
        )?;
        let mut batch = AtomicBatch::default();
        let mut command = None;
        if let Some((key, bytes)) = page.rows.first() {
            let record = CommandRecord::decode(bytes)?;
            batch
                .expectations
                .extend(latent_state::recovery::namespace_readiness_expectations(
                    &view,
                    &TenantId(record.key.tenant.clone()),
                    &StateNamespaceId(record.key.namespace.clone()),
                    crate::atomic::incarnation(&record.key)?,
                )?);
            authorize(Some(&record))?;
            clock.time.check(record.clock_floor)?;
            validate_linked_row(&view, key, bytes)?;
            progress.visited = progress.visited.checked_add(1).ok_or(AtomicError::Limit)?;
            if record.outcome != Outcome::Pending && clock.time.unix_millis >= record.result_expires
            {
                let reclaimed = retire_body(&view, key, bytes, &record, clock, &mut batch)?;
                if reclaimed != 0 {
                    progress.retired = progress.retired.checked_add(1).ok_or(AtomicError::Limit)?;
                    progress.reclaimed_bytes = progress
                        .reclaimed_bytes
                        .checked_add(reclaimed)
                        .ok_or(AtomicError::Limit)?;
                }
            }
            command = Some(record);
        }
        if command.is_none() {
            let key = latent_state::recovery::guard_key();
            batch.expectations.push(ExpectedRow {
                value: view.get(&key)?,
                key,
            });
        }
        progress.generation = progress
            .generation
            .checked_add(1)
            .ok_or(AtomicError::Limit)?;
        progress.unix_millis = clock.time.unix_millis;
        progress.monotonic_millis = clock.monotonic_millis;
        progress.cursor = page.resume;
        replace(
            &mut batch,
            MaintenanceProgress::key(),
            Some(old),
            progress.encode()?,
        );
        store
            .apply_fenced(batch, || {
                authorize(None)?;
                if let Some(record) = &command {
                    authorize(Some(record))?;
                }
                Ok(())
            })
            .map_err(fenced_error)?;
        Ok(progress)
    }
}

fn retire_body(
    view: &ReadView,
    command_key: &RowKey,
    command_bytes: &[u8],
    record: &CommandRecord,
    clock: MaintenanceClock,
    batch: &mut AtomicBatch,
) -> Result<u64, AtomicError> {
    let result_key = result_row_key(record.id, record.attempt);
    let old = view.get(&result_key)?.ok_or(AtomicError::Corrupt)?;
    if old.starts_with(b"LCE\0") {
        ExpiredResult::decode(&old)?.verify(record)?;
        return Ok(0);
    }
    DurableResult::decode(&old)?.verify(record)?;
    let marker = ExpiredResult::new(record, clock.time.unix_millis)?.encode();
    let reclaimed = old
        .len()
        .checked_sub(marker.len())
        .ok_or(AtomicError::Corrupt)? as u64;
    let (mut usage, usage_key, usage_bytes) = Usage::read(view, &record.key)?;
    usage.result_bytes = usage
        .result_bytes
        .checked_sub(reclaimed)
        .ok_or(AtomicError::Corrupt)?;
    let namespace_key = RowKey {
        family: Family::Namespace,
        key: namespace_record_key(
            &TenantId(record.key.tenant.clone()),
            &StateNamespaceId(record.key.namespace.clone()),
        )
        .map_err(|_| AtomicError::Corrupt)?,
    };
    let namespace = view.get(&namespace_key)?.ok_or(AtomicError::Corrupt)?;
    if NamespaceRecord::decode(&namespace)
        .map_err(|_| AtomicError::Corrupt)?
        .version
        .incarnation
        != crate::atomic::incarnation(&record.key)?
    {
        return Err(AtomicError::Conflict);
    }
    let mut protected = record.clone();
    protected.clock_floor = clock.time.unix_millis;
    let protected = protected.encode()?;
    replace(
        batch,
        command_key.clone(),
        Some(command_bytes.to_vec()),
        protected.clone(),
    );
    replace(
        batch,
        attempt_row_key(record.id, record.attempt),
        Some(command_bytes.to_vec()),
        protected,
    );
    replace(batch, result_key, Some(old), marker);
    replace(batch, usage_key, usage_bytes, usage.encode());
    Ok(reclaimed)
}

fn replace(batch: &mut AtomicBatch, key: RowKey, expected: Option<Vec<u8>>, value: Vec<u8>) {
    batch.expectations.push(ExpectedRow {
        key: key.clone(),
        value: expected,
    });
    batch.mutations.push(RowMutation {
        key,
        value: Some(value),
    });
}

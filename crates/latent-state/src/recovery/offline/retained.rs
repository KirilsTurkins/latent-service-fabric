//! Finite installed reconciliation on the original exclusive fixed worker.
use super::{
    operation::Busy, OfflineOperation, OfflineRecoveryError, OfflineRecoverySource,
    PreparedRetainedReconciliation, RecoveryCodecs, RetainedReconciliationRequest, CODEC_BYTES,
    OPERATION_SCRATCH_BYTES,
};
use crate::{
    embedded::{Family, FencedStoreError, ReadView, StoreError},
    recovery::{guard_key, snapshot::validate_deadline, RecoveryGuard, RecoveryStatus},
    store_io::StoreIoKind,
};
use std::{sync::Arc, time::Instant};

const PAYLOAD_BYTES: usize = 16_384;
const RECEIPT_BYTES: usize = 16_384;
const ROWS: usize = 256;

fn validate(request: &RetainedReconciliationRequest) -> Result<(), OfflineRecoveryError> {
    for identity in [&request.operator_id, &request.operation_id] {
        crate::namespace::identity(identity)
            .map_err(|_| OfflineRecoveryError::InvalidConfiguration)?;
    }
    if request.payload.is_empty() || request.payload.len() > PAYLOAD_BYTES {
        return Err(OfflineRecoveryError::InvalidConfiguration);
    }
    Ok(())
}
fn charge(source: &OfflineRecoverySource) -> Result<u64, OfflineRecoveryError> {
    let scratch = source.codecs.scratch_bytes();
    if scratch > CODEC_BYTES {
        return Err(OfflineRecoveryError::InvalidConfiguration);
    }
    OPERATION_SCRATCH_BYTES
        .checked_add(scratch)
        .ok_or(OfflineRecoveryError::InvalidConfiguration)
}
pub(super) fn inspect(
    source: &OfflineRecoverySource,
    request: RetainedReconciliationRequest,
    deadline: Instant,
) -> Result<OfflineOperation<Vec<u8>>, OfflineRecoveryError> {
    validate(&request)?;
    validate_deadline(deadline).map_err(OfflineRecoveryError::Input)?;
    let bytes = charge(source)?;
    let busy = Busy::accept(source)?;
    let codecs = Arc::clone(&source.codecs);
    let inner = source
        .owner
        .with_store(StoreIoKind::Read, bytes, move |store| {
            let _busy = busy;
            let view = store.snapshot()?;
            Ok((|| {
                validate_deadline(deadline).map_err(OfflineRecoveryError::Input)?;
                let plan = codecs
                    .inspect_retained_reconciliation(&view, &request)
                    .map_err(OfflineRecoveryError::Review)?;
                if plan.is_empty() || plan.len() > RECEIPT_BYTES {
                    return Err(OfflineRecoveryError::Input(StoreError::Capacity));
                }
                Ok(plan)
            })())
        })
        .map_err(OfflineRecoveryError::Protected)?;
    Ok(OfflineOperation { inner })
}
pub(super) fn apply(
    source: &OfflineRecoverySource,
    request: RetainedReconciliationRequest,
    deadline: Instant,
) -> Result<OfflineOperation<Vec<u8>>, OfflineRecoveryError> {
    validate(&request)?;
    validate_deadline(deadline).map_err(OfflineRecoveryError::Input)?;
    let bytes = charge(source)?;
    let busy = Busy::accept(source)?;
    let codecs = Arc::clone(&source.codecs);
    let inner = source
        .owner
        .with_store(StoreIoKind::Write, bytes, move |store| {
            let _busy = busy;
            let view = store.snapshot()?;
            let prepared = prepare(&*codecs, &view, &request, deadline);
            drop(view);
            let prepared = match prepared {
                Ok(prepared) => prepared,
                Err(error) => return Ok(Err(OfflineRecoveryError::Review(error))),
            };
            match store.apply_fenced(prepared.batch, || {
                validate_deadline(deadline)?;
                codecs.accept_retained_reconciliation(&request)
            }) {
                Ok(()) => Ok(Ok(prepared.receipt)),
                Err(FencedStoreError::Store(error)) => Err(error),
                Err(FencedStoreError::Fence(error)) => Ok(Err(OfflineRecoveryError::Review(error))),
            }
        })
        .map_err(OfflineRecoveryError::Protected)?;
    Ok(OfflineOperation { inner })
}

fn prepare(
    codecs: &dyn RecoveryCodecs,
    view: &ReadView,
    request: &RetainedReconciliationRequest,
    deadline: Instant,
) -> Result<PreparedRetainedReconciliation, StoreError> {
    validate_deadline(deadline)?;
    codecs
        .validate_view(view)?
        .inventory
        .require_decoders(codecs.installed_formats())
        .map_err(|_| StoreError::UnsupportedFormat)?;
    let original_guard = view.get(&guard_key())?.ok_or(StoreError::Unavailable)?;
    let guard = RecoveryGuard::decode(&original_guard)?;
    let mut prepared = codecs.prepare_retained_reconciliation(view, request)?;
    if prepared.receipt.is_empty()
        || prepared.receipt.len() > RECEIPT_BYTES
        || prepared.batch.mutations.len() > ROWS
        || prepared.batch.expectations.len() > ROWS
        || (prepared.replay && !prepared.batch.mutations.is_empty())
        || (!prepared.replay && guard.status() != RecoveryStatus::ReconciliationRequired)
    {
        return Err(StoreError::Invalid);
    }
    for mutation in &prepared.batch.mutations {
        if !matches!(mutation.key.family, Family::Outbox | Family::Maintenance)
            || mutation.key == guard_key()
        {
            return Err(StoreError::UnsupportedFormat);
        }
        let old = prepared
            .batch
            .expectations
            .iter()
            .filter(|row| row.key == mutation.key)
            .collect::<Vec<_>>();
        if old.len() != 1 || view.get(&mutation.key)? != old[0].value {
            return Err(StoreError::Conflict);
        }
        if let Some(value) = &mutation.value {
            codecs.validate_row(view, &mutation.key, value)?;
        }
    }
    let mut guards = prepared
        .batch
        .expectations
        .iter()
        .filter(|row| row.key == guard_key());
    if let Some(expected) = guards.next() {
        if expected.value.as_deref() != Some(original_guard.as_slice()) || guards.next().is_some() {
            return Err(StoreError::Conflict);
        }
    } else {
        if prepared.batch.expectations.len() == ROWS {
            return Err(StoreError::Capacity);
        }
        prepared
            .batch
            .expectations
            .push(crate::embedded::ExpectedRow {
                key: guard_key(),
                value: Some(original_guard),
            });
    }
    Ok(prepared)
}

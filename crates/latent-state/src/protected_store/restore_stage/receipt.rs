//! Recover a lost completed-stage response without another write or activation.
use super::*;
use crate::recovery::{RecoveryGuard, RecoveryStatus};

impl ProtectedStoreOwner {
    /// Read the same physically sealed destination retained by this snapshot's
    /// original custody. The new input response must come from this SAME file
    /// and original reservation. Exact operation/current-owner checks precede
    /// all reads; a partially completed stage remains an explicit refusal.
    pub fn recover_restore_receipt(
        &self,
        snapshot: ProtectedSnapshot,
        input: ProtectedRestoreInput,
        request: RestoreStageRequest,
        owners: Arc<dyn RestoreStageOwners>,
    ) -> Result<ProtectedRestoreStageJob, ProtectedStoreError> {
        let inner =
            self.with_physical_custody(snapshot.custody, WORK_BYTES, move |file, source| {
                let Some(file) = file else {
                    return Ok(Err(RestoreStageError::Review(StoreError::Invalid)));
                };
                Ok(recover(source, file, input, request, owners))
            })?;
        Ok(ProtectedRestoreStageJob { inner })
    }
}

fn recover(
    source: &PhysicalStore,
    file: &SnapshotFile,
    input: ProtectedRestoreInput,
    request: RestoreStageRequest,
    owners: Arc<dyn RestoreStageOwners>,
) -> Result<RestoreStageReceipt, RestoreStageError> {
    if !input.is_from_file(file) {
        return Err(RestoreStageError::Review(StoreError::Conflict));
    }
    let held = file
        .restore_owner
        .lock()
        .map_err(|_| RestoreStageError::Review(StoreError::Unavailable))?;
    if !held
        .as_ref()
        .is_some_and(|original| Arc::ptr_eq(original, &owners))
    {
        return Err(RestoreStageError::Review(StoreError::Conflict));
    }
    drop(held);
    current(file, &input, owners.as_ref())?;
    let operation_digest = request.digest(&input).map_err(RestoreStageError::Review)?;
    let staging = file
        .restore
        .lock()
        .map_err(|_| RestoreStageError::Review(StoreError::Unavailable))?;
    if !staging.sealed || staging.adoption_prepared {
        return Err(RestoreStageError::Review(StoreError::Conflict));
    }
    let completed = staging
        .completed
        .as_ref()
        .ok_or(RestoreStageError::Review(StoreError::Conflict))?;
    if completed.operation_digest != operation_digest {
        return Err(RestoreStageError::Review(StoreError::Conflict));
    }
    let destination = staging
        .destination
        .as_ref()
        .ok_or(RestoreStageError::Review(StoreError::Corrupt))?;
    destination
        .store
        .check()
        .map_err(RestoreStageError::Destination)?;
    let actual = inspect_snapshot(&mut file.cursor(), file.deadline(), |key, bytes| {
        current_store(file, owners.as_ref())?;
        owners.archive_row(key, bytes)
    })
    .map_err(RestoreStageError::Review)?;
    if &actual != input.snapshot() {
        return Err(RestoreStageError::Review(StoreError::Conflict));
    }
    for artifact in &actual.manifest.metadata.required_artifacts {
        current(file, &input, owners.as_ref())?;
        owners
            .required_artifact(artifact)
            .map_err(RestoreStageError::Review)?;
    }
    let current_view = source
        .engine()
        .snapshot()
        .map_err(RestoreStageError::Review)?;
    let window = RestoreWindow::capture(&current_view, &actual, file.deadline(), || {
        current_store(file, owners.as_ref())
    })
    .map_err(snapshot_error)?;
    if window.digest().map_err(RestoreStageError::Review)? != request.loss_window_acknowledgement {
        return Err(RestoreStageError::Review(StoreError::Conflict));
    }
    owners
        .review_input(&current_view, &input, &request)
        .map_err(RestoreStageError::Review)?;
    let view = destination
        .store
        .engine()
        .snapshot()
        .map_err(RestoreStageError::Review)?;
    verify_import(file, &view, &actual, &window, owners.as_ref())
        .map_err(RestoreStageError::Review)?;
    if StoreIdentity::inspect(&view)
        .map_err(RestoreStageError::Review)?
        .as_ref()
        != Some(&destination.config.identity)
    {
        return Err(RestoreStageError::Review(StoreError::Corrupt));
    }
    let guard = RecoveryGuard::capture(&view)
        .map_err(RestoreStageError::Review)?
        .ok_or(RestoreStageError::Review(StoreError::Corrupt))?;
    if guard.status() != RecoveryStatus::ReconciliationRequired
        || guard.operation_digest() != operation_digest
        || guard.snapshot_digest() != actual.snapshot_digest
        || guard.window_digest() != request.loss_window_acknowledgement
        || guard.require_ready().is_ok()
    {
        return Err(RestoreStageError::Review(StoreError::Conflict));
    }
    owners
        .verify_completed(&view, &input, &request)
        .map_err(RestoreStageError::Review)?;
    let dispatch = owners
        .dispatch_checkpoint(&view)
        .map_err(RestoreStageError::Review)?;
    if owners
        .protected_clock_epoch()
        .map_err(RestoreStageError::Review)?
        != completed.checkpoint.protected_clock_epoch()
        || destination
            .checkpoint
            .inspect(&view, Some(dispatch))
            .map_err(RestoreStageError::Checkpoint)?
            .checkpoint
            .as_ref()
            != Some(&completed.checkpoint)
    {
        return Err(RestoreStageError::Review(StoreError::Conflict));
    }
    current(file, &input, owners.as_ref())?;
    input.accept_read().map_err(RestoreStageError::Review)?;
    let checkpoint = completed.checkpoint.clone();
    let imported_rows = completed.imported_rows;
    drop(view);
    drop(current_view);
    drop(staging);
    let receipt = RestoreStageReceipt {
        checkpoint,
        operation_digest,
        imported_rows,
        owners,
        input,
        request,
    };
    receipt.check()?;
    Ok(receipt)
}

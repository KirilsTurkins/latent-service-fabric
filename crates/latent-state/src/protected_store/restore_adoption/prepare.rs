use super::{
    accept, current, Arc, ProtectedRestoreAdoptionJob, ProtectedSnapshot, ProtectedStoreError,
    ProtectedStoreOwner, ReadView, RestoreAdoptionKind, RestoreAdoptionOwners, RestoreAdoptionPlan,
    RestoreAdoptionRequest, RestoreStageReceipt, SnapshotFile, StoreError,
    StoreIoRetirementWitness, PLAN_RESPONSE_BYTES,
};
use crate::{
    recovery::{RecoveryGuard, RecoveryStatus},
    store_identity::StoreIdentity,
};
use latent_core::native_capacity::NativeBufferClass;
use sha2::{Digest, Sha256};

impl ProtectedStoreOwner {
    pub fn prepare_restore_adoption(
        &self,
        mut snapshot: ProtectedSnapshot,
        stage: RestoreStageReceipt,
        request: RestoreAdoptionRequest,
        owners: Arc<dyn RestoreAdoptionOwners>,
    ) -> Result<ProtectedRestoreAdoptionJob, ProtectedStoreError> {
        validate_request(&stage, &request).map_err(ProtectedStoreError::Store)?;
        let retired = snapshot
            .retirement_witness()
            .ok_or(ProtectedStoreError::Store(StoreError::Conflict))?;
        let source = self.clone();
        let inner =
            self.with_physical_custody(snapshot.custody, 8 * 1024 * 1024, move |file, _| {
                let file = file.as_ref().ok_or(StoreError::Invalid)?;
                Ok(prepare(file, stage, request, owners, source, retired))
            })?;
        Ok(ProtectedRestoreAdoptionJob { inner })
    }
}

fn validate_request(
    stage: &RestoreStageReceipt,
    request: &RestoreAdoptionRequest,
) -> Result<(), StoreError> {
    crate::namespace::identity(&request.operator_id).map_err(|_| StoreError::Invalid)?;
    if request.operator_id.capacity() > 256
        || request.operator_id != stage.request.operator_id
        || request.operation_digest != stage.operation_digest
        || request.checkpoint_digest != <[u8; 32]>::from(Sha256::digest(stage.checkpoint.encode()))
        || request.loss_window_acknowledgement != stage.request.loss_window_acknowledgement
    {
        return Err(StoreError::Conflict);
    }
    Ok(())
}

fn prepare(
    file: &SnapshotFile,
    stage: RestoreStageReceipt,
    request: RestoreAdoptionRequest,
    owners: Arc<dyn RestoreAdoptionOwners>,
    source: ProtectedStoreOwner,
    retired: StoreIoRetirementWitness,
) -> Result<RestoreAdoptionPlan, StoreError> {
    if !stage.input.is_from_file(file) {
        return Err(StoreError::Conflict);
    }
    let held = file
        .restore_owner
        .lock()
        .map_err(|_| StoreError::Unavailable)?;
    if !held
        .as_ref()
        .is_some_and(|owner| Arc::ptr_eq(owner, &stage.owners))
    {
        return Err(StoreError::Conflict);
    }
    drop(held);
    let original = stage.input.original();
    let buffer = original
        .reserve_buffer(NativeBufferClass::Response, PLAN_RESPONSE_BYTES)
        .map_err(|_| StoreError::Capacity)?;
    let mut staging = file.restore.lock().map_err(|_| StoreError::Unavailable)?;
    if !staging.sealed || staging.adoption_prepared {
        return Err(StoreError::Conflict);
    }
    let destination = staging.destination.as_ref().ok_or(StoreError::Invalid)?;
    let plan = RestoreAdoptionPlan {
        config: destination.config.clone(),
        store_fence: destination
            .store
            .restore_fence()
            .map_err(|_| StoreError::Unavailable)?,
        checkpoint_fence: destination.checkpoint.restore_fence()?,
        stage,
        request,
        owners,
        source,
        retired,
        _buffer: buffer,
    };
    current(&plan)?;
    let view = destination.store.engine().snapshot()?;
    verify_view(&plan, &view)?;
    let dispatch = Some(plan.stage.owners.dispatch_checkpoint(&view)?);
    if destination
        .checkpoint
        .inspect(&view, dispatch)?
        .checkpoint
        .as_ref()
        != Some(&plan.stage.checkpoint)
    {
        return Err(StoreError::Conflict);
    }
    drop(view);
    destination
        .store
        .restore_fence()
        .map_err(|_| StoreError::Unavailable)?;
    destination.checkpoint.restore_fence()?;
    accept(&plan, RestoreAdoptionKind::Prepare)?;
    staging.adoption_prepared = true;
    Ok(plan)
}

pub(super) fn verify_view(plan: &RestoreAdoptionPlan, view: &ReadView) -> Result<(), StoreError> {
    current(plan)?;
    if StoreIdentity::inspect(view)?.as_ref() != Some(&plan.config.identity) {
        return Err(StoreError::Corrupt);
    }
    let guard = RecoveryGuard::capture(view)?.ok_or(StoreError::Corrupt)?;
    if guard.status() != RecoveryStatus::ReconciliationRequired
        || guard.operation_digest() != plan.stage.operation_digest
        || guard.snapshot_digest() != plan.stage.input.snapshot().snapshot_digest
        || guard.window_digest() != plan.request.loss_window_acknowledgement
        || guard.require_ready().is_ok()
    {
        return Err(StoreError::Conflict);
    }
    for artifact in &plan
        .stage
        .input
        .snapshot()
        .manifest
        .metadata
        .required_artifacts
    {
        current(plan)?;
        plan.stage.owners.required_artifact(artifact)?;
    }
    // Original staging validation preceded the completed reconciliation guard.
    // This separate mandatory review validates the completed/reopened view;
    // calling a pre-completion verifier would use the wrong lifecycle fence.
    plan.owners.review(view, &plan.stage, &plan.request)?;
    current(plan)
}

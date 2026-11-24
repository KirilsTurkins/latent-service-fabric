//! Enroll one approved logical source under the exclusive checkpoint owner.
use super::{
    ExternalCheckpoint, InboxCustodyWatermark, InventoryObservation, ProtectedCheckpoint,
    ProtectedCheckpointJob, ProtectedStoreError, ProtectedStoreOwner, METADATA_JOB_BYTES,
};
use crate::{
    embedded::{FencedStoreError, ReadView, StoreError},
    inbox_scope::{InboxScope, PreparedInboxScope},
    store_io::StoreIoKind,
};
use latent_core::native_capacity::{NativeAdmissionClass, NativeBufferClass, NativeReservation};
use std::sync::Arc;

impl ProtectedStoreOwner {
    /// Add one approved source while the offline caller owns the actual store
    /// and external checkpoint. A crash between the two publications leaves a
    /// mismatch that normal startup refuses before polling.
    #[expect(
        clippy::too_many_arguments,
        reason = "Keep the original owner, live approval and both custody observations explicit"
    )]
    pub fn enroll_inbox_source(
        &self,
        checkpoint: ProtectedCheckpoint,
        expected: ExternalCheckpoint,
        source: InboxScope,
        keeper: Arc<NativeReservation>,
        inventory_bytes: u64,
        inspect: impl Fn(&ReadView) -> Result<Option<(u64, u64)>, StoreError> + Send + 'static,
        validate_before: impl FnOnce(&ReadView) -> Result<Option<InboxCustodyWatermark>, StoreError>
            + Send
            + 'static,
        validate_after: impl FnOnce(
                &ReadView,
                Option<InboxCustodyWatermark>,
            ) -> Result<InboxCustodyWatermark, StoreError>
            + Send
            + 'static,
        accept: impl FnOnce() -> Result<(), StoreError> + Send + 'static,
    ) -> Result<ProtectedCheckpointJob<ExternalCheckpoint>, ProtectedStoreError> {
        if inventory_bytes == 0
            || inventory_bytes > 8 * 1024 * 1024
            || keeper.class() != NativeAdmissionClass::Recovery
            || !keeper.is_from_owner(&self.native_capacity()?)
        {
            return Err(ProtectedStoreError::InvalidConfiguration);
        }
        let job_bytes = METADATA_JOB_BYTES + inventory_bytes;
        let buffer = keeper
            .reserve_buffer(NativeBufferClass::Work, job_bytes)
            .map_err(|_| ProtectedStoreError::InvalidConfiguration)?;
        let inner = self.with_resource(
            checkpoint.resource,
            StoreIoKind::RecoveryWrite,
            job_bytes,
            move |file, engine| {
                let _buffer = buffer;
                let view = engine.snapshot()?;
                let dispatch = inspect(&view)?;
                let before = validate_before(&view)?;
                let existing = file.inspect_with_inventory(
                    &view,
                    dispatch,
                    InventoryObservation::Observed(before),
                    &keeper,
                )?;
                if existing.checkpoint.as_ref() != Some(&expected) {
                    return Err(StoreError::Conflict);
                }
                let plan = PreparedInboxScope::prepare(&view, &source)?;
                if plan.existing() {
                    return Err(StoreError::Conflict);
                }
                drop(view);
                engine
                    .apply_fenced(plan.into_batch(), accept)
                    .map_err(|error| match error {
                        FencedStoreError::Store(error) | FencedStoreError::Fence(error) => error,
                    })?;

                // The store commit may already be durable. Any subsequent
                // refusal must remain uncertain until the inventory and
                // external checkpoint can be reconciled.
                (|| {
                    let after = engine.snapshot()?;
                    let watermark = validate_after(&after, before)?;
                    if inspect(&after)? != dispatch {
                        return Err(StoreError::Conflict);
                    }
                    file.seal_enrolled_inbox_source(&after, &expected, watermark, &keeper)
                })()
                .map_err(|_| StoreError::CommitUncertain)
            },
        )?;
        Ok(ProtectedCheckpointJob { inner })
    }
}

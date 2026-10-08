//! Activation through the original affine checkpoint and physical Recovery
//! owner. No engine/file/retirement proof is created from a receipt or flag.

use super::{
    custody::ProtectedCustodyJob,
    snapshot::{ProtectedSnapshot, SnapshotFile},
    AggregateMigrationOwners, ProtectedStoreError, ProtectedStoreOwner,
};
use crate::{
    embedded::{EmbeddedStore, FencedStoreError, StoreError},
    namespace::compatibility::ReviewedSchema,
    recovery::{
        migration::{inspect_progress, MigrationError},
        resume::{
            MigrationResumeAction, MigrationResumePlan, MigrationResumeReceipt,
            MigrationResumeRequest, RECEIPT_BYTES,
        },
        snapshot::inspect_snapshot,
    },
    store_io::{StoreIoError, StoreIoKind},
};
use latent_core::native_capacity::{
    NativeBufferClass, NativeBufferPermit, NativeCapacityError, NativeReservation,
};
use std::{
    cell::Cell,
    future::Future,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll},
};

/// The installed current owner consumes this inside its original
/// policy/namespace/effects fences. This affine gate checks only the SAME
/// original native request; it creates no permission or time continuity.
pub struct MigrationResumeCommitFence<'a> {
    original: &'a NativeReservation,
    consumed: &'a Cell<bool>,
    action: MigrationResumeAction,
}
impl MigrationResumeCommitFence<'_> {
    #[must_use]
    pub const fn action(&self) -> MigrationResumeAction {
        self.action
    }

    pub fn accept(self) -> Result<(), StoreError> {
        if self.consumed.get() {
            return Err(StoreError::Invalid);
        }
        self.original
            .with_live(|| self.consumed.set(true))
            .map_err(|_| StoreError::SnapshotExpired)
    }
}

/// Actual bounded response metadata keeps the original prepaid response bytes
/// until destruction, even after the native checkpoint has positively retired.
/// A transport additionally keeps this owner through its last encoded frame.
pub struct ProtectedMigrationResumeReceipt {
    action: MigrationResumeAction,
    receipt: MigrationResumeReceipt,
    _buffer: NativeBufferPermit,
    _original: Arc<NativeReservation>,
}
impl ProtectedMigrationResumeReceipt {
    #[must_use]
    pub const fn action(&self) -> MigrationResumeAction {
        self.action
    }

    #[must_use]
    pub fn receipt(&self) -> &MigrationResumeReceipt {
        &self.receipt
    }
}

#[must_use = "accepted activation and response custody survive waiter loss"]
pub struct ProtectedMigrationResumeJob {
    inner: ProtectedCustodyJob<
        Option<SnapshotFile>,
        Result<ProtectedMigrationResumeReceipt, MigrationError>,
    >,
}
impl Future for ProtectedMigrationResumeJob {
    type Output = Result<
        (
            ProtectedSnapshot,
            Result<Result<ProtectedMigrationResumeReceipt, MigrationError>, ProtectedStoreError>,
        ),
        StoreIoError,
    >;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        match Pin::new(&mut self.get_mut().inner).poll(cx) {
            Poll::Ready(Ok((custody, result))) => {
                Poll::Ready(Ok((ProtectedSnapshot { custody }, result)))
            }
            Poll::Ready(Err(error)) => Poll::Ready(Err(error)),
            Poll::Pending => Poll::Pending,
        }
    }
}

impl ProtectedStoreOwner {
    /// Deliberately activate one complete original fixed migration. The same
    /// physical snapshot custody excludes commits/readers/dispatch/maintenance;
    /// a caller-supplied clean flag or count is never consulted. The original
    /// immutable file is re-read and current work/codecs/artifacts are reviewed.
    ///
    /// Existing migration owners explicitly refuse this new action by default.
    /// A concrete current-authorized host must install both resume callbacks,
    /// with conservative time continuity and original publication/retained-work
    /// checks. No restore guard, checkpoint, rule or credential is renewed here.
    pub fn resume_migration(
        &self,
        snapshot: ProtectedSnapshot,
        request: MigrationResumeRequest,
        schema: ReviewedSchema,
        owners: Arc<dyn AggregateMigrationOwners>,
    ) -> Result<ProtectedMigrationResumeJob, ProtectedStoreError> {
        request.validate().map_err(ProtectedStoreError::Store)?;
        let inner = self.with_custody(
            snapshot.custody,
            StoreIoKind::RecoveryWrite,
            8 * 1024 * 1024,
            move |file, store| {
                let Some(file) = file else {
                    return Ok(Err(MigrationError::Review(StoreError::Invalid)));
                };
                if let Err(error) = file.retain_migration_owner(&owners) {
                    return Ok(Err(MigrationError::Review(error)));
                }
                match apply(store, file, &request, &schema, &owners) {
                    Err(MigrationError::Source(error)) => Err(error),
                    outcome => Ok(outcome),
                }
            },
        )?;
        Ok(ProtectedMigrationResumeJob { inner })
    }
}

fn apply(
    store: &EmbeddedStore,
    file: &SnapshotFile,
    request: &MigrationResumeRequest,
    schema: &ReviewedSchema,
    owners: &Arc<dyn AggregateMigrationOwners>,
) -> Result<ProtectedMigrationResumeReceipt, MigrationError> {
    // Reserve the actual retained result BEFORE preparing or publishing the
    // activation. It cannot borrow ordinary slots or be refunded at encoding.
    let original = file.retain_original();
    let buffer = original
        .reserve_buffer(NativeBufferClass::Response, RECEIPT_BYTES as u64)
        .map_err(|error| match error {
            NativeCapacityError::DeadlineExceeded => MigrationError::Deadline,
            NativeCapacityError::BufferLimit
            | NativeCapacityError::BufferTooLarge
            | NativeCapacityError::AllocationFailed => MigrationError::Capacity,
            _ => MigrationError::Review(StoreError::Unavailable),
        })?;
    file.check()
        .map_err(|_| MigrationError::Review(StoreError::Unavailable))?;
    let view = store.snapshot().map_err(MigrationError::source)?;
    let progress = inspect_progress(
        &view,
        &request.migration.scope,
        &request.migration.operator_id,
        &request.migration.operation_id,
    )
    .map_err(MigrationError::source)?;
    let Some(progress) = progress else {
        let key = request.receipt_key().map_err(MigrationError::Review)?;
        return if view
            .get_bounded(&key, RECEIPT_BYTES)
            .map_err(MigrationError::source)?
            .is_some()
        {
            Err(MigrationError::Source(StoreError::Corrupt))
        } else {
            Err(MigrationError::Review(StoreError::Conflict))
        };
    };
    progress
        .require_input(&request.migration)
        .map_err(MigrationError::Review)?;
    let checkpoint = inspect_snapshot(&mut file.cursor(), file.deadline(), |key, bytes| {
        owners.row(key, bytes)
    })
    .map_err(MigrationError::Review)?;
    if checkpoint.snapshot_digest != progress.checkpoint_digest()
        || checkpoint.manifest_digest != progress.checkpoint_manifest_digest()
    {
        return Err(MigrationError::Review(StoreError::Conflict));
    }
    for artifact in &checkpoint.manifest.metadata.required_artifacts {
        owners.artifact(artifact).map_err(MigrationError::Review)?;
    }
    for artifact in progress
        .required_artifacts()
        .map_err(MigrationError::source)?
    {
        owners.artifact(&artifact).map_err(MigrationError::Review)?;
    }
    let closure = owners.linked(&view)?;
    let plan = MigrationResumePlan::prepare(
        &view,
        request,
        schema,
        file.deadline(),
        |view, request, observation| owners.review_resume(view, request, observation, &closure),
    )?;
    let (batch, receipt, action) = plan.into_parts();
    drop(view);
    file.check()
        .map_err(|_| MigrationError::Review(StoreError::Unavailable))?;
    let consumed = Cell::new(false);
    store
        .apply_fenced(batch, || {
            owners.accept_resume(MigrationResumeCommitFence {
                original: &original,
                consumed: &consumed,
                action,
            })?;
            if !consumed.get() {
                return Err(StoreError::Invalid);
            }
            Ok(())
        })
        .map_err(|error| match error {
            FencedStoreError::Store(error) => MigrationError::source(error),
            FencedStoreError::Fence(error) => MigrationError::Review(error),
        })?;
    // Accepted activation is already durable. Losing current input access or
    // its protected file association after I/O cannot be reported as no-commit,
    // nor may it quarantine a healthy business engine as a policy failure.
    file.check()
        .map_err(|_| MigrationError::Review(StoreError::CommitUncertain))?;
    Ok(ProtectedMigrationResumeReceipt {
        action,
        receipt,
        _buffer: buffer,
        _original: original,
    })
}

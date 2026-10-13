//! Same physical snapshot/native writer, with distinct restored attribution.
use super::{
    custody::ProtectedCustodyJob,
    snapshot::{ProtectedSnapshot, SnapshotFile},
    ProtectedStoreError, ProtectedStoreOwner,
};
use crate::{
    embedded::{FencedStoreError, ReadView, RowKey, StoreError},
    namespace::compatibility::ReviewedSchema,
    recovery::{
        migration::MigrationError,
        restored_resume::{
            RestoredMigrationResumeObservation, RestoredMigrationResumePlan,
            RestoredMigrationResumeReceipt, RestoredMigrationResumeRequest, RECEIPT_BYTES,
        },
        snapshot::{RequiredArtifact, SnapshotClosure},
    },
    store_io::{StoreIoError, StoreIoKind},
};
use latent_core::native_capacity::{NativeBufferClass, NativeBufferPermit, NativeReservation};
use sha2::{Digest, Sha256};
use std::{
    cell::Cell,
    future::Future,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll},
};

pub trait RestoredMigrationResumeOwners: Send + Sync + 'static {
    fn row(&self, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError>;
    fn artifact(&self, artifact: &RequiredArtifact) -> Result<(), StoreError>;
    fn linked(&self, view: &ReadView) -> Result<SnapshotClosure, StoreError>;
    fn review(
        &self,
        view: &ReadView,
        request: &RestoredMigrationResumeRequest,
        observation: RestoredMigrationResumeObservation<'_>,
    ) -> Result<(), StoreError>;
    fn accept(&self, original: RestoredMigrationResumeCommitFence<'_>) -> Result<(), StoreError>;
}
pub struct RestoredMigrationResumeCommitFence<'a> {
    original: &'a NativeReservation,
    consumed: &'a Cell<bool>,
}
impl RestoredMigrationResumeCommitFence<'_> {
    pub fn accept(self) -> Result<(), StoreError> {
        if self.consumed.get() {
            return Err(StoreError::Invalid);
        }
        self.original
            .with_live(|| self.consumed.set(true))
            .map_err(|_| StoreError::SnapshotExpired)
    }
}
pub struct ProtectedRestoredMigrationResumeReceipt {
    receipt: RestoredMigrationResumeReceipt,
    replayed: bool,
    _buffer: NativeBufferPermit,
    _original: Arc<NativeReservation>,
}
impl ProtectedRestoredMigrationResumeReceipt {
    #[must_use]
    pub fn receipt(&self) -> &RestoredMigrationResumeReceipt {
        &self.receipt
    }
    #[must_use]
    pub fn replayed(&self) -> bool {
        self.replayed
    }
}
#[must_use = "accepted restored activation and original file survive waiter loss"]
pub struct ProtectedRestoredMigrationResumeJob {
    inner: ProtectedCustodyJob<
        Option<SnapshotFile>,
        Result<ProtectedRestoredMigrationResumeReceipt, MigrationError>,
    >,
}
impl Future for ProtectedRestoredMigrationResumeJob {
    type Output = Result<
        (
            ProtectedSnapshot,
            Result<
                Result<ProtectedRestoredMigrationResumeReceipt, MigrationError>,
                ProtectedStoreError,
            >,
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
    pub fn resume_restored_migration(
        &self,
        snapshot: ProtectedSnapshot,
        request: RestoredMigrationResumeRequest,
        schema: ReviewedSchema,
        owners: Arc<dyn RestoredMigrationResumeOwners>,
    ) -> Result<ProtectedRestoredMigrationResumeJob, ProtectedStoreError> {
        request.validate().map_err(ProtectedStoreError::Store)?;
        let work = snapshot.custody.maximum_job_bytes();
        let inner = self.with_custody(
            snapshot.custody,
            StoreIoKind::RecoveryWrite,
            work,
            move |file, store| {
                let Some(file) = file else {
                    return Ok(Err(MigrationError::Review(StoreError::Invalid)));
                };
                match apply(store, file, &request, &schema, &owners) {
                    Err(MigrationError::Source(error)) => Err(error),
                    outcome => Ok(outcome),
                }
            },
        )?;
        Ok(ProtectedRestoredMigrationResumeJob { inner })
    }
}
fn apply(
    store: &crate::embedded::EmbeddedStore,
    file: &SnapshotFile,
    request: &RestoredMigrationResumeRequest,
    schema: &ReviewedSchema,
    owners: &Arc<dyn RestoredMigrationResumeOwners>,
) -> Result<ProtectedRestoredMigrationResumeReceipt, MigrationError> {
    let original = file.retain_original();
    let buffer = original
        .reserve_buffer(NativeBufferClass::Response, RECEIPT_BYTES as u64)
        .map_err(|_| MigrationError::Capacity)?;
    file.check()
        .map_err(|_| MigrationError::Review(StoreError::Unavailable))?;
    let mut prefix = crate::recovery::migration::PROGRESS_PREFIX.to_vec();
    prefix.extend_from_slice(
        &crate::namespace::namespace_record_key(&request.scope.tenant, &request.scope.namespace)
            .map_err(|_| MigrationError::Review(StoreError::Invalid))?,
    );
    prefix.extend_from_slice(&request.scope.incarnation.to_le_bytes());
    let mut progress = None::<(RowKey, [u8; 32])>;
    let snapshot = file
        .inspect(|key, bytes| {
            owners.row(key, bytes)?;
            if key.family == crate::embedded::Family::Maintenance && key.key.starts_with(&prefix) {
                let digest = Sha256::digest(bytes).into();
                // The protected decoder rereads every row to verify manifest
                // history. Strict stream ordering rejects same-pass duplicates;
                // both passes must capture this exact same progress key/bytes.
                if let Some((original_key, original_digest)) = &progress {
                    if original_key != key || *original_digest != digest {
                        return Err(StoreError::UnsupportedFormat);
                    }
                } else {
                    progress = Some((key.clone(), digest));
                }
            }
            Ok(())
        })
        .map_err(MigrationError::Review)?;
    for artifact in &snapshot.manifest.metadata.required_artifacts {
        owners.artifact(artifact).map_err(MigrationError::Review)?;
    }
    let (_, progress) = progress.ok_or(MigrationError::Review(StoreError::UnsupportedFormat))?;
    let view = store.snapshot().map_err(MigrationError::source)?;
    owners
        .linked(&view)
        .map_err(MigrationError::Review)?
        .inventory
        .require_retirement_drained()
        .map_err(|_| MigrationError::Review(StoreError::Unavailable))?;
    let plan = RestoredMigrationResumePlan::prepare(
        &view,
        request,
        &snapshot,
        progress,
        schema,
        |view, request, observed| owners.review(view, request, observed),
    )
    .map_err(MigrationError::Review)?;
    let replayed = plan.replayed();
    let receipt = RestoredMigrationResumeReceipt::decode(
        &plan.receipt().encode().map_err(MigrationError::Review)?,
    )
    .map_err(MigrationError::Review)?;
    let batch = plan.into_batch();
    drop(view);
    let consumed = Cell::new(false);
    store
        .apply_fenced(batch, || {
            file.check().map_err(|_| StoreError::Unavailable)?;
            owners.accept(RestoredMigrationResumeCommitFence {
                original: &original,
                consumed: &consumed,
            })?;
            if !consumed.get() {
                return Err(StoreError::Unavailable);
            }
            Ok(())
        })
        .map_err(|error| match error {
            FencedStoreError::Store(error) => MigrationError::source(error),
            FencedStoreError::Fence(error) => MigrationError::Review(error),
        })?;
    file.check()
        .map_err(|_| MigrationError::Source(StoreError::CommitUncertain))?;
    Ok(ProtectedRestoredMigrationResumeReceipt {
        receipt,
        replayed,
        _buffer: buffer,
        _original: original,
    })
}

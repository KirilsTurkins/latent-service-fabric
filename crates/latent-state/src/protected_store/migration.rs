//! Original snapshot/file/custody application of the closed migration producer.
use super::{
    custody::ProtectedCustodyJob,
    snapshot::{ProtectedSnapshot, SnapshotFile},
    ProtectedStoreError, ProtectedStoreOwner,
};
use crate::{
    embedded::{FencedStoreError, ReadView, RowKey, StoreError},
    namespace::compatibility::ReviewedSchema,
    recovery::{
        migration::{
            AggregateMigrationObservation, AggregateMigrationPlan, AggregateMigrationProgress,
            AggregateMigrationRecipe, AggregateMigrationRequest, MigrationAction, MigrationError,
            MigrationPhase, VerifiedMigrationCheckpoint,
        },
        snapshot::{RequiredArtifact, SnapshotClosure},
    },
    store_io::{StoreIoError, StoreIoKind},
};
use latent_core::native_capacity::NativeReservation;
use std::{
    cell::Cell,
    future::Future,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll},
};

/// The concrete host supplies original authenticated policy/lifecycle/critical
/// audit and immutable catalog reviewers. There is no default allowed owner.
/// Review may consult only retained bounded inputs on the fixed native worker.
/// `accept` is short metadata only: no I/O, guest, clock renewal or await.
/// It holds original policy/namespace/effect fences BEFORE consuming `native`.
pub trait AggregateMigrationOwners: Send + Sync + 'static {
    fn row(&self, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError>;
    fn linked(&self, view: &ReadView) -> Result<SnapshotClosure, MigrationError>;
    fn artifact(&self, artifact: &RequiredArtifact) -> Result<(), StoreError>;
    fn review(
        &self,
        view: &ReadView,
        request: &AggregateMigrationRequest,
        observation: AggregateMigrationObservation<'_>,
    ) -> Result<(), StoreError>;
    fn accept(&self, native: MigrationCommitFence<'_>) -> Result<(), StoreError>;
}

/// Affine final original-native check, not an authorization grant. Only this
/// invocation's actual gate can satisfy the writer; ignoring it is refusal.
pub struct MigrationCommitFence<'a> {
    original: &'a NativeReservation,
    consumed: &'a Cell<bool>,
    action: MigrationAction,
}
impl MigrationCommitFence<'_> {
    #[must_use]
    pub const fn action(&self) -> MigrationAction {
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

/// Exact persisted receipt. This description supplies no permission to expose
/// data, resume execution, retry an effect, or activate the changed schema.
pub struct MigrationReceipt {
    action: MigrationAction,
    progress: AggregateMigrationProgress,
}
impl MigrationReceipt {
    #[must_use]
    pub const fn action(&self) -> MigrationAction {
        self.action
    }

    #[must_use]
    pub fn progress(&self) -> &AggregateMigrationProgress {
        &self.progress
    }
}

#[must_use = "accepted migration and file custody survive waiter loss"]
pub struct ProtectedMigrationJob {
    inner: ProtectedCustodyJob<Option<SnapshotFile>, Result<MigrationReceipt, MigrationError>>,
}
impl Future for ProtectedMigrationJob {
    type Output = Result<
        (
            ProtectedSnapshot,
            Result<Result<MigrationReceipt, MigrationError>, ProtectedStoreError>,
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
    /// Use the SAME affine checkpoint/custody and original finite request. Stage
    /// persists a paused marker; Complete atomically transforms the fixed cell,
    /// namespace/schema epoch, progress and tenant categories. Both remain
    /// paused. A lost/uncertain write requires original durable receipt lookup.
    pub fn migrate_aggregate(
        &self,
        snapshot: ProtectedSnapshot,
        request: AggregateMigrationRequest,
        schema: ReviewedSchema,
        selected: (AggregateMigrationRecipe, MigrationPhase),
        owners: Arc<dyn AggregateMigrationOwners>,
    ) -> Result<ProtectedMigrationJob, ProtectedStoreError> {
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
                let outcome = apply(store, file, &request, &schema, selected, &owners);
                match outcome {
                    Err(MigrationError::Source(error)) => Err(error),
                    outcome => Ok(outcome),
                }
            },
        )?;
        Ok(ProtectedMigrationJob { inner })
    }
}

fn apply(
    store: &crate::embedded::EmbeddedStore,
    file: &SnapshotFile,
    request: &AggregateMigrationRequest,
    schema: &ReviewedSchema,
    selected: (AggregateMigrationRecipe, MigrationPhase),
    owners: &Arc<dyn AggregateMigrationOwners>,
) -> Result<MigrationReceipt, MigrationError> {
    file.check()
        .map_err(|_| MigrationError::Review(StoreError::Unavailable))?;
    let view = store.snapshot().map_err(MigrationError::source)?;
    let checkpoint = VerifiedMigrationCheckpoint::inspect(
        &view,
        &mut file.cursor(),
        file.deadline(),
        |key, bytes| owners.row(key, bytes),
        |view| owners.linked(view),
        |artifact| owners.artifact(artifact),
    )?;
    let plan = AggregateMigrationPlan::prepare(
        &view,
        request,
        &checkpoint,
        schema,
        selected,
        file.deadline(),
        |view, request, observation| owners.review(view, request, observation),
    )?;
    let (batch, progress, action) = plan.into_parts();
    drop(view); // Native read storage retires before the actual single writer.
    file.check()
        .map_err(|_| MigrationError::Review(StoreError::Unavailable))?;
    let consumed = Cell::new(false);
    store
        .apply_fenced(batch, || {
            owners.accept(MigrationCommitFence {
                original: file.original(),
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
    Ok(MigrationReceipt { action, progress })
}

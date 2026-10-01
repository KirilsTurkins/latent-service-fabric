use super::{
    file::ProtectedSnapshotFile, operation::Busy, OfflineAggregateMigrationRequest,
    OfflineOperation, OfflineRecoveryError, OfflineRecoverySource, CODEC_BYTES,
    OPERATION_SCRATCH_BYTES,
};
use crate::{
    embedded::FencedStoreError,
    recovery::{
        migration::{
            AggregateMigrationPlan, AggregateMigrationProgress, MigrationAction,
            VerifiedMigrationCheckpoint,
        },
        snapshot::validate_deadline,
    },
    store_io::StoreIoKind,
};
use latent_protected_files::ProtectedRoot;
use std::{sync::Arc, time::Instant};

pub(super) fn execute(
    source: &OfflineRecoverySource,
    request: OfflineAggregateMigrationRequest,
    phase: MigrationAction,
    deadline: Instant,
) -> Result<OfflineOperation<AggregateMigrationProgress>, OfflineRecoveryError> {
    request
        .review
        .validate()
        .map_err(OfflineRecoveryError::Input)?;
    validate_deadline(deadline).map_err(OfflineRecoveryError::Input)?;
    if request.review.scope.tenant.0 != source.tenant || source.codecs.scratch_bytes() > CODEC_BYTES
    {
        return Err(OfflineRecoveryError::InvalidConfiguration);
    }
    let paths = ProtectedSnapshotFile::validate(&request.checkpoint)?;
    let bytes = OPERATION_SCRATCH_BYTES
        .checked_add(source.codecs.scratch_bytes())
        .and_then(|bytes| bytes.checked_add(paths))
        .ok_or(OfflineRecoveryError::InvalidConfiguration)?;
    let compact = request.clone();
    drop(request);
    let request = compact;
    let busy = Busy::accept(source)?;
    let codecs = Arc::clone(&source.codecs);
    let source_root = source.source_root.clone();
    let inner = source
        .owner
        .with_store(StoreIoKind::Write, bytes, move |store| {
            let _busy = busy;
            let view = store.snapshot()?;
            let prepared = (|| {
                validate_deadline(deadline).map_err(OfflineRecoveryError::Input)?;
                let schema = codecs
                    .migration_schema(&view, &request)
                    .map_err(OfflineRecoveryError::Review)?;
                let recipe = codecs
                    .migration_recipe(&view, &request)
                    .map_err(OfflineRecoveryError::Review)?;
                let root = ProtectedRoot::open(&source_root)
                    .map_err(|_| OfflineRecoveryError::UnsafeDestination)?;
                let mut input =
                    ProtectedSnapshotFile::open(&request.checkpoint, root.identity(), false)?;
                let checkpoint = VerifiedMigrationCheckpoint::inspect(
                    &view,
                    &mut input,
                    deadline,
                    |key, bytes| codecs.validate_row(&view, key, bytes),
                    |view| codecs.validate_view(view),
                    |artifact| codecs.verify_artifact(artifact),
                )
                .map_err(OfflineRecoveryError::Input)?;
                if checkpoint.receipt().manifest.metadata.runtime_digest != codecs.runtime_digest()
                {
                    return Err(OfflineRecoveryError::Input(
                        crate::embedded::StoreError::UnsupportedFormat,
                    ));
                }
                let plan = AggregateMigrationPlan::prepare_with_recipe(
                    &view,
                    &request.review,
                    &checkpoint,
                    &schema,
                    (recipe, phase),
                    deadline,
                    |view, _, observed| codecs.review_migration(view, &request, observed),
                )
                .map_err(OfflineRecoveryError::Review)?;
                input
                    .check()
                    .map_err(|_| OfflineRecoveryError::UnsafeDestination)?;
                Ok((plan, input))
            })();
            drop(view);
            let (plan, input) = match prepared {
                Ok(plan) => plan,
                Err(error) => return Ok(Err(error)),
            };
            let progress = plan.progress().clone();
            let result = store.apply_fenced(plan.into_batch(), || {
                validate_deadline(deadline)?;
                codecs.accept_migration(&request, phase)
            });
            match result {
                Ok(()) => {
                    if input.check().is_err() {
                        return Err(crate::embedded::StoreError::CommitUncertain);
                    }
                    Ok(Ok(progress))
                }
                Err(FencedStoreError::Store(error)) => Err(error),
                Err(FencedStoreError::Fence(error)) => Ok(Err(OfflineRecoveryError::Review(error))),
            }
        })
        .map_err(OfflineRecoveryError::Protected)?;
    Ok(OfflineOperation { inner })
}

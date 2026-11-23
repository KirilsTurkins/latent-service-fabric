//! A reviewed maintenance page uses the original worker and protected clock.
use super::{awaited, failure, protected, Codecs};
use latent_commit::atomic::{AtomicError, MaintenanceProgress, ResultMaintenanceOwner};
use latent_core::{native_capacity::NativeBufferClass, PlatformError};
use latent_state::{
    embedded::{ReadView, StoreError},
    protected_store::ProtectedStoreOwner,
    recovery::require_namespace_ready,
    store_io::StoreIoKind,
};
use latent_wire::phase4::StateMaintenanceClock;
use std::sync::Arc;

const PURPOSE: &str = "purge-expired-payload";

pub(super) fn inspect(view: &ReadView) -> Result<serde_json::Value, StoreError> {
    MaintenanceProgress::inspect(view)
        .map(|progress| progress.as_ref().map_or(serde_json::Value::Null, describe))
        .map_err(|error| match error {
            AtomicError::Expired => StoreError::SnapshotExpired,
            AtomicError::Unavailable => StoreError::Unavailable,
            _ => StoreError::Corrupt,
        })
}

pub(super) async fn sweep(
    store: &ProtectedStoreOwner,
    codecs: &Arc<Codecs>,
    expected_view: Vec<u8>,
    expected_generation: Option<u64>,
) -> Result<serde_json::Value, PlatformError> {
    let bytes = ResultMaintenanceOwner::RETAINED_BYTES;
    let permit = codecs
        .original
        .reserve_buffer(NativeBufferClass::Work, bytes)
        .map_err(|_| super::super::capacity())?;
    let clock = super::super::super::maintenance::ProtectedMaintenanceClock::new(Arc::clone(
        &codecs.authority.clock,
    ))?;
    let worker = Arc::clone(codecs);
    let job = store
        .with_store_retaining(
            StoreIoKind::RecoveryWrite,
            bytes,
            Arc::clone(codecs) as Arc<dyn std::any::Any + Send + Sync>,
            move |engine| {
                let _permit = permit;
                let view = engine.snapshot()?;
                worker.closure(&view)?;
                let selected = worker.selected_view(&view)?;
                if selected.view_token()? != expected_view {
                    return Err(StoreError::Conflict);
                }
                require_namespace_ready(
                    &view,
                    &selected.namespace.tenant,
                    &selected.namespace.id,
                    selected.namespace.version.incarnation,
                )?;
                drop(view);
                let scope = selected.namespace;
                let epoch = scope.version.incarnation.to_string();
                let clock = clock.sample().map_err(|_| StoreError::Unavailable)?;
                let result = ResultMaintenanceOwner::default().reviewed_step(
                    engine,
                    clock,
                    expected_generation,
                    |record| {
                        if record.is_some_and(|command| {
                            command.key().tenant != scope.tenant.0
                                || command.key().namespace != scope.id.0
                                || command.key().incarnation != epoch
                        }) {
                            return Err(AtomicError::PermissionDenied);
                        }
                        worker
                            .fence(PURPOSE, || worker.time().map(|_| ()))
                            .map_err(|_| AtomicError::PermissionDenied)
                    },
                );
                match result {
                    Ok(progress) => {
                        worker.check().map_err(|_| StoreError::CommitUncertain)?;
                        Ok(Ok(serde_json::json!({
                            "action": "sweep-result-bodies",
                            "resultMaintenance": describe(&progress),
                        })))
                    }
                    Err(AtomicError::Corrupt) => Err(StoreError::Corrupt),
                    Err(AtomicError::Unavailable) => Err(StoreError::Unavailable),
                    Err(AtomicError::RecoveryRequired) => {
                        drop(engine.snapshot().map_err(|_| StoreError::CommitUncertain)?);
                        Ok(Err(AtomicError::RecoveryRequired))
                    }
                    Err(error) => Ok(Err(error)),
                }
            },
        )
        .map_err(protected)?;
    awaited(job, codecs)
        .await?
        .map_err(protected)?
        .map_err(|error| failure(format!("protected-result-maintenance:{error:?}")))
}

fn describe(progress: &MaintenanceProgress) -> serde_json::Value {
    serde_json::json!({
        "generation": progress.generation.to_string(),
        "coveredUnixMillis": progress.unix_millis.to_string(),
        "visited": progress.visited.to_string(),
        "resultBodiesRetired": progress.retired.to_string(),
        "reclaimedResultBytes": progress.reclaimed_bytes.to_string(),
        "passComplete": progress.cursor.is_none(),
    })
}

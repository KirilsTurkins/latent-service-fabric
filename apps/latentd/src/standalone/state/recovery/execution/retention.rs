//! A reviewed maintenance page uses the original worker and protected clock.
use super::{awaited, failure, protected, Codecs};
use latent_commit::atomic::{
    retention::ScopedResultBody, AtomicError, Identity, MaintenanceProgress, ResultMaintenanceOwner,
};
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
    retention_progress(view)
        .map(|progress| progress.as_ref().map_or(serde_json::Value::Null, describe))
}
fn retention_progress(view: &ReadView) -> Result<Option<MaintenanceProgress>, StoreError> {
    MaintenanceProgress::inspect(view).map_err(|error| match error {
        AtomicError::Expired => StoreError::SnapshotExpired,
        AtomicError::Unavailable => StoreError::Unavailable,
        _ => StoreError::Corrupt,
    })
}

pub(super) async fn inspect_scope(
    store: &ProtectedStoreOwner,
    codecs: &Arc<Codecs>,
) -> Result<serde_json::Value, PlatformError> {
    let original = Arc::clone(codecs);
    let job = store
        .with_store_retaining(
            StoreIoKind::RecoveryRead,
            64 * 1024,
            Arc::clone(codecs) as Arc<dyn std::any::Any + Send + Sync>,
            move |engine| {
                let view = engine.snapshot()?;
                let scope = original.selected_view(&view)?;
                let generation = retention_progress(&view)?;
                original.check()?;
                Ok(serde_json::json!({
                    "action": "inspect-result-maintenance",
                    "view": scope.view_token()?,
                    "generation": generation.map(|record| record.generation.to_string()),
                }))
            },
        )
        .map_err(protected)?;
    awaited(job, codecs).await?.map_err(protected)
}

pub(super) async fn sweep(
    store: &ProtectedStoreOwner,
    codecs: &Arc<Codecs>,
    expected_view: Vec<u8>,
    expected_generation: Option<u64>,
    command: Option<Identity>,
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
                if command.is_none() {
                    worker.closure(&view)?;
                }
                let selected = worker.selected_view(&view)?;
                if command.is_none() && selected.view_token()? != expected_view {
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
                let authorize = |record: Option<&latent_commit::atomic::CommandRecord>| {
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
                };
                let owner = ResultMaintenanceOwner::default();
                let result = if let Some(command) = command {
                    owner
                        .expire_reviewed_body(
                            engine,
                            clock,
                            ScopedResultBody {
                                command,
                                namespace: &scope,
                                expected_view: &expected_view,
                                expected_generation,
                            },
                            authorize,
                        )
                        .map(|(generation, reclaimed)| {
                            serde_json::json!({
                                "action": "expire-result-body",
                                "commandId": command.hex(),
                                "generation": generation.to_string(),
                                "reclaimedResultBytes": reclaimed.to_string(),
                            })
                        })
                } else {
                    owner
                        .reviewed_step(engine, clock, expected_generation, authorize)
                        .map(|progress| {
                            serde_json::json!({
                                "action": "sweep-result-bodies",
                                "resultMaintenance": describe(&progress),
                            })
                        })
                };
                match result {
                    Ok(report) => {
                        worker.check().map_err(|_| StoreError::CommitUncertain)?;
                        Ok(Ok(report))
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
        .map_err(|error| {
            if command.is_some() {
                let code = match error {
                    AtomicError::NotFound => latent_core::PlatformErrorCode::NotFound,
                    AtomicError::Conflict => latent_core::PlatformErrorCode::StateConflict,
                    AtomicError::PermissionDenied => {
                        latent_core::PlatformErrorCode::PermissionDenied
                    }
                    AtomicError::Limit => latent_core::PlatformErrorCode::ResourceExhausted,
                    _ => latent_core::PlatformErrorCode::Unavailable,
                };
                return crate::standalone::error(code, "protected-result-maintenance");
            }
            failure(format!("protected-result-maintenance:{error:?}"))
        })
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

//! Bounded native actions, independently observed original storage retirement.
use super::{
    codecs::Codecs,
    request::{Action, File},
};
use latent_core::{native_capacity::NativeBufferPermit, PlatformError};
use latent_effects::{
    dispatch_store::DispatchCatalog,
    recovery_close::{inspect, prepare, CloseScope},
};
use latent_state::{
    embedded::{AtomicBatch, FencedStoreError, StoreError},
    protected_store::{
        ProtectedCheckpointConfig, ProtectedRestoreDestinationConfig, ProtectedSnapshot,
        ProtectedSnapshotConfig, ProtectedStoreOwner, RestoreInputPrecondition,
        RestoreStageRequest,
    },
    recovery::{
        namespace_resume::{NamespaceResumePlan, NamespaceResumeRequest},
        snapshot::{SnapshotMetadata, SnapshotReceipt},
        RecoveryGuard,
    },
    store_io::{StoreIoKind, StoreIoShutdown},
};
use serde::Serialize;
use std::{sync::Arc, time::Instant};

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeRecoveryReport {
    schema_version: &'static str,
    operation_succeeded: bool,
    failure: Option<Failure>,
    result: Option<serde_json::Value>,
    retirement: Retirement,
    pub(in crate::standalone) catalogs_retired: bool,
    #[serde(skip)]
    pins: Option<Arc<Codecs>>,
    #[serde(skip)]
    _response: NativeBufferPermit,
    #[serde(skip)]
    encoded: NativeBufferPermit,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Retirement {
    clean: bool,
    physically_retired: bool,
    live_workers: usize,
    accepted_jobs: usize,
    threads_joined: Option<usize>,
}

#[derive(Serialize)]
struct Failure {
    code: &'static str,
    message: String,
    retryable: bool,
}
impl NativeRecoveryReport {
    pub(in crate::standalone) fn retire_catalog_pins(&mut self) {
        self.pins.take();
    }
    pub(super) fn new(
        result: Result<serde_json::Value, PlatformError>,
        retired: StoreIoShutdown,
        joined: Option<usize>,
        pins: Option<Arc<Codecs>>,
        response: NativeBufferPermit,
        encoded: NativeBufferPermit,
    ) -> Self {
        let snapshot = retired.snapshot;
        let (operation_succeeded, result, failure) = match result {
            Ok(value) => (true, Some(value), None),
            Err(error) => (
                false,
                None,
                Some(Failure {
                    code: error.code.wire_code(),
                    message: error.message.chars().take(1024).collect(),
                    retryable: error.retryable,
                }),
            ),
        };
        Self {
            schema_version: "latent.native-transaction-recovery.v2",
            operation_succeeded,
            failure,
            result,
            retirement: Retirement {
                clean: retired.clean && snapshot.physically_retired() && joined.is_some(),
                physically_retired: snapshot.physically_retired(),
                live_workers: snapshot.live_workers,
                accepted_jobs: snapshot.accepted,
                threads_joined: joined,
            },
            catalogs_retired: false,
            pins,
            _response: response,
            encoded,
        }
    }
    pub fn encode(
        self,
    ) -> Result<latent_core::native_capacity::NativeBuffer<Vec<u8>>, PlatformError> {
        let mut output = BoundedOutput(Vec::new());
        output
            .0
            .try_reserve_exact(2 * 1024 * 1024)
            .map_err(|_| super::capacity())?;
        if output.0.capacity() > 2 * 1024 * 1024 {
            return Err(super::capacity());
        }
        serde_json::to_writer(&mut output, &self).map_err(|_| super::capacity())?;
        Ok(self.encoded.attach(output.0))
    }
}

struct BoundedOutput(Vec<u8>);
impl std::io::Write for BoundedOutput {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        if bytes.len() > 2 * 1024 * 1024 - self.0.len() {
            return Err(std::io::ErrorKind::FileTooLarge.into());
        }
        self.0.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

#[expect(
    clippy::too_many_lines,
    reason = "The affine snapshot and staged input stay in one action scope through exact acknowledgement, writer acceptance and physical retirement"
)]
pub(super) async fn execute(
    store: &ProtectedStoreOwner,
    codecs: Arc<Codecs>,
    settings: &crate::config::state::StateSettings,
) -> Result<serde_json::Value, PlatformError> {
    match &codecs.action {
        Action::Snapshot { operation_id, file } => {
            snapshot(store, Arc::clone(&codecs), operation_id, file).await
        }
        Action::InspectRestore {
            file,
            destination_root,
            destination_checkpoint_root,
            operation_id,
            snapshot_digest,
            manifest_digest,
        }
        | Action::Restore {
            file,
            destination_root,
            destination_checkpoint_root,
            operation_id,
            snapshot_digest,
            manifest_digest,
            ..
        } => {
            let mut destination = settings.store.clone();
            destination.root = destination_root.clone();
            destination.create_if_missing = true;
            let destination = ProtectedRestoreDestinationConfig {
                store: destination,
                checkpoint: ProtectedCheckpointConfig {
                    root: destination_checkpoint_root.clone(),
                },
                identity: settings.store_identity.clone(),
            };
            let row = Arc::clone(&codecs);
            let current = Arc::clone(&codecs);
            let (snapshot, opened) = awaited(
                store
                    .open_snapshot_for_restore_profile(
                        file_config(file),
                        destination,
                        Arc::clone(&codecs.original),
                        move |key, bytes| row.row(key, bytes),
                        Arc::new(move || current.check()),
                        codecs.authority.file_bytes,
                        latent_state::protected_store::ProtectedSnapshotProfile::SingleNamespace,
                    )
                    .map_err(protected)?,
                &codecs,
            )
            .await?;
            let input = opened.map_err(protected)?.map_err(snapshot_error);
            if let Err(error) = input {
                retire(snapshot, &codecs).await;
                return Err(error);
            }
            let precondition = RestoreInputPrecondition {
                snapshot_digest: super::assets::digest_bytes(snapshot_digest)?,
                manifest_digest: super::assets::digest_bytes(manifest_digest)?,
            };
            let (snapshot, reviewed) = awaited(
                store
                    .review_restore_window(
                        snapshot,
                        precondition,
                        Arc::clone(&codecs)
                            as Arc<dyn latent_state::protected_store::RestoreInputOwners>,
                    )
                    .map_err(protected)?,
                &codecs,
            )
            .await?;
            let input = match reviewed.map_err(protected)?.map_err(snapshot_error) {
                Ok(input) => input,
                Err(error) => {
                    retire(snapshot, &codecs).await;
                    return Err(error);
                }
            };
            if let Action::Restore {
                window_acknowledgement,
                ..
            } = &codecs.action
            {
                let request = RestoreStageRequest {
                    operation_id: operation_id.clone(),
                    operator_id: codecs.authority.actor.clone(),
                    runtime_digest: codecs.runtime,
                    loss_window_acknowledgement: super::assets::digest_bytes(
                        window_acknowledgement,
                    )?,
                };
                let (snapshot, result) = awaited(
                    store
                        .stage_restore(
                            snapshot,
                            input,
                            request,
                            Arc::clone(&codecs)
                                as Arc<dyn latent_state::protected_store::RestoreStageOwners>,
                        )
                        .map_err(protected)?,
                    &codecs,
                )
                .await?;
                let outcome = result
                    .map_err(protected)?
                    .map_err(|error| failure(format!("restore-stage:{error:?}")));
                let retired = retire(snapshot, &codecs).await;
                let receipt = outcome?;
                Ok(
                    serde_json::json!({"action":"restore", "operationDigest":digest(receipt.operation_digest()),
                        "snapshotDigest":digest(receipt.input().snapshot().snapshot_digest),
                        "manifestDigest":digest(receipt.input().snapshot().manifest_digest),
                        "destinationIdentity":receipt.checkpoint().identity().as_str(),
                        "checkpoint":receipt.checkpoint().encode(), "importedRows":receipt.imported_rows().to_string(),
                        "resourcePhysicallyRetired":retired, "pausedForReconciliation":true}),
                )
            } else {
                let value = serde_json::json!({"action":"inspect-restore", "snapshot":snapshot_value(input.snapshot()), "windowDigest":digest(input.window().digest().map_err(storage)?), "window":input.window()});
                drop(input);
                let retired = retire(snapshot, &codecs).await;
                Ok(with_retirement(value, retired))
            }
        }
        Action::StageMigration { .. } | Action::CompleteMigration { .. } => {
            migration(store, codecs).await
        }
        Action::ResumeMigration { .. } => resume_migration(store, codecs).await,
        Action::ResumeRestoredMigration { .. } => resume_restored_migration(store, codecs).await,
        _ => metadata_action(store, codecs, settings).await,
    }
}

async fn resume_restored_migration(
    store: &ProtectedStoreOwner,
    codecs: Arc<Codecs>,
) -> Result<serde_json::Value, PlatformError> {
    let Action::ResumeRestoredMigration {
        operation_id,
        migration_operation_id,
        file,
        expected_view,
        snapshot_digest,
        manifest_digest,
        window_acknowledgement,
    } = &codecs.action
    else {
        return Err(super::denied());
    };
    let (operation, migration, expected) = (
        operation_id.clone(),
        migration_operation_id.clone(),
        expected_view.clone(),
    );
    let (snapshot_digest, manifest_digest, window_digest) = (
        super::assets::digest_bytes(snapshot_digest)?,
        super::assets::digest_bytes(manifest_digest)?,
        super::assets::digest_bytes(window_acknowledgement)?,
    );
    let selected = Arc::clone(&codecs);
    let request=awaited(store.with_store_retaining(StoreIoKind::RecoveryRead,1024*1024,
        Arc::clone(&codecs) as Arc<dyn std::any::Any+Send+Sync>,move |engine| {
            let view=engine.snapshot()?;
            Ok((|| { selected.closure(&view)?;
                Ok::<_,StoreError>(latent_state::recovery::restored_resume::RestoredMigrationResumeRequest {
                    scope:selected.selected_view(&view)?.scope(),operation_id:operation,
                    operator_id:selected.authority.actor.clone(),migration_operation_id:migration,
                    expected_view:expected,snapshot_digest,manifest_digest,window_digest,review_digest:selected.review,
                    restore_operation_digest:latent_state::recovery::RecoveryGuard::capture(&view)?.ok_or(StoreError::Unavailable)?.operation_digest(),
                })
            })())
        }).map_err(protected)?,&codecs).await?.map_err(protected)?.map_err(storage)?;
    let row = Arc::clone(&codecs);
    let current = Arc::clone(&codecs);
    let (snapshot, opened) = awaited(
        store
            .open_snapshot_profile(
                file_config(file),
                Arc::clone(&codecs.original),
                move |key, bytes| row.row(key, bytes),
                Arc::new(move || current.check()),
                codecs.authority.file_bytes,
                latent_state::protected_store::ProtectedSnapshotProfile::SingleNamespace,
            )
            .map_err(protected)?,
        &codecs,
    )
    .await?;
    if let Err(error) = opened.map_err(protected)?.map_err(snapshot_error) {
        retire(snapshot, &codecs).await;
        return Err(error);
    }
    let (snapshot, result) = awaited(
        store
            .resume_restored_migration(
                snapshot,
                request,
                codecs.catalog.primary().schema.clone(),
                Arc::clone(&codecs)
                    as Arc<dyn latent_state::protected_store::RestoredMigrationResumeOwners>,
            )
            .map_err(protected)?,
        &codecs,
    )
    .await?;
    let result = result
        .map_err(protected)?
        .map_err(|error| failure(format!("protected-restored-migration-resume:{error:?}")));
    let retired = retire(snapshot, &codecs).await;
    let receipt = result?;
    Ok(
        serde_json::json!({"action":"resume-restored-migration","receipt":receipt.receipt().encode().map_err(storage)?,
        "view":receipt.receipt().view_token().map_err(storage)?,"replay":receipt.replayed(),
        "snapshotDigest":digest(snapshot_digest),"manifestDigest":digest(manifest_digest),
        "windowAcknowledgement":digest(window_digest),"reviewDigest":digest(codecs.review),
        "resourcePhysicallyRetired":retired}),
    )
}

async fn resume_migration(
    store: &ProtectedStoreOwner,
    codecs: Arc<Codecs>,
) -> Result<serde_json::Value, PlatformError> {
    let Action::ResumeMigration {
        operation_id,
        migration_operation_id,
        file,
        expected_view,
        migration_expected_view,
        checkpoint_digest,
        checkpoint_manifest_digest,
    } = &codecs.action
    else {
        return Err(super::denied());
    };
    let selected = Arc::clone(&codecs);
    let operation = operation_id.clone();
    let migration_operation = migration_operation_id.clone();
    let expected = expected_view.clone();
    let migration_view = migration_expected_view.clone();
    let snapshot_digest = checkpoint_digest.clone();
    let manifest_digest = checkpoint_manifest_digest.clone();
    let request = awaited(
        store
            .with_store_retaining(
                StoreIoKind::RecoveryRead,
                1024 * 1024,
                Arc::clone(&codecs) as Arc<dyn std::any::Any + Send + Sync>,
                move |engine| {
                    let view = engine.snapshot()?;
                    Ok((|| {
                        let migration = selected.migration_request(
                            &view,
                            &migration_operation,
                            &migration_view,
                            &snapshot_digest,
                            &manifest_digest,
                        )?;
                        Ok::<_, StoreError>(
                            latent_state::recovery::resume::MigrationResumeRequest {
                                scope: selected.selected_view(&view)?.scope(),
                                operation_id: operation,
                                operator_id: selected.authority.actor.clone(),
                                expected_view: expected,
                                migration,
                                review_digest: selected.review,
                            },
                        )
                    })())
                },
            )
            .map_err(protected)?,
        &codecs,
    )
    .await?
    .map_err(protected)?
    .map_err(storage)?;
    let row = Arc::clone(&codecs);
    let current = Arc::clone(&codecs);
    let (snapshot, opened) = awaited(
        store
            .open_snapshot_profile(
                file_config(file),
                Arc::clone(&codecs.original),
                move |key, bytes| row.row(key, bytes),
                Arc::new(move || current.check()),
                codecs.authority.file_bytes,
                latent_state::protected_store::ProtectedSnapshotProfile::SingleNamespace,
            )
            .map_err(protected)?,
        &codecs,
    )
    .await?;
    let opened = opened.map_err(protected)?.map_err(snapshot_error);
    if let Err(error) = opened {
        retire(snapshot, &codecs).await;
        return Err(error);
    }
    let (snapshot, result) = awaited(
        store
            .resume_migration(
                snapshot,
                request,
                codecs.catalog.primary().schema.clone(),
                Arc::clone(&codecs)
                    as Arc<dyn latent_state::protected_store::AggregateMigrationOwners>,
            )
            .map_err(protected)?,
        &codecs,
    )
    .await?;
    let outcome = result
        .map_err(protected)?
        .map_err(|error| failure(format!("protected-migration-resume:{error:?}")));
    let retired = retire(snapshot, &codecs).await;
    let receipt = outcome?;
    Ok(
        serde_json::json!({"action":"resume-migration", "receipt":receipt.receipt().encode().map_err(storage)?,
        "view":receipt.receipt().view_token().map_err(storage)?, "resourcePhysicallyRetired":retired}),
    )
}

async fn migration(
    store: &ProtectedStoreOwner,
    codecs: Arc<Codecs>,
) -> Result<serde_json::Value, PlatformError> {
    let (Action::StageMigration {
        operation_id,
        file,
        expected_view,
        checkpoint_digest,
        checkpoint_manifest_digest,
    }
    | Action::CompleteMigration {
        operation_id,
        file,
        expected_view,
        checkpoint_digest,
        checkpoint_manifest_digest,
    }) = &codecs.action
    else {
        return Err(super::denied());
    };
    let selected = Arc::clone(&codecs);
    let operation = operation_id.clone();
    let view_token = expected_view.clone();
    let snapshot_digest = checkpoint_digest.clone();
    let manifest_digest = checkpoint_manifest_digest.clone();
    let request = awaited(
        store
            .with_store_retaining(
                StoreIoKind::RecoveryRead,
                1024 * 1024,
                Arc::clone(&codecs) as Arc<dyn std::any::Any + Send + Sync>,
                move |engine| {
                    let view = engine.snapshot()?;
                    Ok(selected.migration_request(
                        &view,
                        &operation,
                        &view_token,
                        &snapshot_digest,
                        &manifest_digest,
                    ))
                },
            )
            .map_err(protected)?,
        &codecs,
    )
    .await?
    .map_err(protected)?
    .map_err(storage)?;
    let row = Arc::clone(&codecs);
    let current = Arc::clone(&codecs);
    let (snapshot, opened) = awaited(
        store
            .open_snapshot_profile(
                file_config(file),
                Arc::clone(&codecs.original),
                move |key, bytes| row.row(key, bytes),
                Arc::new(move || current.check()),
                codecs.authority.file_bytes,
                latent_state::protected_store::ProtectedSnapshotProfile::SingleNamespace,
            )
            .map_err(protected)?,
        &codecs,
    )
    .await?;
    let opened = opened.map_err(protected)?.map_err(snapshot_error);
    if let Err(error) = opened {
        retire(snapshot, &codecs).await;
        return Err(error);
    }
    let phase = if matches!(codecs.action, Action::StageMigration { .. }) {
        latent_state::recovery::migration::MigrationPhase::Stage
    } else {
        latent_state::recovery::migration::MigrationPhase::Complete
    };
    let (snapshot, result) = awaited(
        store
            .migrate_aggregate(
                snapshot,
                request,
                codecs.catalog.primary().schema.clone(),
                (
                    latent_state::recovery::migration::AggregateMigrationRecipe::JavaAggregate,
                    phase,
                ),
                Arc::clone(&codecs)
                    as Arc<dyn latent_state::protected_store::AggregateMigrationOwners>,
            )
            .map_err(protected)?,
        &codecs,
    )
    .await?;
    let outcome = result
        .map_err(protected)?
        .map_err(|error| failure(format!("protected-migration:{error:?}")));
    let retired = retire(snapshot, &codecs).await;
    let receipt = outcome?;
    Ok(
        serde_json::json!({"action":if phase == latent_state::recovery::migration::MigrationPhase::Stage {"stage-migration"} else {"complete-migration"},
        "receipt":receipt.progress().encode().map_err(storage)?, "completed":receipt.progress().completed(), "resourcePhysicallyRetired":retired}),
    )
}

async fn snapshot(
    store: &ProtectedStoreOwner,
    codecs: Arc<Codecs>,
    operation: &str,
    file: &File,
) -> Result<serde_json::Value, PlatformError> {
    let metadata = SnapshotMetadata {
        tenant: codecs.catalog.primary().operation.target().tenant.0.clone(),
        operation_id: operation.into(),
        operator_id: codecs.authority.actor.clone(),
        runtime_digest: codecs.runtime,
        decoder_formats: codecs.catalog.formats.clone(),
        required_artifacts: codecs.catalog.artifacts.clone(),
    };
    let view = Arc::clone(&codecs);
    let artifact = Arc::clone(&codecs);
    let row = Arc::clone(&codecs);
    let current = Arc::clone(&codecs);
    let (snapshot, result) = awaited(
        store
            .create_reviewed_snapshot_profile(
                file_config(file),
                metadata,
                Arc::clone(&codecs.original),
                move |source| {
                    view.closure(source)
                        .map_err(latent_state::recovery::snapshot::SnapshotError::Review)
                },
                move |required| artifact.artifact(required),
                move |key, bytes| row.row(key, bytes),
                Arc::new(move || current.check()),
                codecs.authority.file_bytes,
                latent_state::protected_store::ProtectedSnapshotProfile::SingleNamespace,
            )
            .map_err(protected)?,
        &codecs,
    )
    .await?;
    let outcome = result.map_err(protected)?.map_err(snapshot_error);
    let retired = retire(snapshot, &codecs).await;
    Ok(with_retirement(snapshot_value(&outcome?), retired))
}

async fn metadata_action(
    store: &ProtectedStoreOwner,
    codecs: Arc<Codecs>,
    settings: &crate::config::state::StateSettings,
) -> Result<serde_json::Value, PlatformError> {
    let worker = Arc::clone(&codecs);
    let memory = codecs
        .original
        .reserve_buffer(
            latent_core::native_capacity::NativeBufferClass::Work,
            8 * 1024 * 1024,
        )
        .map_err(|_| super::capacity())?;
    let job = store.with_store_retaining(StoreIoKind::RecoveryWrite, 8 * 1024 * 1024, Arc::clone(&codecs) as Arc<dyn std::any::Any + Send + Sync>, move |engine| {
        let _memory = memory;
        let outcome = (|| {
            let view = engine.snapshot()?;
            worker.closure(&view)?;
            let observed = worker.selected_view(&view)?;
            let mut batch = AtomicBatch::default();
            let mut time_changed = false;
            let result = match &worker.action {
                Action::InspectNamespace {} => serde_json::json!({"action":"inspect-namespace", "namespace":observed.namespace.encode().map_err(|_| StoreError::Corrupt)?, "history":observed.history.encode().map_err(|_| StoreError::Corrupt)?, "view":observed.view_token()?, "guard":observed.guard.as_ref().map(RecoveryGuard::encode).transpose()?, "reviewDigest":digest(worker.review)}),
                Action::InspectCloseEffects { operation_id, effect_ids, reason } => {
                    let plan = inspect(&view, close_scope(&worker), worker.authority.actor.clone(), operation_id.clone(), effect_ids.clone(), reason.clone())?;
                    serde_json::json!({"action":"inspect-close-effects", "acknowledgement":digest(plan.digest()?), "plan":plan})
                },
                Action::CloseEffects { operation_id, plan, acknowledgement } => {
                    let acknowledgement = super::assets::digest_bytes(acknowledgement).map_err(|_| StoreError::Invalid)?;
                    let prepared = prepare(&view, plan, &close_scope(&worker), &worker.authority.actor, operation_id, acknowledgement, worker.time()?)?;
                    batch = prepared.batch;
                    if !prepared.replay { append(&mut batch, DispatchCatalog::prepare_offline_clock(&view, latent_effects::authority::EffectTime { unix_millis: prepared.receipt.observed_at_millis, continuity_proven: true })?)?; time_changed = true; }
                    serde_json::json!({"action":"close-effects", "receipt":prepared.receipt, "replay":prepared.replay})
                },
                Action::Review {} => {
                    worker.closure(&view)?.inventory.require_retirement_drained().map_err(|_| StoreError::Unavailable)?;
                    let guard = observed.guard.as_ref().ok_or(StoreError::Unavailable)?;
                    batch = guard.prepare_reviewed(&view, worker.review, |_, _, _| worker.check())?;
                    serde_json::json!({"action":"review", "reviewDigest":digest(worker.review)})
                },
                Action::Resume { operation_id, expected_view } => {
                    worker.closure(&view)?.inventory.require_retirement_drained().map_err(|_| StoreError::Unavailable)?;
                    let request = NamespaceResumeRequest { scope: observed.scope(), operation_id: operation_id.clone(), operator_id: worker.authority.actor.clone(), expected_view: expected_view.clone(), review_digest: worker.review };
                    let plan = NamespaceResumePlan::prepare(&view, &request, |_, _, _| worker.check())?;
                    let result = serde_json::json!({"action":"resume", "receipt":plan.receipt().encode()?, "view":plan.receipt().view_token()?, "replay":plan.replayed()});
                    batch = plan.into_batch();
                    result
                },
                _ => return Err(StoreError::Invalid),
            };
            drop(view);
            if !batch.expectations.is_empty() || !batch.mutations.is_empty() {
                engine.apply_fenced(batch, || worker.fence(worker.action.purposes()[0], || worker.original.with_live(|| ()).map_err(|_| StoreError::SnapshotExpired)))
                    .map_err(|error| match error { FencedStoreError::Store(error) | FencedStoreError::Fence(error) => error })?;
            }
            worker.check().map_err(|_| StoreError::CommitUncertain)?;
            Ok((result, time_changed))
        })();
        Ok(outcome)
    }).map_err(protected)?;
    let (result, changed) = awaited(job, &codecs)
        .await?
        .map_err(protected)?
        .map_err(storage)?;
    if changed {
        seal(store, &codecs, settings).await?;
    }
    Ok(result)
}

async fn seal(
    store: &ProtectedStoreOwner,
    codecs: &Codecs,
    settings: &crate::config::state::StateSettings,
) -> Result<(), PlatformError> {
    let (checkpoint, opened) = awaited(
        store
            .open_checkpoint(
                ProtectedCheckpointConfig {
                    root: settings.checkpoint_root.clone(),
                },
                codecs.identity.clone(),
                None,
                Arc::clone(&codecs.original),
                DispatchCatalog::checkpoint,
            )
            .map_err(protected)?,
        codecs,
    )
    .await?;
    opened.map_err(protected)?;
    let (checkpoint, result) = awaited(
        store
            .advance_checkpoint(
                checkpoint,
                Some(codecs.checkpoint.clone()),
                codecs.authority.clock.covered_epoch()?,
                DispatchCatalog::checkpoint,
            )
            .map_err(protected)?,
        codecs,
    )
    .await?;
    let result = result.map_err(protected);
    checkpoint.retire().await;
    result.map(|_| ())
}

fn append(batch: &mut AtomicBatch, other: AtomicBatch) -> Result<(), StoreError> {
    for expected in other.expectations {
        if let Some(prior) = batch
            .expectations
            .iter()
            .find(|prior| prior.key == expected.key)
        {
            if prior.value != expected.value {
                return Err(StoreError::Conflict);
            }
        } else {
            batch.expectations.push(expected);
        }
    }
    for mutation in other.mutations {
        if batch
            .mutations
            .iter()
            .any(|prior| prior.key == mutation.key)
        {
            return Err(StoreError::Conflict);
        }
        batch.mutations.push(mutation);
    }
    Ok(())
}
fn close_scope(codecs: &Codecs) -> CloseScope {
    let operation = &codecs.catalog.primary().operation;
    CloseScope {
        tenant: operation.target().tenant.0.clone(),
        namespace: operation.namespace().into(),
        incarnation: operation.incarnation(),
    }
}
fn file_config(file: &File) -> ProtectedSnapshotConfig {
    ProtectedSnapshotConfig {
        root: file.root.clone(),
        file_name: file.name.clone(),
    }
}
fn snapshot_value(receipt: &SnapshotReceipt) -> serde_json::Value {
    serde_json::json!({"action":"snapshot", "snapshotDigest":digest(receipt.snapshot_digest), "manifestDigest":digest(receipt.manifest_digest), "fileBytes":receipt.file_bytes.to_string(), "manifest":receipt.manifest})
}
fn with_retirement(mut value: serde_json::Value, retired: bool) -> serde_json::Value {
    value["resourcePhysicallyRetired"] = retired.into();
    value
}
pub(super) fn digest(bytes: [u8; 32]) -> String {
    format!("sha256:{:x}", latent_core::digest::HexDigest(bytes))
}
async fn retire(mut snapshot: ProtectedSnapshot, codecs: &Codecs) -> bool {
    let witness = snapshot.retirement_witness();
    let cutoff = Instant::now() + std::time::Duration::from_secs(5);
    let _observation = tokio::time::timeout_at(cutoff.into(), snapshot.retire()).await;
    let _ = codecs;
    witness.is_some_and(|witness| witness.has_retired())
}
async fn awaited<T, E: std::fmt::Debug>(
    future: impl std::future::Future<Output = Result<T, E>>,
    codecs: &Codecs,
) -> Result<T, PlatformError> {
    tokio::time::timeout_at(codecs.authority.deadline.into(), future)
        .await
        .map_err(|_| failure("native-original-deadline".into()))?
        .map_err(|error| failure(format!("native-original-job:{error:?}")))
}
fn protected(error: latent_state::protected_store::ProtectedStoreError) -> PlatformError {
    failure(format!("protected-owner:{error:?}"))
}
fn snapshot_error(error: latent_state::recovery::snapshot::SnapshotError) -> PlatformError {
    failure(format!("protected-snapshot:{error:?}"))
}
fn storage(error: StoreError) -> PlatformError {
    failure(format!("native-review:{error:?}"))
}
fn failure(message: String) -> PlatformError {
    PlatformError {
        code: latent_core::PlatformErrorCode::Unavailable,
        message,
        retryable: false,
        details: Vec::new(),
    }
}

#[cfg(test)]
mod tests;
